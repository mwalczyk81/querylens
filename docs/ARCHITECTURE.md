# Architecture & Design

This document outlines the architecture, data flow, extension points, and exit-code semantics of QueryLens.

---

## Component Architecture & Data Flow

QueryLens follows a layered design centered around the `DatabaseAdapter` Protocol seam, decoupling query execution from anti-pattern diagnostics and reporting:

```mermaid
flowchart TD
    YAML["Workload YAML"] --> CLI["Click CLI (querylens run)"]
    CLI --> PROTOCOL["DatabaseAdapter Protocol (Extension Point)"]
    PROTOCOL --> COSMOS["CosmosAdapter (azure-cosmos SDK)"]
    COSMOS --> COST["QueryCost Domain Model"]
    COST --> RULES["Rule Engine (QL001, QL002, QL003)"]
    RULES --> FINDINGS["WorkloadRunSummary"]
    FINDINGS --> CONSOLE["Rich Console Report"]
    FINDINGS --> JSON["Structured JSON Output"]
```

### Protocol Seam as Extension Point

The profiler engine communicates with database engines exclusively through `DatabaseAdapter` (`src/querylens/adapters/protocol.py`), defined as a Python `typing.Protocol`:

```python
class DatabaseAdapter(Protocol):
    def collect(self, workload: Workload) -> Iterator[QueryCost]: ...
```

`CosmosAdapter` implements this protocol for Azure Cosmos DB for NoSQL. Additional database adapters (such as MongoDB vCore, PostgreSQL, or Couchbase) can be plugged in by providing a new adapter conforming to `DatabaseAdapter` without altering the diagnostic rules, budget guards, or reporting layers.

---

## Log Analytics Discovery Architecture (`querylens discover`)

The discovery engine queries Azure Monitor Log Analytics to uncover top query shapes directly from historical diagnostic logs:

```mermaid
flowchart TD
    CLI["Click CLI (querylens discover)"] --> OPTIONS["DiscoveryOptions Validation"]
    OPTIONS --> BUILDER["KQL Query Builder (kql.py)"]
    BUILDER --> KQL["Shapes Query & Totals Query"]
    KQL --> SDK["LogsQueryClient (azure-monitor-query)"]
    SDK --> LA["Azure Monitor Log Analytics (AzureDiagnostics)"]
    LA --> SERVICE["Discovery Service (service.py)"]
    SERVICE --> GUARD{"Silent-Zero Guard"}
    GUARD -- "Zero Attributed RU" --> ERR["Exit 1 (Misconfiguration)"]
    GUARD -- "Valid Attributed RU" --> MODELS["DiscoveredQueryShape & Summary"]
    MODELS --> CONSOLE["Rich Console Table"]
    MODELS --> JSON["Structured JSON Output"]
```

Unlike `querylens run`, `querylens discover` queries Azure Monitor management telemetry using the official `azure-monitor-query` SDK and `DefaultAzureCredential` (requiring `Log Analytics Reader`). It executes server-side KQL aggregation without reading from the Cosmos DB data plane, bypassing the `DatabaseAdapter` protocol seam entirely.

---

## Exit-Code Decision Hierarchy

QueryLens uses an exit-code precedence hierarchy for CI/CD pipelines. Fatal environment and authentication failures abort immediately, while completed runs render their full reports before evaluating exit criteria:

```mermaid
flowchart TD
    START["Execution Start"] --> RUNTIME{"Fatal Runtime Error?"}
    RUNTIME -- "Auth or RBAC Failure" --> EXIT5["Exit 5: Auth Failure"]
    RUNTIME -- "Connection Error" --> EXIT3["Exit 3: Connection Failure"]
    RUNTIME -- "No Runtime Abortion" --> COMPLETE["Render Report"]
    COMPLETE --> BUDGET{"Budget Exceeded?"}
    BUDGET -- "Yes" --> EXIT2["Exit 2: Budget Exceeded"]
    BUDGET -- "No" --> GATE{"--fail-on Gate Breached?"}
    GATE -- "Yes" --> EXIT4["Exit 4: Gate Breached"]
    GATE -- "No" --> QUERYERR{"Query / Validation Error?"}
    QUERYERR -- "Yes" --> EXIT1["Exit 1: Error"]
    QUERYERR -- "No" --> EXIT0["Exit 0: Success"]
```

### Exit Codes Reference

| Exit Code | Reason | Timing |
| --------- | ------ | ------ |
| **0** | Success: Workload profile succeeded cleanly, or discovery completed with valid shapes or clean empty window. | After report |
| **1** | Query or Validation Error: Malformed YAML, invalid CLI options, query syntax errors, or discovery Silent-Zero Guard misconfiguration. | After report / Immediate |
| **2** | Budget Exceeded: Cumulative Request Units exceeded `--ru-budget` ceiling (profiling mode only). | After report |
| **3** | Connection Failure: Target endpoint unreachable, network dropped mid-run, or Log Analytics workspace unreachable. | Immediate abort |
| **4** | Diagnostic Gate Breached: Findings met or exceeded `--fail-on` threshold (profiling mode only). | After report |
| **5** | Authentication Failure: Missing credentials, expired token, or missing RBAC permissions (`Cosmos DB Built-in Data Reader` or `Log Analytics Reader`). | Immediate abort |

---

## Design Decisions

Architectural choices are documented in our Architectural Decision Records:

- [ADR 0001](adr/0001-minimal-databaseadapter-protocol.md): `DatabaseAdapter` Protocol (`collect(workload) -> Iterator[QueryCost]`) and unified domain model, keeping diagnostic rules decoupled from SDK specifics.
- [ADR 0002](adr/0002-read-only-safety-and-payload-privacy.md): Read-only queries, streaming payload discard (`for _ in page: pass`) with no disk or cache persistence, and per-page RU budget circuit breakers.
- [ADR 0003](adr/0003-test-first-property-testing-and-docker-emulator.md): Testing strategy combining Hypothesis property-based tests, Syrupy snapshot assertions, and Docker Linux Cosmos DB emulator integration.
- [ADR 0004](adr/0004-cli-first-design-and-deterministic-exit-codes.md): CLI ergonomics and exit code hierarchy (`0`, `1`, `2`, `3`, `4`, `5`) for pipeline orchestration.
- [ADR 0005](adr/0005-azure-cosmos-sdk-contracts-and-metrics-extraction.md): Azure Cosmos SDK metrics extraction via `response_hook`, header parsing, and distinct physical partition key range IDs for cross-partition detection.
- [ADR 0006](adr/0006-azure-monitor-logs-query-contracts.md): Azure Monitor Logs query contracts, two-query server-side KQL aggregation, container-scoped database resolution, top-3 caller ranking, property bag packaging, and dynamic deserialization.
- [ADR 0007](adr/0007-kql-injection-defense-and-input-validation.md): KQL injection defense, parameter validation, and sanitization invariants for offline and online query construction.
