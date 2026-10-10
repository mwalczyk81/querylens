# Implementation Plan: Cosmos DB Query Cost Discovery

**Branch**: `002-query-cost-discovery` | **Date**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from [spec.md](spec.md)

---

## Summary

Enable developers and platform teams to automatically identify high-cost query shapes from existing Azure Cosmos DB for NoSQL diagnostic telemetry logged to an Azure Log Analytics workspace via a new CLI command: `querylens discover`.

The feature queries the legacy `AzureDiagnostics` table using the official `azure-monitor-query` SDK and Microsoft Entra ID credentials (`DefaultAzureCredential`). Because Log Analytics returns only the final tabular output of a script, the engine executes **two targeted KQL queries**:

1. **Top Shapes Query**: Summarizes both sides by `activityId_g` alone before joining, wraps `joined` and `top_shapes` in `materialize()` to guarantee join stability and tie-breaking consistency, and extracts top 3 callers per shape. Returns at most $N$ rows (where $N$ is `--top`, 1–100).
2. **Totals Query**: Calculates overall `window_total_ru`, `attributed_total_ru` (summed across ALL joined shapes in the window), `total_executions`, and `min(TimeGenerated)` from `DataPlaneRequests`. Returns exactly 1 row.

The client receives at most $N$ shape rows plus 1 totals row (zero unaggregated rows transferred). The command makes zero calls to the Cosmos DB data plane, requires zero Cosmos credentials, adheres to strict KQL injection defense, provides preflight telemetry health checks (`--check`), provides offline KQL inspection for both queries (`--print-kql`), enforces a Silent-Zero Guard against telemetry misconfiguration, and outputs both Rich terminal tables and privacy-preserving machine-readable JSON (omitting query text by default unless `--show-text` is passed).

---

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**:

- `azure-monitor-query>=2.0.0` (official Azure Monitor Logs query plane client)
- `azure-identity>=1.15.0` (Microsoft Entra ID token credentials)
- `click>=8.1.7` (CLI command routing and options)
- `rich>=13.7.0` (terminal tables, panels, and formatting)
- `pydantic>=2.6.0` & `pydantic-settings>=2.2.0` (domain models and validation)

**Storage**: Azure Log Analytics workspace (`AzureDiagnostics` table); zero local database or file storage.
**Testing**: `pytest`, `pytest-cov`, `hypothesis` (property-based injection verification), `syrupy` (snapshot verification).
**Target Platform**: Cross-platform (Windows, macOS, Linux) CLI executable via `uv`.
**Project Type**: CLI tool extension.
**Performance Goals**:

- Client receives at most $N$ shape rows plus 1 totals row (default 20, max 100).
- Zero unaggregated raw log records transferred across the network.
- Server-side query timeout enforced (default 180s, max 600s).

**Constraints**:

- Strictly read-only against Azure Monitor; zero calls to Cosmos DB data plane.
- Zero secret storage; Entra ID authentication only (`Log Analytics Reader`).
- Strict KQL injection defense via allowlist validation and string-literal escaping.
- Strict type safety: wrap every `column_ifexists(...)` in `tostring()` before `coalesce()`.
- Deterministic joins: `materialize()` on `joined` and `top_shapes`.
- Case-insensitive account filtering without term-splitting: `_ResourceId endswith "/databaseaccounts/{escaped_account}"`.
- Silent-Zero Guard: abort with exit code 1 if `attributed_total_ru == 0` while `window_total_ru > 0`, or if essential columns are absent.
- Payload privacy (FR-012): query text omitted from `--json` unless `--show-text` is passed.
- Continuous Integration limit: KQL is never executed against live Azure in CI; snapshot tests protect against query text regressions, not semantic correctness.
- Mandatory manual qualification gate: Every release is gated on manual portal verification for both queries via `--print-kql`, `--check`, and live discovery per `docs/manual-testing.md`.
- Minimum 85% test coverage maintained.

**Scale/Scope**: Server-side aggregation over millions of diagnostic records; client processing lightweight Pydantic summaries.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Status | Evidence / Notes |
| --- | --- | --- | --- |
| **I. Read-Only Safety & Privacy-First Security** | Strictly read-only; zero secrets; payload privacy; input validation. | **PASS** | Only queries Azure Monitor query plane; makes 0 Cosmos data plane calls; uses `DefaultAzureCredential`; literals redacted by Cosmos; CLI inputs validated via Pydantic/regex; query text omitted from JSON by default (FR-012). |
| **II. Minimal Abstraction Architecture** | Protocol-based adapters only where justified; no bespoke layers without ADR. | **PASS** | Implemented as plain functions in `querylens.discovery` with injected `LogsQueryClient`. No new Protocol, base classes, or factories. Existing `DatabaseAdapter` seam stays untouched. |
| **III. Test-First Rule Development & Property Verification** | TDD workflow; Hypothesis property tests; CI coverage >= 85%; emulator/offline tests. | **PASS** | Synthetic test fixtures using `LogsTable`/`LogsTableRow`; Hypothesis property tests for KQL escaping; 0 live cloud dependencies in unit suite; >= 85% coverage gate enforced. |
| **IV. CLI-First Contract & Deterministic Diagnostics** | Dual output (Rich + `--json`); deterministic exit codes (0, 1, 3, 5); clean diagnostics. | **PASS** | Full Rich table + `--json` conforming to JSON schemas; exit codes 0 (success / empty / print-kql), 1 (validation / query error / silent-zero guard), 3 (workspace/network error), 5 (auth/RBAC error) per [ADR 0004](file:///docs/adr/0004-cli-first-design-and-deterministic-exit-codes.md). |
| **V. Dependency Discipline** | Reuse over reinvention; documented justification; managed via `uv`. | **PASS** | Uses official `azure-monitor-query==2.0.0` declared in `pyproject.toml` and locked with `uv.lock`. |

*All constitutional gates PASSED without violations.*

---

## Project Structure

### Documentation (this feature)

```text
specs/002-query-cost-discovery/
├── spec.md              # Feature specification
├── checklists/
│   └── requirements.md  # Requirements quality checklist
├── plan.md              # This implementation plan
├── research.md          # Research findings & architectural decisions
├── data-model.md        # Data entities, Pydantic models, and flow
├── quickstart.md        # Verification guide and execution commands
├── contracts/
│   ├── discover-output-schema.json  # Schema for querylens discover JSON
│   └── check-output-schema.json     # Schema for querylens discover --check JSON
└── tasks.md             # Tasks definition (to be generated by /speckit-tasks)
```

### Architecture Decision Records & Manual Testing Guide

```text
docs/
├── manual-testing.md                                # Release qualification checklist & procedure for both queries
└── adr/
    ├── 0006-azure-monitor-logs-query-contracts.md       # SDK signatures, types, two-query architecture, release gate
    └── 0007-kql-injection-defense-and-input-validation.md # Allowlist regex, escaping, timespan routing
```

### Source Code & Test Layout

```text
src/querylens/
├── cli.py                     # Main Click group (imports & registers discover command)
├── discover_cli.py            # 'querylens discover' command implementation & options (--print-kql, --check)
├── discovery/
│   ├── __init__.py            # Discovery package exports
│   ├── columns.py             # Type-safe KQL column mappings with tostring(column_ifexists(...))
│   ├── kql.py                 # KQL query construction (Shapes Query + Totals Query) & escape_kql_string
│   ├── models.py              # Pydantic schemas (DiscoveredQueryShape, Summary, Check)
│   └── service.py             # Discovery execution, silent-zero guard, preflight check (injected client)
└── report/
    ├── discover_console.py    # Rich console rendering for discovery table & preflight check
    └── discover_json.py       # JSON serialization for discovery and check reports (FR-012 query text omission)

tests/
├── unit/
│   ├── test_discover_kql.py             # KQL query building, escaping, column resilience
│   ├── test_discover_kql_snapshots.py   # Golden snapshot tests for both queries in --print-kql output
│   ├── test_discover_contract.py        # Contract tests asserting default JSON omits query text & schema conformance
│   ├── test_discover_models.py          # Pydantic validation, bounds, and nullability
│   ├── test_discover_service.py         # Service logic with synthetic LogsTable fixtures & silent-zero guard
│   ├── test_discover_cli.py             # CLI options, exit codes (0, 1, 3, 5), flags (--print-kql, --check)
│   └── test_discover_injection_property.py # Hypothesis property tests for KQL injection
└── integration/
    └── test_discover_snapshots.py       # Output format snapshots (Rich table & JSON)
```

---

## Complexity Tracking

*No constitutional violations. No additional complexity justification required.*
