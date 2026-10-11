# Quickstart & Verification Guide: Cosmos DB Query Cost Discovery

**Feature**: `002-query-cost-discovery` (`querylens discover`)
**Date**: 2026-10-10
**Status**: Completed (Updated with Review Findings)

---

## Prerequisites

1. **Python Environment**: Python 3.12+ with project dependencies installed:

   ```bash
   uv sync
   ```

2. **Azure Entra ID Authentication** (for live runs against an actual Azure workspace):
   - User identity authenticated via Azure CLI (`az login`) or managed identity.
   - Entra role: `Log Analytics Reader` (or `Reader` / `Contributor`) assigned on the target Azure Log Analytics workspace.
3. **Target Workspace**: An Azure Log Analytics workspace where Azure Cosmos DB diagnostic settings send logs to the `AzureDiagnostics` destination table.

---

## 1. Inspecting & Validating KQL Offline (`--print-kql`)

Generate and print **both constructed KQL queries** (Query 1: Top Shapes, and Query 2: Window & Attributed Totals) to `stdout` without initiating any network calls or requiring Azure credentials:

### Print Default KQL Queries

```bash
uv run querylens discover --workspace-id 12345678-1234-1234-1234-123456789abc --print-kql
```

### Print KQL with Account Filter and Custom Top Limit

```bash
uv run querylens discover \
  --workspace-id 12345678-1234-1234-1234-123456789abc \
  --account cosmos-prod-eastus \
  --top 10 \
  --print-kql
```

**Use Case**: Prints two demarcated queries (`Query 1: Top Query Shapes` and `Query 2: Window & Attributed Totals`). Copy each query directly into the **Azure Portal Logs query editor** to verify syntax, column resolution, and performance against your live workspace schema before running automated queries.

---

## 2. Preflight Health Verification (`--check`)

Verify that the target Log Analytics workspace has active Cosmos DB diagnostic logging without retrieving query workloads.

### CLI Execution

```bash
uv run querylens discover --workspace-id 12345678-1234-1234-1234-123456789abc --check
```

### JSON Output (`--json`)

```bash
uv run querylens discover --workspace-id 12345678-1234-1234-1234-123456789abc --check --json
```

Conforms to [check-output-schema.json](file:///specs/002-query-cost-discovery/contracts/check-output-schema.json).

### Expected Console Output

```text
Log Analytics Diagnostic Preflight Check
Workspace: ...9abc (Window: 24h)

Diagnostic Categories:
  • DataPlaneRequests: 1,420,891 records
  • QueryRuntimeStatistics: 312,045 records

Log Retention & Time Boundaries:
  • Earliest Record: 2026-10-09 16:00:00 UTC
  • Latest Record:   2026-10-10 16:00:00 UTC
  • Retention Status: Healthy (data spans entire requested window)

Field Coverage:
  • requestCharge_s: 100.0%
  • activityId_g:    100.0%
  • shapesignature_s: 98.4%
  • querytext_s:      100.0%

Authentication Distribution:
  • Entra ID (AAD): 92.4%
  • Master Key:      7.6%
```

---

## 3. Workload Cost Discovery Execution

Discover top query shapes aggregated server-side across the target lookback window.

### Standard Terminal Report

```bash
uv run querylens discover --workspace-id 12345678-1234-1234-1234-123456789abc --top 10
```

### With Database Account Filter and Custom Time Window

```bash
uv run querylens discover \
  --workspace-id 12345678-1234-1234-1234-123456789abc \
  --account cosmos-prod-eastus \
  --time-window 7d \
  --top 20
```

### Machine-Readable Output (Privacy-Preserving Default)

```bash
uv run querylens discover \
  --workspace-id 12345678-1234-1234-1234-123456789abc \
  --top 10 \
  --json > discovery-report.json
```

> [!NOTE]
> **Privacy Invariant (FR-012)**: In default `--json` output, `sample_query_text` is **OMITTED** entirely from every result item. It is included only if `--show-text` is explicitly passed:
>
> ```bash
> uv run querylens discover --workspace-id 12345678-1234-1234-1234-123456789abc --show-text --json
> ```
>
> In terminal console tables, `sample_query_text` is truncated to 200 characters by default, and displayed in full when `--show-text` is passed.

Conforms to [discover-output-schema.json](file:///specs/002-query-cost-discovery/contracts/discover-output-schema.json).

### Expected Terminal Output

- Header summary panel displaying:
  - Masked workspace ID (`...9abc`)
  - Evaluated time window (start to end UTC)
  - Total RU across all DataPlaneRequests in scope (the denominator)
  - Unattributed RU and unattributed percentage (non-query point operations, writes)
  - Discovered query count
- Rich ranked table sorted descending by total RU:
  - Database & Container
  - Shape ID (first 8 characters)
  - Executions
  - Total RU
  - Avg RU
  - Max RU
  - RU Share %
  - Avg Rows Returned (derived from `numberofrowsreturned_s`)
  - RU / Row
  - 429 Throttle Count
  - Top 3 Callers (masked GUID or IP, with individual RU share %)
  - Sample Query Text (truncated to 200 chars unless `--show-text` is specified)

---

## 4. Local Cloud-Free Unit & Snapshot Verification

Run the automated test suite locally without Azure credentials or cloud access using synthetic test fixtures:

```bash
# Run unit tests covering KQL escaping, input validation, and parsing
uv run pytest tests/unit/test_discover_*.py -v

# Run contract tests asserting JSON query text omission and schema conformance
uv run pytest tests/unit/test_discover_contract.py -v

# Run golden snapshot tests verifying generated KQL strings for --print-kql
uv run pytest tests/unit/test_discover_kql_snapshots.py -v

# Run property-based injection tests via Hypothesis
uv run pytest tests/unit/test_discover_injection_property.py -v

# Run full quality suite with 85% coverage enforcement
uv run pytest --cov=querylens --cov-fail-under=85
```

> [!IMPORTANT]
> CI automated tests verify query text structure and regression avoidance, but do not execute KQL against live Azure backends. Refer to [docs/manual-testing.md](file:///docs/manual-testing.md) for the mandatory manual qualification checklist required before each release.

---

## 5. Exit Code Verification Scenarios

| Scenario | Invocation | Expected Exit Code | Expected Output |
| --- | --- | --- | --- |
| **Print KQL Query** | `uv run querylens discover --workspace-id <valid-uuid> --print-kql` | `0` | Formatted KQL query text to stdout |
| **Successful Discovery** | `uv run querylens discover --workspace-id <valid-uuid>` | `0` | Rich table or JSON to stdout |
| **Empty Results** | `uv run querylens discover --workspace-id <valid-uuid> --account empty-acct --json` | `0` | Valid JSON with `results: []` on stdout; notice on stderr |
| **Invalid Workspace ID** | `uv run querylens discover --workspace-id not-a-uuid` | `1` | `Error: Invalid workspace ID format. Must be an RFC 4122 UUID.` on stderr |
| **Invalid Account Filter** | `uv run querylens discover --workspace-id <uuid> --account "bad;name"` | `1` | `Error: Invalid account filter. Must match Cosmos DB account naming rules.` on stderr |
| **Silent-Zero Guard** | Telemetry misconfigured or 0 attributed RU | `1` | `Error: Diagnostic telemetry misconfigured. Run querylens discover --check.` on stderr |
| **Workspace Not Found (404)** | `uv run querylens discover --workspace-id <non-existent-uuid>` | `3` | `Error: Log Analytics workspace not found or unreachable.` on stderr |
| **Network Timeout** | Connection drops during query execution | `3` | `Error: Network connection or server timeout communicating with Azure Monitor.` on stderr |
| **Authentication Failure (401/403)** | Unauthenticated or lacks `Log Analytics Reader` | `5` | `Error: Authentication or authorization failed. Verify Entra credentials and Log Analytics Reader role.` on stderr |
