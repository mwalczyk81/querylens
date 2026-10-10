# Research & Architectural Decisions: Query Cost Discovery

**Feature**: `002-query-cost-discovery` (`querylens discover`)
**Date**: 2026-10-10
**Status**: Completed (Updated with Review Findings)

---

## 1. Package Architecture and Component Seams

### Decision

Implement the discovery feature inside a new standalone package `querylens.discovery` with plain functions and an injected `LogsQueryClient` instance. Do not define new `Protocol` interfaces, base classes, or factory patterns. The existing `DatabaseAdapter` protocol remains strictly focused on active workload profiling (`querylens run`) and is untouched.

### Rationale

- Constitution Principle II explicitly states: *"No additional intermediate layers, abstractions, or design patterns (e.g., repository layers, complex plugin registries) MAY be introduced without an approved Architecture Decision Record (ADR) justifying the complexity."*
- `querylens run` interacts with the Cosmos DB data plane (`azure-cosmos` querying item containers). `querylens discover` interacts with the Azure Monitor log analytics query plane (`azure-monitor-query` querying workspace tables).
- These two access patterns share no connection lifecycle, data models, or query syntax. Introducing a shared adapter abstraction would be an unnatural coupling and leaky abstraction.
- Plain functions accepting `client: LogsQueryClient | None = None` provide maximum testability, allow direct dependency injection of fake/mock clients in unit tests, and maintain zero runtime overhead.

### Alternatives Considered

- *Extend `DatabaseAdapter` Protocol*: Rejected. `DatabaseAdapter` specifies `collect(workload: Workload) -> Iterator[QueryCost]`. Discovery does not profile workloads; it analyzes aggregated historical log telemetry.
- *Abstract Factory / Class Hierarchy*: Rejected. Adds indirection and boilerplate without providing any polymorphic benefit (we only query Azure Log Analytics).

---

## 2. CLI Command Structure and Modularization

### Decision

Implement the CLI entry point in a dedicated module `src/querylens/discover_cli.py` and register it on the existing main Click group (`cli` in `src/querylens/cli.py`) using `cli.add_command(discover)`.

### Rationale

- `src/querylens/cli.py` is already ~330 lines long containing options, validation, and execution logic for `querylens run`.
- Separating `discover` into `discover_cli.py` keeps CLI definition clean, ensures modular testability, and prevents `cli.py` from becoming an unmanageable monolithic file.
- Reuses existing exit code conventions from [ADR 0004](file:///docs/adr/0004-cli-first-design-and-deterministic-exit-codes.md) (0 for success, 1 for usage/validation error, 3 for network/workspace error, 5 for authentication/authorization error).

### Alternatives Considered

- *Append command directly into `src/querylens/cli.py`*: Rejected due to module size and risk of regression to existing `run` CLI logic.

---

## 3. Type-Safe Column Mapping and Schema Resilience

### Decision

Create a centralized column mapping module `src/querylens/discovery/columns.py` routing **EVERY source column** through KQL expressions wrapping each column in `tostring()` before `coalesce()`:

- **`requestCharge_s`**: `coalesce(tostring(column_ifexists("requestCharge_s", "")), tostring(column_ifexists("RequestCharge_s", "")), "0")`
- **`statusCode_s`**: `coalesce(tostring(column_ifexists("statusCode_s", "")), tostring(column_ifexists("StatusCode_s", "")), "")`
- **`clientIpAddress_s`**: `coalesce(tostring(column_ifexists("clientIpAddress_s", "")), tostring(column_ifexists("ClientIpAddress_s", "")), "")`
- **`aadPrincipalId_g`**: `coalesce(tostring(column_ifexists("aadPrincipalId_g", "")), tostring(column_ifexists("AadPrincipalId_g", "")), "")`
- **`activityId_g`**: `coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "")`
- **`querytext_s`**: `coalesce(tostring(column_ifexists("querytext_s", "")), tostring(column_ifexists("QueryText_s", "")), tostring(column_ifexists("queryText_s", "")), "")`
- **`shapesignature_s`**: `coalesce(tostring(column_ifexists("shapesignature_s", "")), tostring(column_ifexists("ShapeSignature_s", "")), tostring(column_ifexists("shapeSignature_s", "")), "")`
- **`numberofrowsreturned_s`**: `coalesce(tostring(column_ifexists("numberofrowsreturned_s", "")), tostring(column_ifexists("numberOfRowsReturned_s", "")), tostring(column_ifexists("NumberOfRowsReturned_s", "")), "0")`
- **Database Name**: `coalesce(tostring(column_ifexists("databaseName_s", "")), tostring(column_ifexists("databasename_s", ""), tostring(column_ifexists("DatabaseName_s", "")), "")`
- **Collection Name**: `coalesce(tostring(column_ifexists("collectionName_s", "")), tostring(column_ifexists("collectionname_s", ""), tostring(column_ifexists("CollectionName_s", "")), "")`

### Rationale

- In Azure Monitor Log Analytics, the legacy `AzureDiagnostics` table suffers from inconsistent casing across regions and service generations. In KQL, referencing a non-existent column produces a fatal semantic compilation error.
- Passing string defaults to `column_ifexists()` on `guid`-typed columns (`activityId_g`, `aadPrincipalId_g`) causes scalar type resolution errors. Wrapping with `tostring(...)` ensures uniform string handling and guarantees joins on `activityId_g` evaluate cleanly.
- If an optional column is missing, the expression evaluates to a safe fallback (`""` or `"0"`), yielding `None` or `0` in Python, **never** a failed query.
- **Documents Returned vs Scanned**: Cosmos DB diagnostic logs record `numberofrowsreturned_s` (documents returned). Diagnostic logs **do NOT contain a scanned-documents metric** (such as `retrievedDocumentCount` found only in direct client-side execution headers). Therefore, QueryLens strictly extracts returned rows (`numberofrowsreturned_s`) and intentionally omits any scanned-documents metric from discovery.

---

## 4. Two-Query Architecture & Server-Side KQL Aggregation

### Decision

Because Azure Monitor Log Analytics returns **only the final tabular result set** of a query, QueryLens executes **two distinct server-side KQL queries**:

1. **Query 1 (Shapes Query)**: Returns the top $N$ query shapes with caller bags, executions, and RU aggregates.
2. **Query 2 (Totals Query)**: Returns a single 1-row summary table containing `window_total_ru`, `attributed_total_ru`, `total_executions`, and `min_time_generated`.

#### Query 1: Top Query Shapes Query

```kusto
let reqs = AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
    // Account filter applied if specified:
    // | where _ResourceId endswith "/databaseaccounts/{escaped_account}"
    | summarize
        total_charge = sum(todouble(coalesce(tostring(column_ifexists("requestCharge_s", "")), tostring(column_ifexists("RequestCharge_s", "")), "0"))),
        is_429 = max(iff(coalesce(tostring(column_ifexists("statusCode_s", "")), tostring(column_ifexists("StatusCode_s", "")), "") == "429", 1, 0)),
        client_ip = take_any(coalesce(tostring(column_ifexists("clientIpAddress_s", "")), tostring(column_ifexists("ClientIpAddress_s", "")), "")),
        aad_principal = take_any(coalesce(tostring(column_ifexists("aadPrincipalId_g", "")), tostring(column_ifexists("AadPrincipalId_g", "")), ""))
      by activityId_g = coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "");

let queries = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
    // | where _ResourceId endswith "/databaseaccounts/{escaped_account}"
    | extend
        db_name = coalesce(tostring(column_ifexists("databaseName_s", "")), tostring(column_ifexists("databasename_s", "")), tostring(column_ifexists("DatabaseName_s", "")), ""),
        coll_name = coalesce(tostring(column_ifexists("collectionName_s", "")), tostring(column_ifexists("collectionname_s", "")), tostring(column_ifexists("CollectionName_s", "")), ""),
        shape_sig = coalesce(tostring(column_ifexists("shapesignature_s", "")), tostring(column_ifexists("ShapeSignature_s", "")), tostring(column_ifexists("shapeSignature_s", "")), ""),
        raw_text = coalesce(tostring(column_ifexists("querytext_s", "")), tostring(column_ifexists("QueryText_s", "")), tostring(column_ifexists("queryText_s", "")), ""),
        returned_count = todouble(coalesce(tostring(column_ifexists("numberofrowsreturned_s", "")), tostring(column_ifexists("numberOfRowsReturned_s", "")), tostring(column_ifexists("NumberOfRowsReturned_s", "")), "0"))
    | extend shape_key = iff(isnotempty(shape_sig), shape_sig, hash_sha256(raw_text))
    | summarize
        database = take_any(db_name),
        container = take_any(coll_name),
        shape_id = take_any(shape_key),
        sample_query_text = take_any(raw_text),
        returned_rows = sum(returned_count)
      by activityId_g = coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "");

let joined = materialize(
    queries
    | join kind=inner reqs on activityId_g
    | extend
        caller_id = iff(isnotempty(aad_principal), aad_principal, client_ip),
        caller_type = iff(isnotempty(aad_principal), "aad_principal", iff(isnotempty(client_ip), "client_ip", "none"))
);

let top_shapes = materialize(
    joined
    | summarize
        execution_count = count(),
        total_ru = sum(total_charge),
        max_ru = max(total_charge),
        total_returned_rows = sum(returned_rows),
        throttled_count = sum(is_429),
        sample_text = take_any(sample_query_text)
      by database, container, shape_id
    | top N by total_ru desc
);

let top_shape_keys = top_shapes | project database, container, shape_id;

let top_callers_per_shape = joined
| join kind=inner top_shape_keys on database, container, shape_id
| where isnotempty(caller_id) and caller_type != "none"
| summarize caller_ru = sum(total_charge) by database, container, shape_id, caller_id, caller_type
| order by database asc, container asc, shape_id asc, caller_ru desc
| summarize top_callers = make_list(bag_pack("identifier", caller_id, "caller_ru", caller_ru, "identifier_type", caller_type), 3)
  by database, container, shape_id;

top_shapes
| join kind=leftouter top_callers_per_shape on database, container, shape_id
| project
    database, container, shape_id, sample_text,
    execution_count, total_ru, max_ru, total_returned_rows,
    throttled_count,
    top_callers = coalesce(top_callers, dynamic([]))
```

#### Query 2: Window & Attributed Totals Query

```kusto
let reqs = AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
    // | where _ResourceId endswith "/databaseaccounts/{escaped_account}"
    | summarize
        total_charge = sum(todouble(coalesce(tostring(column_ifexists("requestCharge_s", "")), tostring(column_ifexists("RequestCharge_s", "")), "0"))),
        earliest_time = min(TimeGenerated)
      by activityId_g = coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "");

let queries = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
    // | where _ResourceId endswith "/databaseaccounts/{escaped_account}"
    | summarize by activityId_g = coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "");

let window_total = toscalar(reqs | summarize sum(total_charge));
let min_time = toscalar(reqs | summarize min(earliest_time));

queries
| join kind=inner reqs on activityId_g
| summarize
    attributed_total_ru = sum(total_charge),
    total_executions = count()
| extend
    window_total_ru = window_total,
    min_time_generated = min_time
```

### Rationale

- **Deterministic Evaluation with `materialize()`**: Wrapping `joined` and `top_shapes` in `materialize()` prevents CTE re-evaluation, guarantees join consistency, and eliminates tie-breaking rank discrepancies.
- **Accurate Denominator & True Attributed Sum**: `window_total_ru` provides the total RU of all data plane requests in the window. `attributed_total_ru` sums RU over **ALL joined queries** across the entire window (not just the top N). The client computes `unattributed_ru = max(0.0, window_total_ru - attributed_total_ru)`.
- **Exact Transfer Bounds**: The client receives at most $N$ shape rows from Query 1 plus 1 totals row from Query 2, strictly satisfying SC-001.

---

## 5. Server-Side Extraction of Top 3 Callers Per Shape

### Decision

Extract the top 3 callers **per query shape** server-side within KQL, strictly bounded to the top N shapes using `top_shape_keys` filtering, sorting by `caller_ru desc` within each shape, and packaging into a dynamic array with `make_list(..., 3)`.

### Rationale

- Callers are ranked *per shape*, guaranteeing that each shape reflects its own top 3 callers rather than a global top 3.
- Bounding the caller join to `top_shape_keys` offloads aggregation to Azure Monitor and prevents shipping large unaggregated caller tables to the client.

### Staged Implementation Across User Stories

- **User Story 1 (MVP)**: `build_shapes_query` generates the baseline shapes query returning shapes without caller ranking, terminating directly at `top_shapes` projection. Output schema and US1 tests do not require callers.
- **User Story 3**: Extends `build_shapes_query` with `top_callers_per_shape` join and `make_list(bag_pack(...), 3)`, updates golden KQL snapshots, and implements dynamic bag parsing in the service.

---

## 6. Retention Warning Logic via Data Inference

### Decision

Infer retention window boundaries by comparing `min_time_generated` from the Totals Query directly against the requested window start timestamp:
$$\text{min\_time} > \text{window\_start} + \max(1\text{h}, 0.05 \times \text{window\_duration})$$

---

## 7. Throttling (HTTP 429) Accounting

### Decision

Count 429 throttling events per shape by evaluating `statusCode_s == "429"` in `DataPlaneRequests`, strictly joined on `activityId_g` to the shape's query execution.

---

## 8. Preflight Health Check (`querylens discover --check`)

### Decision

Implement `--check` as a non-intrusive metadata check verifying workspace connectivity, detected diagnostic categories, row counts, earliest and latest record timestamps, key field coverage percentages, and auth token distributions. Emits 100% quantitative metrics with zero query text.

---

## 9. Privacy Alignment and Obfuscation Handling (FR-012)

### Decision

Strictly adhere to **FR-012**:

- **`--json` Output**: `sample_query_text` is **OMITTED** entirely from JSON result objects by default. It is included only if `--show-text` is passed.
- **Console Table Output**: `sample_query_text` is truncated to 200 characters in terminal tables by default. When `--show-text` is passed, the full query text is displayed.
- **Contract Test**: A dedicated contract test (`test_discover_json_omits_query_text_by_default`) asserts that default JSON contains zero `sample_query_text` keys.

---

## 10. `--print-kql` Option for Offline Inspection & Azure Portal Verification

### Decision

Provide a `--print-kql` CLI option that constructs and prints **both KQL queries** (Query 1: Shapes Query and Query 2: Totals Query) to `stdout` following standard input validation, without initiating any network calls or requiring credentials, and exits with code 0.

---

## 11. Silent-Zero Guard (Telemetry Misconfiguration Defense)

### Decision

If `attributed_total_ru == 0` while `window_total_ru > 0`, OR if essential diagnostic columns (`requestCharge_s`, `activityId_g`, `querytext_s`) are entirely absent or unpopulated:

- Abort execution with **exit code 1**.
- Emit a clear, actionable error on `stderr` pointing the user to `querylens discover --check`.
- Protects users from misinterpreting broken or unconfigured diagnostics as zero-cost query executions.
