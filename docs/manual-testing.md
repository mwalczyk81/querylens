# Manual Testing & Release Qualification Guide

**Target Feature**: `002-query-cost-discovery` (`querylens discover`)
**Audience**: Maintainers, Release Engineers, Developers

---

## 1. Why Manual Testing is Required

> [!IMPORTANT]
> **KQL is Never Executed in CI Pipelines**
>
> In accordance with Constitution Principle I (Read-Only Safety) and Principle III (Offline CI Verification), QueryLens automated test suites run with **zero live cloud dependencies**. CI tests utilize 100% synthetic `LogsTable` fixtures and golden snapshot tests.
>
> **Snapshot tests protect strictly against unintended query text regressions, NOT against semantic KQL execution correctness on live Azure backends.**
>
> Therefore, **every release containing discovery features MUST be gated on a successful manual validation run** following the procedure below.

---

## 2. Release Qualification Checklist

> [!TIP]
> **Claude Code Live-Gate Prompt**: To execute this qualification procedure interactively with Claude Code after signing in to Azure, use the instructions in [Live Workspace Qualification Gate](live-gate.md).

Before cutting any release tag (e.g. `v0.2.0`), perform the following steps against a real Azure Log Analytics workspace connected to an active Cosmos DB account:

- [ ] **Step 1: KQL Syntax & Query Inspection (`--print-kql` and `--check --print-kql`)**
- [ ] **Step 2: Preflight Diagnostic Check (`querylens discover --check`)**
- [ ] **Step 3: End-to-End Discovery Run (`querylens discover`)**
- [ ] **Step 4: Machine-Readable JSON Validation (`--json`)**
- [ ] **Step 5: Query Text Privacy Verification (default vs `--show-text`)**
- [ ] **Step 6: Caller Attribution Verification (guid/ip fallback & shares <= 100%)**
- [ ] **Step 7: Silent-Zero Guard Verification (misconfigured telemetry handling)**

---

## 3. Step-by-Step Qualification Procedure

### Step 1: KQL Syntax & Query Inspection in Azure Portal (`--print-kql`)

QueryLens provides offline `--print-kql` inspection for both the Discovery engine and the Preflight Diagnostic Check. Both queries must be validated in the Azure Portal Logs query editor prior to release.

1. Authenticate with Azure CLI:

   ```bash
   az login
   ```

2. Generate Discovery KQL queries using `--print-kql`:

   ```bash
   uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --account <YOUR_ACCOUNT_NAME> --print-kql
   ```

   The output contains two demarcated sections:
   - `// === Query 1: Top Query Shapes Query ===`
   - `// === Query 2: Window & Attributed Totals Query ===`

3. Generate Preflight Check KQL query using `--check --print-kql`:

   ```bash
   uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --check --print-kql
   ```

   The output contains:
   - `// === Preflight Diagnostic Check Query ===`

4. Open the **Azure Portal**, navigate to your target **Log Analytics workspace**, and open the **Logs** query editor.

#### Validating Query 1 (Top Shapes)

1. Copy Query 1 from terminal output, paste it into the query editor, and click **Run**.
2. **Pass Criteria**:
   - Compiles and runs cleanly without semantic, syntax, or memory limit errors.
   - Note: Query 1 wraps `ql_resolved_activities` in `materialize()` to avoid evaluating the container-scoped database-resolution join twice. Confirm this executes cleanly on live workspace telemetry.
   - All columns (`numberofrowsreturned_s`, `requestCharge_s`, `shapesignature_s`, `activityId_g`, etc.) resolve cleanly via `column_ifexists()`.
   - Results return at most $N$ rows (where $N$ is `--top`).
   - The `ql_top_callers` column produces a valid JSON dynamic array with up to 3 caller objects per shape.

#### Validating Query 2 (Totals)

1. Copy Query 2 from terminal output, paste it into the query editor, and click **Run**.
2. **Pass Criteria**:
   - Compiles and runs cleanly, returning exactly **1 row** with columns:
     - `ql_window_total_ru`: Non-negative float representing all `DataPlaneRequests` in scope and window.
     - `ql_attributed_total_ru`: Non-negative float representing RU of all joined queries.
     - `ql_total_executions`: Non-negative integer.
     - `ql_min_time_generated`: Earliest timestamp observed in the window.

#### Validating Preflight Check Query

1. Copy the Preflight Diagnostic Check query, paste it into the query editor, and click **Run**.
2. **Pass Criteria**:
   - Compiles and runs cleanly, returning category rows and populated column counts.
   - Dynamic bag `ql_auth_breakdown` resolves as a valid property bag.

---

### Step 2: Preflight Diagnostic Check (`--check`)

Run the preflight health check command against the live workspace:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --check
```

**Pass Criteria**:

- Successfully displays category row counts (`DataPlaneRequests`, `QueryRuntimeStatistics`).
- Displays time boundaries and retention health without error.
- Displays column population percentages (0.0% to 100.0%).
- Emits masked workspace ID (e.g. `...abcd`).
- Confirms zero customer query text or data values appear in the output.

---

### Step 3: End-to-End Discovery Run (`querylens discover`)

Execute cost discovery against the live workspace:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --top 10
```

**Pass Criteria**:

- Rich terminal table renders with header summary.
- Displays total window RU and unattributed RU summary.
- Ranked query shapes sorted descending by total RU.
- `Top Callers` column displays caller GUIDs or IPs with individual RU share percentages.
- `Sample Query` column truncates query text to 200 characters.

---

### Step 4: Machine-Readable JSON Validation (`--json`)

Run discovery with JSON export:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --top 10 --json > live-test.json
```

**Pass Criteria**:

- Emits valid JSON to `stdout` matching `contracts/discover-output-schema.json`.
- Crucially, verify that `sample_query_text` is **omitted** from each result item in default JSON mode (FR-012).

---

### Step 5: Privacy Validation with `--show-text`

Run discovery with `--show-text`:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --top 10 --show-text --json > live-text-included.json
```

**Pass Criteria**:

- `sample_query_text` is now **present** in each result item in JSON output.
- Terminal table shows full query text without truncation.

---

### Step 6: Caller Attribution Verification

Inspect caller attribution in the discovery terminal table and JSON output:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --top 10
```

**Pass Criteria**:

- "Top Callers" column lists up to 3 callers per shape with identifier and RU share %.
- Identifiers display Entra ID principal GUIDs when present, falling back to client IP addresses.
- Each caller's RU share percentage is bounded between 0.0% and 100.0%.
- Callers are omitted without error if both principal GUID and client IP are absent.

---

### Step 7: Silent-Zero Guard Verification

Test behavior against an account where query diagnostic logging is unconfigured or where `attributed_total_ru` is 0:

```bash
uv run querylens discover --workspace-id <YOUR_WORKSPACE_ID> --account <ACCOUNT_WITHOUT_RUNTIME_STATS>
```

**Pass Criteria**:

- Exits immediately with **exit code 1**.
- Emits a clear, actionable notice on `stderr` explaining that telemetry is incomplete and advising the user to run `querylens discover --check`.
- Does **not** render a misleading table of zeros or empty success.

---

## 4. Interactive Live-Gate Execution

For interactive, non-destructive validation of this procedure with Claude Code on a live workspace, refer to the full prompt in [Live Workspace Qualification Gate Prompt](live-gate.md).
