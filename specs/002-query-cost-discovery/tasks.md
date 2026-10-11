# Tasks: Cosmos DB Query Cost Discovery (`querylens discover`)

**Feature Branch**: `002-query-cost-discovery`
**Specification**: [spec.md](spec.md) | **Implementation Plan**: [plan.md](plan.md)
**Data Model**: [data-model.md](data-model.md) | **Research**: [research.md](research.md)
**Contracts**: [contracts/discover-output-schema.json](contracts/discover-output-schema.json), [contracts/check-output-schema.json](contracts/check-output-schema.json)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency pinning, package initialization, column mappings, and test fixture scaffolding.

- [x] T001 Pin azure-monitor-query==2.0.0 dependency in pyproject.toml, refresh uv.lock with uv lock, and confirm pip-audit and uv sync --locked pass
- [x] T002 Create discovery package layout with public exports in src/querylens/discovery/**init**.py
- [x] T003 [P] Create synthetic Azure Monitor Logs table and row fixtures in tests/fixtures/synthetic_logs.py
- [x] T004 [P] Implement type-safe KQL column mapping module with tostring and coalesce helpers in src/querylens/discovery/columns.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core domain models, validation schemas, and injection defenses that MUST be complete before any user story can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this foundational phase is complete.

- [x] T005 [P] Implement KQL string-literal escaping utility in src/querylens/discovery/kql.py and author property-based escaping tests in tests/unit/test_discover_injection_property.py
- [x] T006 Implement CLI options validation and DiscoveryOptions model in src/querylens/discovery/models.py quoting verbatim validation rules: workspace_id ("RFC 4122 UUIDv4 format (`uuid.UUID`). Rejects invalid with exit 1."), account_filter ("Optional. Regex `^[a-zA-Z0-9][-a-zA-Z0-9]{1,42}[a-zA-Z0-9]$`. Rejects invalid with exit 1."), time_window ("Duration string parsed into `timedelta` (`[1-9][0-9]*[mhd]`). Bounded: `5m` to `90d`."), top_n ("Integer bounded `1 <= top_n <= 100`. Rejects invalid with exit 1."), server_timeout_seconds ("Integer bounded `10 <= timeout <= 600`."), and boolean flags (show_text, check_only, print_kql, json_output)
- [x] T007 Implement Pydantic domain models and custom exceptions in src/querylens/discovery/models.py quoting verbatim constraints: CallerAttribution with identifier ("Non-empty string."), ru_share_pct ("`0.0 <= ru_share_pct <= 100.0`"), and identifier_type ("Must be `\"aad_principal\"` or `\"client_ip\"`."); DiscoveredQueryShape with database ("Non-empty string."), container ("Non-empty string."), shape_id ("Non-empty string, hex/hash format."), sample_query_text ("Optional string (`None` by default in JSON)."), execution_count ("`>= 1`"), total_ru ("`>= 0.0`"), avg_ru ("`>= 0.0`"), max_ru ("`>= 0.0`"), ru_share_pct ("`0.0 <= ru_share_pct <= 100.0`"), avg_returned_rows ("`>= 0.0`"), ru_per_returned_row ("Non-negative float or `None`."), throttled_count ("`>= 0`"), and top_callers ("Max 3 items."); WorkloadDiscoverySummary with window_start ("ISO 8601 UTC."), window_end ("ISO 8601 UTC, `window_end >= window_start`."), total_ru ("`>= 0.0`"), attributed_total_ru ("`>= 0.0`"), unattributed_ru ("`>= 0.0`"), unattributed_ru_pct ("`0.0 <= unattributed_ru_pct <= 100.0`"), discovered_query_count ("`>= 0`"), results ("Length bounded by `--top` (max 100)."), retention_warning ("Boolean."), and masked_workspace_id ("Format matching `...[0-9a-fA-F]{4}`."); PreflightCheckReport with categories_detected ("List of non-empty strings."), row_counts ("All counts `>= 0`."), window_start ("ISO 8601 UTC."), window_end ("ISO 8601 UTC."), earliest_record ("ISO 8601 UTC or `None`."), latest_record ("ISO 8601 UTC or `None`."), field_coverage ("Values between `0.0` and `1.0`."), auth_breakdown ("Non-negative integers."), retention_warning ("Boolean."), and masked_workspace_id ("Format matching `...[0-9a-fA-F]{4}`."); and exception classes TelemetryMisconfigurationError, DiscoveryAuthError, DiscoveryConnectionError, DiscoveryValidationError
- [x] T008 Author unit tests for model validation, boundary limits, and custom exceptions in tests/unit/test_discover_models.py

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Discover High-Cost Query Shapes from Log Analytics (Priority: P1) 🎯 MVP

**Goal**: Discover and rank top query shapes from Azure Log Analytics diagnostic logs using server-side KQL aggregation (Query 1: Top Shapes without callers, Query 2: Totals), enforce the Silent-Zero Guard, provide Rich console and JSON reporting, support offline KQL inspection via `--print-kql`, and validate live against Azure Portal and real workspace before proceeding.

**Independent Test**: Provide a target workspace ID and time window. Verify that baseline KQL queries build correctly without callers, transfer at most N shape rows plus 1 totals row, map into a ranked `WorkloadDiscoverySummary`, that Silent-Zero Guard terminates with exit 1 if `attributed_total_ru == 0` while `total_ru > 0`, that `--print-kql` prints both queries without network calls or credentials, and that `--json` conforms to `discover-output-schema.json`.

### Tests for User Story 1 🧪

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T009 [P] [US1] Author KQL query builder unit tests in tests/unit/test_discover_kql.py verifying construction of baseline Query 1 (Top Shapes WITHOUT callers) and Query 2 (Totals), `materialize()` wrapping, `activityId_g` pre-aggregation, `_ResourceId endswith` account clause, column fallbacks, and sha256 fallback when `shapesignature_s` is absent
- [x] T010 [P] [US1] Author golden snapshot tests for `--print-kql` output in tests/unit/test_discover_kql_snapshots.py verifying exact baseline KQL text for both queries (shapes without callers and totals) with and without account filters
- [x] T011 [P] [US1] Author discovery JSON contract tests in tests/unit/test_discover_contract.py validating synthetic discovery output WITHOUT callers against specs/002-query-cost-discovery/contracts/discover-output-schema.json
- [x] T012 [P] [US1] Author discovery service unit tests in tests/unit/test_discover_service.py using synthetic `LogsTable` fixtures to test two-query execution, row transformation into WorkloadDiscoverySummary without callers, unattributed RU calculation (`max(0.0, total_ru - attributed_total_ru)`), retention warning inference (`min_time > window_start + max(1h, 0.05 * window_duration)`), empty workspace handling (`results: []`), and Silent-Zero Guard raising `TelemetryMisconfigurationError` when `attributed_total_ru == 0` while `total_ru > 0`
- [x] T013 [P] [US1] Author CLI unit tests in tests/unit/test_discover_cli.py verifying command arguments (--workspace-id/-w, --account/-a, --time-window/-t, --top/-n, --timeout), `--print-kql` offline execution (exit 0), standard discovery run (exit 0), empty results (exit 0), invalid inputs (exit 1), Silent-Zero Guard abort (exit 1 directing to `--check`), connection failure (exit 3), and auth/RBAC failure (exit 5)
- [x] T014 [P] [US1] Author offline credential isolation test in tests/unit/test_discover_cli.py verifying that with DefaultAzureCredential patched to raise if instantiated, querylens discover --workspace-id <uuid> --print-kql still exits 0 and prints both queries without acquiring credentials or making network calls

### Implementation for User Story 1

- [x] T015 [US1] Implement baseline KQL builders build_shapes_query (returning shapes without caller ranking) and build_totals_query in src/querylens/discovery/kql.py incorporating column mapping expressions, `materialize()` CTE caching, single-row pre-aggregation by `activityId_g`, and account filter `endswith` clause
- [x] T016 [US1] Implement discovery execution service run_discovery in src/querylens/discovery/service.py accepting injected LogsQueryClient, executing Query 1 and Query 2, mapping rows to DiscoveredQueryShape (without callers) and WorkloadDiscoverySummary, calculating unattributed RU and retention warning, and enforcing the Silent-Zero Guard invariant ("If `attributed_total_ru == 0` while `total_ru > 0`, or if essential diagnostic columns (`requestCharge_s`, `activityId_g`, `querytext_s`) are absent/unpopulated in the logs, the model/service raises `TelemetryMisconfigurationError`, aborting execution with CLI exit code 1 and advising the user to run `querylens discover --check`")
- [x] T017 [US1] Implement Rich console report formatter for baseline discovery results in src/querylens/report/discover_console.py rendering summary header panel (masked workspace ID, window, total RU, unattributed RU and %) and ranked table sorted descending by total RU (database, container, shape_id, executions, total RU, avg RU, max RU, RU %, avg returned rows from `numberofrowsreturned_s`, RU / row, 429 throttle count, sample query text)
- [x] T018 [US1] Implement discovery JSON serialization in src/querylens/report/discover_json.py conforming to specs/002-query-cost-discovery/contracts/discover-output-schema.json without requiring top_callers
- [x] T019 [US1] Implement CLI command discover in src/querylens/discover_cli.py with Click options (--workspace-id/-w, --account/-a, --time-window/-t, --top/-n, --timeout, --print-kql, --json), parameter validation, exit code mapping (0, 1, 3, 5), and wiring of `--print-kql`
- [x] T020 [US1] Register discover command on main Click group cli in src/querylens/cli.py
- [x] T021 [US1] Execute blocking manual qualification gate per docs/manual-testing.md: paste both --print-kql queries into the Azure portal Logs editor, run querylens discover --workspace-id <uuid> against a real workspace (non-prod access, counts only), and fix any KQL errors BEFORE starting US2/US3 (Completed: live gate passed on real workspace at commit `82c992a`)

**Checkpoint**: At this point, User Story 1 (MVP) is fully functional and validated live on Azure before starting subsequent stories.

---

## Phase 4: User Story 2 - Preflight Workspace Diagnostic Inspection (`--check`) (Priority: P2)

**Goal**: Inspect target Log Analytics workspace to verify Cosmos DB diagnostic telemetry readiness, reporting category row counts, time boundaries, column population percentages, and auth token distributions with 0% sensitive data, validated live against real workspace before proceeding.

**Independent Test**: Run `querylens discover --workspace-id <uuid> --check`. Verify that preflight KQL executes, reports category presence, masks the workspace ID to its last 4 characters, computes field coverage ratios, warns if `QueryRuntimeStatistics` is missing, and produces JSON conforming to `check-output-schema.json`.

### Tests for User Story 2 🧪

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T022 [P] [US2] Author preflight check JSON contract tests in tests/unit/test_discover_contract.py validating synthetic check output against specs/002-query-cost-discovery/contracts/check-output-schema.json
- [x] T023 [P] [US2] Author preflight service unit tests in tests/unit/test_discover_service.py using synthetic logs fixtures to verify category detection, row counting, field coverage percentage calculations, auth token distribution grouping, retention warning detection, and missing `QueryRuntimeStatistics` category warning
- [x] T024 [P] [US2] Author preflight CLI tests in tests/unit/test_discover_cli.py verifying querylens discover --workspace-id <uuid> --check console rendering and querylens discover --workspace-id <uuid> --check --json machine-readable output

### Implementation for User Story 2

- [x] T025 [US2] Implement preflight check KQL query builder build_preflight_check_query in src/querylens/discovery/kql.py querying `AzureDiagnostics` category counts, min/max `TimeGenerated`, non-empty counts for columns (`shapesignature_s`, `querytext_s`, `aadPrincipalId_g`, `aadPrincipalId_s`, `clientIpAddress_s`, `useragent_s`), and breakdown of `authTokenType_s`
- [x] T026 [US2] Implement run_preflight_check in src/querylens/discovery/service.py accepting injected LogsQueryClient, parsing raw diagnostic results into PreflightCheckReport, masking workspace ID to last 4 characters, computing column coverage ratios, and flagging retention and missing category warnings
- [x] T027 [US2] Implement preflight check Rich console renderer in src/querylens/report/discover_console.py formatting category record counts, time boundaries, field coverage percentages, and authentication token breakdown
- [x] T028 [US2] Wire `--check` mode into src/querylens/discover_cli.py supporting both Rich console report and `--json` serialization matching specs/002-query-cost-discovery/contracts/check-output-schema.json
- [x] T029 [US2] Execute manual preflight qualification gate per docs/manual-testing.md: run querylens discover --workspace-id <uuid> --check against a real workspace (counts and percentages only) and fix any preflight KQL errors before starting US3 (Completed: live gate passed on real workspace at commit `82c992a`)

**Checkpoint**: At this point, User Stories 1 AND 2 are both verified offline and qualified on live Azure before caller attribution work begins.

---

## Phase 5: User Story 3 - Caller Attribution & Sensitive Query Text Privacy (Priority: P3)

**Goal**: Extend Top Shapes query with server-side per-shape top 3 caller ranking and dynamic packing, update golden KQL snapshots, parse callers into domain models, enforce default query text omission from `--json` and truncation in console tables, and support opt-in `--show-text`.

**Independent Test**: Run `querylens discover --workspace-id <uuid>` on logs containing principal GUIDs and client IPs. Verify that up to 3 callers per shape are extracted with individual RU share percentages, that default `--json` output contains NO `sample_query_text` keys, that console tables truncate sample text to 200 characters by default, and that `--show-text` preserves full text in both console and JSON outputs.

### Tests for User Story 3 🧪

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T030 [P] [US3] Author query text privacy contract test test_discover_json_omits_query_text_by_default and caller attribution contract test in tests/unit/test_discover_contract.py asserting that default `--json` output omits sample_query_text, that `--show-text --json` includes sample_query_text, and that top_callers is populated according to specs/002-query-cost-discovery/contracts/discover-output-schema.json
- [x] T031 [P] [US3] Author caller attribution KQL builder tests in tests/unit/test_discover_kql.py and update golden snapshots in tests/unit/test_discover_kql_snapshots.py for the extended Top Shapes query including `top_callers_per_shape` join and `make_list(bag_pack(...), 3)`
- [x] T032 [P] [US3] Author caller attribution parsing unit tests in tests/unit/test_discover_service.py testing dynamic bag unpacking for `top_callers`, Entra ID principal GUID preference (`aadPrincipalId_g`), client IP fallback (`clientIpAddress_s`), blank caller omission, max 3 callers per shape, and individual caller RU share calculations
- [x] T033 [P] [US3] Author query text privacy CLI unit tests in tests/unit/test_discover_cli.py verifying console table truncates `sample_query_text` to 200 characters unless `--show-text` is passed, and asserting query text is never logged to internal structlog loggers

### Implementation for User Story 3

- [x] T034 [US3] Extend build_shapes_query in src/querylens/discovery/kql.py with `top_callers_per_shape` join, per-shape caller ranking (`caller_ru desc`), and dynamic array construction `make_list(bag_pack(...), 3)`
- [x] T035 [US3] Implement dynamic caller bag parsing in src/querylens/discovery/service.py parsing KQL `top_callers` list of bags (`identifier`, `caller_ru`, `identifier_type`) into `list[CallerAttribution]`, computing caller RU share relative to shape total RU, and enforcing maximum of 3 callers per shape
- [x] T036 [US3] Implement query text truncation and caller rendering in src/querylens/report/discover_console.py (formatting top 3 callers with RU shares, and truncating `sample_query_text` to 200 characters unless `show_text=True`) and query text omission in src/querylens/report/discover_json.py (omitting `sample_query_text` from output dictionary unless `show_text=True`, and serializing `top_callers`)
- [x] T037 [US3] Wire `--show-text` flag into src/querylens/discover_cli.py propagating option through DiscoveryOptions to console and JSON formatters

**Checkpoint**: All three user stories are now complete, with caller attribution and privacy invariants enforced. Pending: live gate for US3 (callers) and the materialize(ql_resolved_activities) change will run at the final commit.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Snapshot regression verification, release documentation, code hygiene, and test coverage enforcement.

- [x] T038 [P] Implement end-to-end output format snapshot tests in tests/integration/test_discover_snapshots.py using syrupy for discovery console table, discovery JSON, check console report, and check JSON
- [x] T039 [P] Update release qualification procedure in docs/manual-testing.md with step-by-step verification commands for both KQL queries against Azure portal Logs editor
- [x] T040 [P] Update README.md (new 'Discover query costs from logs' section covering --check, --print-kql, --show-text, required role Log Analytics Reader, and the obfuscation caveat) and CONTRIBUTING.md in README.md and CONTRIBUTING.md
- [x] T041 Verify test coverage threshold >= 85% across all discovery and report modules using uv run pytest --cov=querylens --cov-fail-under=85
- [x] T042 [P] Run static analysis and linting checks using uv run ruff check src tests, uv run ruff format --check src tests, and uv run pyrefly check
- [x] T043 Run full pre-commit pipeline across all repository files using uv run pre-commit run --all-files
- [ ] T044 Run docs/live-gate.md at the final commit (callers, materialize change) and record the tested commit SHA.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately.
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) - BLOCKS all user stories.
- **User Stories (Phases 3–5)**:
  - User Story 1 (Phase 3) depends on Foundational (Phase 2).
  - User Story 2 (Phase 4) follows User Story 1; both are validated at the manual qualification gates (`T021`, `T029`) before US3.
  - User Story 3 (Phase 5) depends on US1 baseline and US2 preflight completion.
- **Polish (Phase 6)**: Depends on all user stories (US1, US2, US3) being complete.

### User Story Dependencies & Manual Gates

- **User Story 1 (P1 - MVP)**: Can start after Phase 2. Delivers core discovery, baseline two-query KQL engine (without callers), Silent-Zero Guard, `--print-kql`, Rich table, and default JSON output.
  - **Blocking Manual Gate `T021`**: Paste `--print-kql` queries into Azure portal Logs editor and run `querylens discover` against a real workspace before proceeding.
- **User Story 2 (P2 - Preflight Check)**: Follows US1. Adds `--check` preflight telemetry verification.
  - **Manual Gate `T029`**: Run `querylens discover --workspace-id <uuid> --check` against real workspace to confirm diagnostic metadata extraction before starting US3.
- **User Story 3 (P3 - Caller Attribution & Privacy)**: Extends `build_shapes_query` with `top_callers_per_shape` server-side ranking, parses dynamic caller bags, and enforces query text privacy (`--show-text`).

### Within Each User Story

- Tests MUST be written FIRST and fail before implementation begins (Constitution Principle III).
- Models and schemas before service logic.
- Service logic before formatters and CLI wiring.
- Story complete and independently testable before proceeding to the next priority.

### Parallel Opportunities

- **Phase 1**: T003 and T004 can run in parallel after T001 and T002.
- **Phase 2**: T005 can run in parallel with T006; T007 follows T006 in `models.py`.
- **Phase 3 (US1)**: Test tasks T009, T010, T011, T012, T013, and T014 can all be written in parallel before implementation tasks T015–T020.
- **Phase 4 (US2)**: Test tasks T022, T023, and T024 can be written in parallel before implementation tasks T025–T028.
- **Phase 5 (US3)**: Test tasks T030, T031, T032, and T033 can be written in parallel before implementation tasks T034–T037.
- **Phase 6**: Snapshot test T038, documentation T039, README/CONTRIBUTING T040, and linting T042 can be executed in parallel before final gates T041, T043, and live gate T044.

---

## Parallel Execution Examples

### Parallel Tests for User Story 1 (P1)

```bash
# Launch test authoring for User Story 1 together:
Task: "Author KQL query builder unit tests in tests/unit/test_discover_kql.py"
Task: "Author golden snapshot tests for --print-kql output in tests/unit/test_discover_kql_snapshots.py"
Task: "Author discovery JSON contract tests in tests/unit/test_discover_contract.py"
Task: "Author discovery service unit tests in tests/unit/test_discover_service.py"
Task: "Author CLI unit tests in tests/unit/test_discover_cli.py"
Task: "Author offline credential isolation test in tests/unit/test_discover_cli.py"
```

### Parallel Tests for User Story 2 (P2)

```bash
# Launch test authoring for User Story 2 together:
Task: "Author preflight check JSON contract tests in tests/unit/test_discover_contract.py"
Task: "Author preflight service unit tests in tests/unit/test_discover_service.py"
Task: "Author preflight CLI tests in tests/unit/test_discover_cli.py"
```

### Parallel Tests for User Story 3 (P3)

```bash
# Launch test authoring for User Story 3 together:
Task: "Author query text privacy contract test in tests/unit/test_discover_contract.py"
Task: "Author caller attribution KQL builder tests in tests/unit/test_discover_kql.py"
Task: "Author caller attribution parsing unit tests in tests/unit/test_discover_service.py"
Task: "Author query text privacy CLI unit tests in tests/unit/test_discover_cli.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete **Phase 1: Setup** (pinning dependency, package layout, test fixtures, column mapping).
2. Complete **Phase 2: Foundational** (escaping, validation options, Pydantic models).
3. Complete **Phase 3: User Story 1** (TDD tests → baseline KQL queries without callers → service → formatters → CLI).
4. **STOP and EXECUTE MANUAL GATE (`T021`)**:
   - Run `uv run querylens discover --workspace-id <uuid> --print-kql` and verify offline output.
   - Paste both queries into Azure Portal Logs editor.
   - Run `uv run querylens discover --workspace-id <uuid>` against non-prod workspace and fix any KQL errors.

### Incremental Delivery

1. **Foundations**: Setup + Foundational complete → Foundation ready.
2. **Increment 1 (MVP)**: Add User Story 1 → Test independently → CLI `querylens discover` functional with `--print-kql` and Rich/JSON output → Validate on Azure portal gate.
3. **Increment 2**: Add User Story 2 → Test independently → CLI `querylens discover --check` available for preflight workspace validation → Validate on Azure preflight gate.
4. **Increment 3**: Add User Story 3 → Test independently → Extend `build_shapes_query` with caller ranking, update golden snapshots, parse callers, and activate `--show-text` privacy gates.
5. **Increment 4**: Polish → Snapshot tests, README and CONTRIBUTING updates, 85% coverage gate, pre-commit clean, and final live workspace qualification gate (T044).
