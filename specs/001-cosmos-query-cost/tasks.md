# Tasks: Cosmos DB Query Cost Analyzer

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependency tooling, and code hygiene configurations.

- [x] T001 Initialize Python 3.12 project structure in `pyproject.toml` with `uv` lockfile declaring dependencies: `click`, `rich`, `pydantic` (v2), `pydantic-settings`, `azure-cosmos`, `azure-identity`, `tenacity`, `structlog`, `pyyaml`, `pytest`, `pytest-cov`, `hypothesis`, and `syrupy`.
- [x] T002 [P] Configure `ruff` (enabling `D`, `DOC`, and `S` rulesets) and `pyrefly` in strict mode in `pyproject.toml`.
- [x] T003 [P] Configure pre-commit hooks in `.pre-commit-config.yaml` running `ruff check`, `ruff format`, and `pyrefly check`.
- [x] T004 [P] Create Docker Compose service for the Azure Cosmos DB Linux emulator (`mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:latest`) in `docker-compose.yml`.
- [x] T005 [P] Create package skeleton and namespace modules in `src/querylens/__init__.py`, `src/querylens/adapters/__init__.py`, `src/querylens/rules/__init__.py`, and `src/querylens/report/__init__.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data models, protocol contracts, and configuration that MUST be complete before user stories can execute.

- [x] T006 Implement domain models and enums in `src/querylens/model.py`:
  - `Severity` enum: `INFO`, `MEDIUM`, `HIGH`, `CRITICAL` with ordering `level` comparison (`INFO < MEDIUM < HIGH < CRITICAL`).
  - `QueryParameter`: `name: str` (matching `@.+`), `value: Any`.
  - `QueryDefinition`: `id: str`, `query: str`, `parameters: list[QueryParameter]`, `partition_key: str | int | float | bool | list[str | int | float | bool] | None`. Include Pydantic field validator enforcing list length between 1 and 3 (`1 <= len <= 3`), rejecting empty lists (`[]`), nested lists, and null (`None`) values.
  - `Workload`: `version: str = "1"`, `database: str | None`, `container: str | None`, `ru_budget: float | None`, `queries: list[QueryDefinition]`.
  - `IndexUtilization`: `utilized_single`, `potential_single`, `utilized_composite`, `potential_composite`.
  - `QueryCost`: `query_id: str`, `query_text: str`, `request_charge: float`, `latency_ms: float`, `documents_scanned: int`, `documents_returned: int`, `is_cross_partition: bool`, `is_partial: bool = False`, `index_metrics: IndexUtilization | None`, `error_message: str | None`.
  - `Finding`: `rule_id: str`, `rule_name: str`, `severity: Severity`, `summary: str`, `evidence: dict[str, Any]`.
  - `QueryResultSummary`: `cost: QueryCost`, `findings: list[Finding]`.
  - `WorkloadRunSummary`: `timestamp: str`, `database: str`, `container: str`, `total_queries: int`, `completed_queries: int`, `total_ru_consumed: float`, `ru_budget: float | None`, `budget_exceeded: bool`, `results: list[QueryResultSummary]`.
- [x] T007 [P] Implement configuration settings in `src/querylens/config.py` using `pydantic-settings` (`Settings` with `QUERYLENS_` prefix) covering `endpoint`, `database`, `container`, `cosmos_key`, `ru_budget`, `max_item_count`, `debug`, `fail_on`, and rule thresholds (`high_ru_warning`, `high_ru_critical`, `scan_gap_ratio_warning`, `scan_gap_ratio_critical`, `scan_gap_absolute_threshold`).
- [x] T008 [P] Implement `DatabaseAdapter` `typing.Protocol` in `src/querylens/adapters/protocol.py` defining the contract `collect(workload: Workload) -> Iterator[QueryCost]`.
- [x] T009 [P] Implement structured logging configuration in `src/querylens/logging.py` using `structlog` ensuring query result payload dictionaries are never logged or persisted.
- [x] T010 Unit tests for workload parsing and model validation in `tests/unit/test_models.py`, testing valid scalars, valid 1-3 item partition key lists, and asserting rejections of empty lists, nested lists, and nulls with exit code 1.

**Checkpoint**: Foundation complete. Core models and contracts are ready for user story execution.

---

## Phase 3: User Story 1 - Profile and Rank Query Workload by Cost (Priority: P1) [MVP]

**Goal**: Execute a YAML workload of read-only queries against Cosmos DB, record RU charge and latency, and output a terminal table ranked by RU cost or machine-readable JSON via `--json`.

**Independent Test**: Provide a sample YAML workload file with 3 queries against the emulator; run CLI; verify output table ranked descending by RU cost and `--json` output matches `contracts/run-output-schema.json` without retaining document payloads.

### Tests for User Story 1 (Test-First)
- [x] T011 [P] [US1] Create sample workload files and mock Cosmos DB response headers in `tests/fixtures/workloads/sample_workload.yaml` and `tests/fixtures/headers/query_metrics.txt`.
- [x] T012 [P] [US1] Write unit tests for Cosmos DB response header metric parsing in `tests/unit/test_cosmos_parsing.py` testing extraction of `x-ms-request-charge`, `x-ms-documentdb-query-metrics` (`retrievedDocumentCount`, `outputDocumentCount`), and Base64-decoded `x-ms-cosmos-index-utilization`.
- [x] T013 [P] [US1] Write test-first CLI exit code contract tests in `tests/unit/test_cli_exit_codes.py` verifying exit code `0` (success), exit code `1` (workload validation/format error), exit code `3` (connection error/unreachable host/missing container), and exit code `5` (auth error: invalid credentials, missing Data Reader role, HTTP 401/403).

### Implementation for User Story 1
- [x] T014 [US1] Implement `CosmosAdapter` in `src/querylens/adapters/cosmos.py`:
  - Implement `collect(workload: Workload) -> Iterator[QueryCost]`.
  - Connect via `CosmosClient` with `DefaultAzureCredential` for remote endpoints; accept `COSMOS_EMULATOR_KEY` only when endpoint resolves to `localhost` or `127.0.0.1`.
  - Execute queries using `container.query_items(query, parameters, partition_key, enable_cross_partition_query=True, populate_query_metrics=True, populate_index_metrics=True, max_item_count=settings.max_item_count, response_hook=...)`.
  - Discard item payloads immediately during iteration (`for _ in page: pass`).
  - Map response headers to `QueryCost` model.
  - Distinguish connection failures (exit code `3`) from authentication/authorization failures (HTTP 401, 403, credential errors) raising distinct typed exceptions.
- [x] T015 [P] [US1] Implement Rich terminal table and summary rendering in `src/querylens/report/console.py` sorting queries in descending order by `request_charge` and formatting latency, scanned, returned, and partition scope.
- [x] T016 [P] [US1] Implement machine-readable JSON serialization in `src/querylens/report/json_out.py` strictly conforming to `specs/001-cosmos-query-cost/contracts/run-output-schema.json`.
- [x] T017 [US1] Implement Click CLI commands in `src/querylens/cli.py` (`querylens run <workload_file>`) wiring options (`-e`, `-d`, `-c`, `--json`, `--debug`, `--max-item-count`), suppressing raw stack traces unless `--debug`, and enforcing exit codes `0`, `1`, `3`, and `5`.

**Checkpoint**: User Story 1 (MVP) is fully functional and independently verifiable.

---

## Phase 4: User Story 2 - Inefficiency & Problem Diagnosis with Metric Evidence (Priority: P2)

**Goal**: Evaluate diagnostic rules against `QueryCost` metrics to flag high RU cost, cross-partition fan-out, and scan-to-return gaps with evidence and severity; support `--fail-on <severity>` exiting with code 4.

**Independent Test**: Run queries exhibiting anti-patterns; verify diagnostic findings and metric evidence in console table and JSON; verify `--fail-on <severity>` returns exit code 4 when findings meet/exceed severity.

### Tests for User Story 2 (Test-First)
- [x] T018 [P] [US2] Write unit tests for rule functions in `tests/unit/test_rules.py` verifying detection logic and metric evidence for `high_ru_cost`, `cross_partition_fanout`, and `scan_to_return_gap` (verify tests fail before rule implementation).
- [x] T019 [P] [US2] Write property-based tests using `hypothesis` in `tests/unit/test_rules_property.py` verifying rule invariants across arbitrary generated `QueryCost` values (no crashes, severity monotonicity, valid evidence keys).
- [x] T020 [P] [US2] Write test-first unit tests for `--fail-on <severity>` in `tests/unit/test_cli_fail_on.py` verifying exit code `4` when findings are at or above specified severity (`critical`, `high`, `medium`), and exit code `0` when below or when `--fail-on` is off.

### Implementation for User Story 2
- [x] T021 [P] [US2] Implement `rule_high_ru_cost` in `src/querylens/rules/high_ru.py` flagging `HIGH` severity above `high_ru_warning` and `CRITICAL` severity above `high_ru_critical`.
- [x] T022 [P] [US2] Implement `rule_cross_partition_fanout` in `src/querylens/rules/fanout.py` flagging `MEDIUM` severity when `is_cross_partition` is `True`.
- [x] T023 [P] [US2] Implement `rule_scan_to_return_gap` in `src/querylens/rules/scan_gap.py` flagging `HIGH` severity above `scan_gap_ratio_warning` (default 10x), `CRITICAL` severity above `scan_gap_ratio_critical` (default 100x), and `CRITICAL` severity for zero returned with `>= 1000` scanned.
- [x] T024 [US2] Implement rule registry and evaluation runner in `src/querylens/rules/registry.py` with signature `evaluate_rules(cost: QueryCost, settings: Settings) -> list[Finding]`.
- [x] T025 [US2] Integrate diagnostic findings into Rich table rendering in `src/querylens/report/console.py` displaying color-coded findings tags (`[CRIT]`, `[HIGH]`, `[MED]`) and metric evidence panels.
- [x] T026 [US2] Wire rule evaluation into `src/querylens/cli.py` and enforce `--fail-on <severity>` exit code `4` gating when findings reach or exceed the threshold.

**Checkpoint**: User Stories 1 and 2 operate together.

---

## Phase 5: User Story 3 - Safe Execution with Configurable RU Budget Guards (Priority: P3)

**Goal**: Enforce a cumulative RU budget checked per paginated response; abort mid-query if breached, mark query with `is_partial=True`, output partial results with alert, and exit with code 2.

**Independent Test**: Configure `--ru-budget 15.0` on a workload consuming 30 RUs; verify execution halts mid-query, reports partial results, and exits with code 2.

### Tests for User Story 3 (Test-First)
- [ ] T027 [P] [US3] Write unit tests for per-page RU budget tracking and mid-query abort in `tests/unit/test_budget_guard.py` verifying that execution halts on the exact page exceeding budget, sets `is_partial=True`, and triggers exit code `2`.

### Implementation for User Story 3
- [ ] T028 [US3] Implement per-page cumulative RU accumulation in `src/querylens/adapters/cosmos.py`: track running cumulative RU total across pages, immediately break pagination loop when budget is exceeded, mark the active `QueryCost` with `is_partial=True`, and raise or yield `BudgetExceeded`.
- [ ] T029 [US3] Handle budget overrun in `src/querylens/cli.py`: catch budget exhaustion, render partial results table/JSON with a prominent warning panel, and exit with exit code `2`.

**Checkpoint**: All three user stories are complete and independently testable.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration testing with local emulator, CI/CD pipeline automation, and end-to-end documentation validation.

- [ ] T030 [P] Implement integration test suite in `tests/integration/test_cosmos_adapter.py` executing against the Dockerized Cosmos DB emulator (creating test container, seeding sample documents, verifying read-only execution, metric extraction, and header decoding).
- [ ] T031 [P] Implement CLI snapshot tests using `syrupy` in `tests/integration/test_cli_snapshots.py` asserting stability of Rich terminal output and `--json` schemas.
- [ ] T032 [P] Create GitHub Actions workflow in `.github/workflows/ci.yml` running `ruff check`, `ruff format --check`, `pyrefly check`, `pytest --cov=src/querylens --cov-fail-under=85`, `pip-audit`, CodeQL, and `gitleaks`, plus a separate emulator integration test job.
- [ ] T033 [P] Configure Dependabot in `.github/dependabot.yml` with GitHub Actions pinned to commit SHAs.
- [ ] T034 Execute end-to-end validation scenarios from `specs/001-cosmos-query-cost/quickstart.md` against the running emulator and verify all exit codes (`0`, `1`, `2`, `3`, `4`, `5`).

---

## Dependencies & Execution Order

### Phase Dependencies
```
Phase 1: Setup ──► Phase 2: Foundational ──► Phase 3: User Story 1 (MVP)
                                                    │
                                                    ▼
                                            Phase 4: User Story 2
                                                    │
                                                    ▼
                                            Phase 5: User Story 3
                                                    │
                                                    ▼
                                            Phase 6: Polish & CI
```

- **Phase 1 (Setup)**: Can start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1; BLOCKS all User Stories.
- **Phase 3 (User Story 1)**: Depends on Phase 2; produces the core viable MVP CLI.
- **Phase 4 (User Story 2)**: Depends on Phase 3; adds diagnostic rules and `--fail-on`.
- **Phase 5 (User Story 3)**: Depends on Phase 3 & 4; adds per-page RU budget safety guards.
- **Phase 6 (Polish)**: Depends on all user story phases.

### Parallel Opportunities Within Phases
- **Phase 1**: `T002`, `T003`, `T004`, `T005` can run in parallel after `T001`.
- **Phase 2**: `T007`, `T008`, `T009` can run in parallel after `T006`.
- **Phase 3 (US1)**: `T011`, `T012`, `T013` (tests) can run in parallel; `T015`, `T016` can run in parallel.
- **Phase 4 (US2)**: `T018`, `T019`, `T020` (tests) can run in parallel; `T021`, `T022`, `T023` (rules) can run in parallel.
- **Phase 6**: `T030`, `T031`, `T032`, `T033` can run in parallel.

---

## Implementation Strategy & Incremental Delivery

1. **MVP Increment (Phases 1, 2, 3)**:
   - Sets up repository, models, protocol, and the Cosmos adapter.
   - Delivers runnable `querylens run <workload>` outputting ranked RU costs and `--json`.
   - Verifies exit codes `0`, `1`, `3`, `5`.
2. **Diagnostic Increment (Phase 4)**:
   - Delivers TDD rule suite and property tests with `hypothesis`.
   - Adds `--fail-on <severity>` (exit code `4`).
3. **Safety Guard Increment (Phase 5)**:
   - Delivers per-page RU budget abort guard (exit code `2`).
4. **Hardening & Verification (Phase 6)**:
   - Dockerized Cosmos emulator integration tests, CI pipelines, and 85% coverage enforcement.
