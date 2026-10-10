# Implementation Plan: Cosmos DB Query Cost Analyzer

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-cosmos-query-cost/spec.md`

---

## Summary

Build `querylens`, an open-source Python 3.12+ CLI tool that profiles workloads of Cosmos DB for NoSQL queries, captures detailed cost metrics (Request Units / RUs, latency, documents scanned vs returned, partition fan-out, and index metrics), ranks queries by RU charge, diagnoses root-cause inefficiencies with quantitative metric evidence, and enforces strict operational safety (read-only execution, payload discard, and cumulative RU budget aborts).

The system follows a strict `src/` layout with a minimal [`DatabaseAdapter`](file:///C:/Users/mwalc/source/repos/querylens/specs/001-cosmos-query-cost/plan.md#L97) `typing.Protocol`, plain-function rule registry, Click CLI with Rich terminal output and `--json` support, and Dockerized emulator testing.

---

## Technical Context

**Language/Version**: Python 3.12+ (modern type syntax, pattern matching, union operators).

**Primary Dependencies & Justifications**:

* `click`: Standard declarative CLI framework for command routing, argument validation, and exit code management.
* `rich`: Terminal rendering for colorful, structured query ranking tables, summary cards, and diagnostic alerts.
* `pydantic` (v2): High-performance schema validation, type parsing, and data modeling for workloads and execution metrics.
* `pydantic-settings`: Type-safe configuration management loading environment variables and CLI overrides for thresholds.
* `azure-cosmos`: Official Microsoft Azure Cosmos DB for NoSQL data-plane SDK providing `query_items`, pagination, and metrics.
* `azure-identity`: Entra ID authentication using `DefaultAzureCredential` for secure, keyless database access.
* `tenacity`: Declarative retry utility with exponential backoff and jitter for handling transient HTTP 429 throttling.
* `structlog`: Structured JSON logging framework that isolates logs and ensures query result payloads are never recorded.
* `PyYAML`: YAML parser executed strictly with `safe_load` to securely parse workload files.

**Storage**: None (ephemeral runtime analysis; results rendered to terminal/stdout; query payloads never persisted).

**Testing**:

* `pytest`: Primary test execution framework.
* `pytest-cov`: Enforces the mandatory 85% minimum code and branch coverage gate in CI.
* `hypothesis`: Property-based testing generating adversarial inputs to verify rule engine invariants.
* `syrupy`: Snapshot testing validating stability of Rich terminal tables and JSON output structures.

**Target Platform**: Cross-platform (Windows, Linux, macOS) command-line interface.

**Project Type**: CLI application with `src/` layout managed via `uv`.

**Performance Goals**: CLI summary and JSON generation complete within 2 seconds of final query execution.

**Constraints**:

* Read-only by design: zero write/alter operations to target databases.
* Zero-secret footprint: Entra ID RBAC for remote accounts; local emulator master key permitted only for localhost endpoints.
* Zero data payload persistence: query result item dictionaries discarded immediately during iteration.
* RU budget abort: execution immediately stops when cumulative RU spend crosses the configured limit (evaluated per page; partial metrics recorded with is_partial flag).

---

## Constitution Check

*GATE: Checked before Phase 0 research and re-evaluated post-design.*

| Principle / Rule | Compliance Status | Implementation Strategy |
| :--- | :--- | :--- |
| **I. Read-Only Safety** | **PASS** | Adapter uses read-only query calls; Data Reader RBAC role mandated for production accounts. |
| **I. Zero-Secret Footprint** | **PASS** | Remote accounts authenticate via `DefaultAzureCredential()`; emulator key permitted only when endpoint resolves to localhost. |
| **I. Payload Privacy** | **PASS** | Query iterator pages discard items immediately (`for _ in page: pass`); no payloads persisted or logged. |
| **I. Input Validation** | **PASS** | Workload files parsed with `yaml.safe_load` and validated via Pydantic v2 schemas. |
| **II. Minimal Abstraction** | **PASS** | `DatabaseAdapter` `typing.Protocol` with `collect(workload) -> Iterator[QueryCost]`; no extra layers. |
| **II. Target Sequencing** | **PASS** | Cosmos DB for NoSQL is the initial and only adapter implementation. |
| **II. Rule Independence** | **PASS** | Plain functions `(QueryCost, Settings) -> list[Finding]` in a simple registry; no SQL parser; operates strictly on metrics. |
| **III. Test-First (TDD)** | **PASS** | Rule test suites authored prior to rule implementations. |
| **III. Property-Based Testing** | **PASS** | `hypothesis` tests assert invariant safety across generated `QueryCost` values. |
| **III. CI Coverage Gate (≥85%)** | **PASS** | CI configuration enforces `pytest --cov --cov-fail-under=85`. |
| **III. Docker Emulator Testing** | **PASS** | Integration tests execute against `azure-cosmos-emulator` container in Docker Compose. |
| **IV. CLI-First & Diagnostics** | **PASS** | Rich table output, `--json` flag, distinct exit codes (0–5 including separate auth error code 5 and `--fail-on <severity>`), suppressed stack traces unless `--debug`. |
| **V. Dependency Discipline** | **PASS** | Standard packages used with one-line justifications; managed via `uv` with `uv.lock`. |
| **Code Quality & Typing** | **PASS** | Python 3.12+, `ruff` (D, DOC, S rules enabled), Google-style docstrings, `pyrefly` strict type checking. |

---

## Project Structure

### Documentation (this feature)

```text
specs/001-cosmos-query-cost/
├── plan.md              # This implementation plan
├── research.md          # Phase 0: SDK verification, security, rule design
├── data-model.md        # Phase 1: Pydantic v2 schemas and models
├── quickstart.md        # Phase 1: Setup and end-to-end validation guide
├── contracts/           # Phase 1: Schema contracts
│   ├── workload-schema.json
│   ├── run-output-schema.json
│   └── cli-contract.md
└── tasks.md             # Phase 2: Implementation tasks (generated via /speckit-tasks)
```

### Source Code Layout (`src/` layout)

```text
querylens/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                 # Ruff, Pyrefly, Pytest (85% cov), pip-audit, CodeQL, Gitleaks
│   │   └── emulator-tests.yml     # Docker Compose Cosmos emulator integration tests
│   └── dependabot.yml             # Pinned action SHAs & dependency updates
├── docker-compose.yml             # Cosmos DB Linux emulator service definition
├── pyproject.toml                 # uv package configuration, tool settings, ruff, pytest
├── README.md
├── src/
│   └── querylens/
│       ├── __init__.py
│       ├── model.py               # Workload, QueryCost, Finding, Severity, RunSummary
│       ├── config.py              # pydantic-settings: Settings and threshold configs
│       ├── cli.py                 # Click CLI commands: `querylens run`
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── protocol.py        # DatabaseAdapter typing.Protocol
│       │   └── cosmos.py          # Cosmos DB adapter (query_items, metrics headers)
│       ├── rules/
│       │   ├── __init__.py
│       │   ├── registry.py        # Rule registry: (QueryCost, Settings) -> list[Finding]
│       │   ├── high_ru.py         # Rule: High RU cost detection
│       │   ├── fanout.py          # Rule: Cross-partition fan-out detection
│       │   └── scan_gap.py        # Rule: Documents scanned vs returned gap
│       └── report/
│           ├── __init__.py
│           ├── console.py         # Rich terminal table and finding panels
│           └── json_out.py        # Structured JSON serializer
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── workloads/             # Sample workload YAML files
    │   └── headers/               # Captured Cosmos DB response headers for testing
    ├── unit/
    │   ├── test_models.py
    │   ├── test_rules.py          # Rule unit tests + Hypothesis property tests
    │   ├── test_report.py         # Rich and JSON output unit tests
    │   └── test_cli.py            # Click runner tests
    └── integration/
        ├── test_cosmos_adapter.py # Real queries against Dockerized Cosmos emulator
        └── test_end_to_end.py     # Full CLI run against emulator
```

**Structure Decision**: A single-project `src/` layout under `src/querylens` managed by `uv`. This satisfies the Minimal Abstraction Principle by keeping adapter logic, rules, and CLI reporting cleanly separated without unnecessary subpackages or monorepo overhead.

---

## Complexity Tracking

*No violations or unjustified abstractions exist.* All components adhere strictly to the project constitution.
