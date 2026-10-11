# Azure Monitor Logs Query Contracts and SDK Verification

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: Before implementing `querylens discover`, verify the exact SDK signatures, response objects, parameter handling, timeout options, and exception behaviors of `azure-monitor-query==2.0.0` to ensure robust, non-breaking metrics extraction and cloud-free testability.

## Context and Problem Statement

`querylens discover` identifies expensive query shapes in Azure Cosmos DB for NoSQL by querying diagnostic telemetry stored in an Azure Log Analytics workspace. Unlike `querylens run` (which interacts directly with the Cosmos DB data plane via `azure-cosmos`), `discover` interacts strictly with the Azure Monitor control/query plane via `azure-monitor-query`.

How does QueryLens reliably query Log Analytics workspaces, handle partial responses, enforce server-side query timeouts, map case-variant schema columns, and support 100% offline unit testing without live cloud dependencies?

## Decision Drivers

* Constitution Principle I: Zero-Impact, Read-Only Safety Guarantees (read-only control plane telemetry, zero Cosmos data plane calls, no secret persistence).
* Constitution Principle II: Minimal Abstraction Architecture (plain functions, injected `LogsQueryClient`, no bespoke factories or adapter protocols).
* Constitution Principle III: Test-First Rule Development & Offline Verification (ability to construct synthetic SDK responses without network calls).
* Constitution Principle IV: CLI-First Contract & Deterministic Exit Codes (mapping Azure Monitor exceptions to codes 0, 1, 3, 5).
* Verification of `azure-monitor-query==2.0.0` runtime contracts, parameter support, and response types.

## Considered Options

* Option 1: Use `azure-monitor-query==2.0.0` `LogsQueryClient.query_workspace` with plain functions, dependency injection for unit testing, and case-resilient KQL column mappings.
* Option 2: Build a generic `LogsQueryAdapter` abstraction mirroring `DatabaseAdapter`.
* Option 3: Call the Azure Monitor REST API directly using `httpx` or `requests`.

## Decision Outcome

Chosen option: "Option 1", because:

### 1. Verified SDK Signatures (`azure-monitor-query==2.0.0`)

Empirical inspection of `azure.monitor.query.LogsQueryClient` confirms:

* Method signature:

  ```python
  def query_workspace(
      self,
      workspace_id: str,
      query: str,
      *,
      timespan: timedelta | tuple[datetime, datetime] | tuple[datetime, timedelta] | str | None = None,
      server_timeout: int | None = None,
      include_statistics: bool | None = None,
      include_visualization: bool | None = None,
      **kwargs: Any,
  ) -> LogsQueryResult | LogsQueryPartialResult:
  ```

* Parameter contracts:
  * `workspace_id`: Target Log Analytics workspace GUID (RFC 4122).
  * `query`: Kusto Query Language (KQL) query string.
  * `timespan`: Time interval passed to Azure Monitor. The SDK serializes `timedelta` as an ISO 8601 duration (`P...`) or `tuple[datetime, datetime]` as an ISO 8601 interval (`start/end`).
  * `server_timeout`: Server timeout in integer seconds. Passed in HTTP headers as `Prefer: wait=<server_timeout>`. Default is 180 seconds; maximum allowed by Azure Monitor is 600 seconds.
  * `include_statistics`: Optional boolean to include query execution statistics.

### 2. Verified Response Handling (`LogsQueryResult` vs `LogsQueryPartialResult`)

`LogsQueryClient.query_workspace` returns either `LogsQueryResult` or `LogsQueryPartialResult`:

* **Complete Success (`LogsQueryResult`)**:
  * `result.status == LogsQueryStatus.SUCCESS`
  * `result.tables`: `list[LogsTable]`. Each `LogsTable` exposes:
    * `table.name`: string table name.
    * `table.columns`: list of column names or `LogsTableColumn` objects (`name`, `type`).
    * `table.rows`: list of `LogsTableRow` objects (subclass of `list`, supporting both index-based and column-name-based indexing: `row[0]` or `row["column_name"]`).
* **Partial Success (`LogsQueryPartialResult`)**:
  * Returned when partial data is available before hitting a resource limit.
  * `result.status == LogsQueryStatus.PARTIAL`
  * `result.partial_data`: `list[LogsTable]`.
  * `result.partial_error`: `ODataV4Format` containing error details.
* **Extraction Contract**:

  ```python
  tables: list[LogsTable] = (
      result.tables if isinstance(result, LogsQueryResult) else result.partial_data
  )
  ```

### 3. Absence of KQL Parameterization Mechanism

Inspection of `azure-monitor-query`'s REST serialization reveals the POST payload sent to `https://api.loganalytics.io/v1/workspaces/{workspaceId}/query`:

```json
{
  "query": "<KQL string>",
  "timespan": "<ISO 8601 duration or interval>",
  "workspaces": []
}
```

Neither the Azure Monitor Logs REST API nor the Python SDK provides a parameterized query binding mechanism (such as SQL `@param` or KQL `declare query_parameters(...)`). Therefore, all parameter filtering in KQL must be constructed programmatically. Strict validation and escaping must be enforced at the application boundary (see [ADR 0007](file:///docs/adr/0007-kql-injection-defense-and-input-validation.md)).

### 4. Cloud-Free Test Fixtures

`LogsTable` and `LogsTableRow` are lightweight classes that can be instantiated directly in test suites without network connections or mocked internals:

```python
from azure.monitor.query import LogsTable, LogsTableRow


def make_test_table(columns: list[str], rows: list[list[Any]]) -> LogsTable:
    return LogsTable(
        name="PrimaryResult",
        columns=columns,
        rows=[LogsTableRow(columns, row) for row in rows],
    )
```

This enables fast, deterministic unit and property tests with 0 live cloud dependencies.

### 5. Type-Safe Column Mapping with `tostring()` and `column_ifexists`

The legacy `AzureDiagnostics` table has known casing discrepancies across Azure regions, service versions, and diagnostic settings configurations. In KQL, referencing a non-existent column causes a fatal semantic compilation error (`'where' operator: Failed to resolve scalar expression...`). Furthermore, passing a string default to `column_ifexists()` for a `guid`-typed column (such as `activityId_g` or `aadPrincipalId_g`) causes a type resolution error.

To guarantee complete resilience and strict type safety, QueryLens routes **EVERY source column** through a centralized column mapping module (`src/querylens/discovery/columns.py`) by wrapping each column in `tostring()` before `coalesce()`:

* **`requestCharge_s`**: `coalesce(tostring(column_ifexists("requestCharge_s", "")), tostring(column_ifexists("RequestCharge_s", "")), "0")`
* **`statusCode_s`**: `coalesce(tostring(column_ifexists("statusCode_s", "")), tostring(column_ifexists("StatusCode_s", "")), "")`
* **`clientIpAddress_s`**: `coalesce(tostring(column_ifexists("clientIpAddress_s", "")), tostring(column_ifexists("ClientIpAddress_s", "")), "")`
* **`aadPrincipalId_g`**: `coalesce(tostring(column_ifexists("aadPrincipalId_g", "")), tostring(column_ifexists("AadPrincipalId_g", "")), "")`
* **`activityId_g`**: `coalesce(tostring(column_ifexists("activityId_g", "")), tostring(column_ifexists("ActivityId_g", "")), "")`
* **`querytext_s`**: `coalesce(tostring(column_ifexists("querytext_s", "")), tostring(column_ifexists("QueryText_s", "")), tostring(column_ifexists("queryText_s", "")), "")`
* **`shapesignature_s`**: `coalesce(tostring(column_ifexists("shapesignature_s", "")), tostring(column_ifexists("ShapeSignature_s", "")), tostring(column_ifexists("shapeSignature_s", "")), "")`
* **`numberofrowsreturned_s`**: `coalesce(tostring(column_ifexists("numberofrowsreturned_s", "")), tostring(column_ifexists("numberOfRowsReturned_s", "")), tostring(column_ifexists("NumberOfRowsReturned_s", "")), "0")`
* **Database Name**: `coalesce(tostring(column_ifexists("databaseName_s", "")), tostring(column_ifexists("databasename_s", "")), tostring(column_ifexists("DatabaseName_s", "")), "")`
* **Collection Name**: `coalesce(tostring(column_ifexists("collectionName_s", "")), tostring(column_ifexists("collectionname_s", "")), tostring(column_ifexists("CollectionName_s", "")), "")`

**Design Guarantees**:

1. **Uniform String Join Keys**: Join keys on `activityId_g` strictly use the `tostring()`-evaluated value, eliminating GUID vs string join mismatch errors.
2. **Missing Column Tolerance**: If an optional or deprecated column is completely missing, the expression evaluates to a safe fallback string (`""` or `"0"`), yielding `None` or `0` in Python, **never** a failed query.
3. **Returned Rows vs Scanned Documents**: Cosmos DB diagnostic logs record `numberofrowsreturned_s` (documents returned). Diagnostic logs **do NOT contain** a scanned-documents metric (such as `retrievedDocumentCount` from client-side headers). Therefore, QueryLens strictly extracts returned rows and intentionally omits any scanned-documents metric from discovery.

### 6. Two-Query Architecture (Shapes Query & Totals Query)

Because Azure Monitor Log Analytics executes a script and returns **only the final tabular result set** (let assignments without `union` do not emit intermediate scalar outputs), QueryLens executes **two distinct, targeted KQL queries**:

1. **Shapes Query (Top N)**:
   * Evaluates pre-aggregated requests and queries joined 1-to-1 on `activityId_g`.
   * Wraps `joined` in `materialize()` to guarantee the join is evaluated once.
   * Summarizes top shapes and wraps `top_shapes` in `materialize()` so top-N ranking ties cannot diverge between the caller extraction join and the final projection.
   * Extracts top 3 callers per shape partitioned by `caller_ru desc` (implemented in User Story 3; User Story 1 delivers the baseline query without callers).
   * Returns at most $N$ rows.
2. **Totals Query (1 Row Summary)**:
   * Evaluates `DataPlaneRequests` and joined query shapes over the entire window.
   * Returns a single 1-row table containing:
     * `window_total_ru`: Total RU across all `DataPlaneRequests` in the window (the denominator, scoped to account).
     * `attributed_total_ru`: Cumulative RU summed across ALL joined query shapes (not just the top N).
     * `total_executions`: Count of all query executions across all shapes in the window.
     * `min_time_generated`: `min(TimeGenerated)` from `DataPlaneRequests`.
   * Client derives `unattributed_ru = max(0.0, window_total_ru - attributed_total_ru)`, `unattributed_ru_pct`, shape RU shares, and retention warning.
   * Network transfer bound: At most $N$ shape rows plus 1 totals row.

### 7. Account Filter and Materialization Invariants

* **Account Filter Suffix**: To avoid term-splitting quirks with `has`, the account filter strictly uses:

  ```kusto
  | where _ResourceId endswith "/databaseaccounts/{escaped_account}"
  ```

  applied in **every sub-query** of both the shapes query and the totals query.
* **Deterministic Materialization**:

  ```kusto
  let ql_joined = materialize(
      ql_qrs
      | join kind=inner ql_reqs on ql_activity_id
      | extend ...
  );
  ...
  let ql_top_shapes = materialize(
      ql_joined
      | summarize ...
      | top N by ql_total_ru desc
  );
  ```

  guarantees zero evaluation drift or tie-breaking discrepancies across CTE references.

### 8. Silent-Zero Guard

If diagnostic settings stream `DataPlaneRequests` but `QueryRuntimeStatistics` is disabled or key columns (`requestCharge_s`, `activityId_g`, `querytext_s`) are empty, a naive query would return 0 total RU or empty results.

QueryLens implements a strict **Silent-Zero Guard**:

* If `attributed_total_ru == 0` while `window_total_ru > 0`, OR if essential columns are completely unpopulated:
  * Abort execution with **exit code 1**.
  * Print an actionable error to `stderr` explaining that diagnostic telemetry is incomplete and directing the user to run `querylens discover --check`.
  * Prevents users from mistaking misconfigured logging for "zero query cost".

### 9. Exception Handling and Exit Code Mapping

To comply with [ADR 0004](file:///docs/adr/0004-cli-first-design-and-deterministic-exit-codes.md), Azure Monitor client exceptions are mapped deterministically:

* **Exit Code 5 (Auth / Permission Error)**:
  * `azure.core.exceptions.ClientAuthenticationError` (missing credentials, expired Entra token).
  * `azure.core.exceptions.HttpResponseError` when `error.status_code in (401, 403)` (e.g. caller lacks `Log Analytics Reader` role on the workspace).
* **Exit Code 3 (Connection / Workspace Not Found / Network Timeout)**:
  * `azure.core.exceptions.HttpResponseError` when `error.status_code == 404` (Workspace GUID does not exist or was deleted).
  * `azure.core.exceptions.ServiceRequestError` (DNS failure, network unreachable).
  * `azure.core.exceptions.ServiceRequestTimeoutError` (client-side HTTP timeout).
* **Exit Code 1 (Validation / Client Error / KQL Syntax Error / Silent-Zero Guard)**:
  * `ValueError` (invalid workspace UUID, invalid account regex, invalid window).
  * Silent-Zero Guard trigger (telemetry misconfiguration).
  * `azure.core.exceptions.HttpResponseError` when `error.status_code == 400` (e.g., malformed KQL or invalid workspace parameter).

### 10. Testing Strategy, CI Limits, and Mandatory Release Gating

> [!IMPORTANT]
> **KQL is Never Executed in CI Pipelines**
>
> In accordance with Constitution Principle I (Read-Only Safety) and Principle III (Offline CI Verification), QueryLens automated test suites run with **zero live cloud dependencies**. CI tests utilize 100% synthetic `LogsTable` fixtures and golden snapshot tests.
>
> Therefore, **snapshot tests protect strictly against unintended query text regressions, NOT against semantic KQL execution correctness on live Azure backends.**

To guarantee real-world query validity, QueryLens provides the `--print-kql` CLI option and enforces a mandatory manual qualification gate:

* **`--print-kql` Tooling**: Developers can run `querylens discover --workspace-id <uuid> --print-kql` to generate and print **both queries** (the Shapes query and the Totals query) without network calls or credentials, allowing instant copy-pasting into the Azure portal Log Analytics query editor.
* **Golden Snapshot Tests**: Golden snapshot tests (`test_discover_kql_snapshots.py`) assert the exact query text for both queries across argument combinations.
* **Mandatory Release Qualification Gate**: **Every release MUST be gated on a manual validation run** following [docs/manual-testing.md](file:///docs/manual-testing.md):
  1. Generate queries via `--print-kql` and run **both queries** in the Azure Portal Logs editor against a populated workspace to confirm zero syntax or column resolution errors.
  2. Run `querylens discover --check` against a live workspace to confirm diagnostic metadata extraction.
  3. Run `querylens discover` against a live workspace to confirm end-to-end shape discovery, caller attribution, and formatting.

### 11. Structural KQL Identifier Collision Prevention via Prefix Convention

During live workspace testing, queries using identifiers such as `queries` failed with semantic errors because `queries` is a reserved word in Azure Data Explorer / Kusto. While Microsoft documents identifier quoting and naming conventions, Microsoft publishes **no normative, exhaustive reserved-word list** for KQL. Maintaining a heuristic blacklist of reserved keywords is therefore fragile and incomplete.

To make identifier collisions structurally impossible across all Azure Monitor versions and service environments:

* **Universal `ql_` Prefix Control**: **EVERY** generated identifier in all queries (`build_shapes_query`, `build_totals_query`, and `build_preflight_check_query`) must begin with `ql_`:
  * All `let` statement CTE variable names (e.g., `ql_reqs`, `ql_qrs`, `ql_joined`, `ql_known_db_by_shape_container`, `ql_single_db_shape_containers`, `ql_resolved_activities`, `ql_top_shapes`, `ql_top_shape_keys`, `ql_top_callers_per_shape`, `ql_base`, `ql_counts`, `ql_auth`).
  * All computed intermediate column aliases and join keys (e.g., `ql_activity_id`, `ql_total_charge`, `ql_is_429`, `ql_db_name`, `ql_coll_name`, `ql_shape_id`, `ql_db_count`, `ql_resolved_db`, `ql_caller_id`, `ql_caller_type`, `ql_caller_ru`, `ql_caller_rank`, `ql_top_callers`).
  * All projected final output columns (e.g., `ql_db_name`, `ql_coll_name`, `ql_shape_id`, `ql_sample_text`, `ql_execution_count`, `ql_total_ru`, `ql_max_ru`, `ql_total_returned_rows`, `ql_throttled_count`, `ql_top_callers`, `ql_window_total_ru`, `ql_attributed_total_ru`, `ql_total_executions`, `ql_min_time_generated`, `ql_dataplane_count`, `ql_auth_breakdown`).
* **Double Underscore Ban**: Generated identifiers must never start or end with double underscores (`__`).
* **Automated Convention Enforcement**: Rather than testing against an incomplete reserved-word list, QueryLens enforces naming through an automated convention test (`test_kql_identifier_naming_conventions` in `tests/unit/test_discover_kql.py`):
  * Every generated `let` name, computed alias, and output column must match `^ql_[a-z0-9_]+$`.
  * An explicit minimal allowlist is permitted strictly for external Azure schema columns referenced by the queries: `{"Category", "ResourceProvider", "TimeGenerated", "_ResourceId"}`.
* **Domain Model Decoupling**: The `ql_` prefix is strictly internal to the KQL generation and row-mapping service layer. Public domain entities (`DiscoveredQueryShape`, `PreflightCheckReport`) and JSON contract schemas preserve clean, unprefixed field names (`database`, `container`, `total_ru`, `execution_count`).

### 12. Authentication Token Breakdown Dynamic Packaging and Strict Deserialization

During live workspace qualification, aggregating authentication token types using `make_list(pack_array(ql_auth_type, ql_count))` failed because the Azure Monitor service flattened the nested list of pairs into a single flat array (e.g. `['AadToken', 62135, 'PrimaryMasterKey', 12511]`), which caused pair-oriented parsers to silently drop all records.

To guarantee accurate aggregation and robust parsing:

* **KQL Property Bag Aggregation**: `build_preflight_check_query` packages the distribution using `make_bag(bag_pack(ql_auth_type, ql_count))`. This generates a native KQL property bag that deserializes directly into a key-value mapping (`dict[str, int]`).
* **Strict Shape Enforcement**: `run_preflight_check` in `service.py` strictly validates the parsed shape: it accepts only a dictionary mapping authentication types to integer counts. Any unexpected response shape (including flat lists or list of pairs) immediately raises `InternalConsistencyError` with a descriptive message rather than silently returning an empty distribution.

### 13. Unknown Database Resolution Scoped to (Shape, Container)

In Azure Cosmos DB diagnostic logs, `QueryRuntimeStatistics` occasionally omits the database name for certain SDK requests while still emitting the container name and query text/shape.

During live workspace qualification, resolving unknown database names purely at the query shape level caused cross-container pollution: when a shape ran in multiple containers, activities in one container could be erroneously relabeled with another container's database and container name.

To prevent container misattribution while still resolving omitted database names:

* **Scoped Key Matching**: `build_shapes_query` pre-computes known database names strictly grouped by `(ql_shape_id, ql_coll_name)` in `ql_known_db_by_shape_container`.
* **Single Known Database Invariant**: In `ql_single_db_shape_containers`, resolution occurs only when a `(shape, container)` pair has exactly one distinct known database name in the requested time window (`ql_db_count == 1`).
* **Container Preservation**: The resolution join matches on `(ql_shape_id, ql_coll_name)` and fills *only* `ql_db_name`. The container name is never overwritten. If an activity's container is empty, or if a `(shape, container)` pair has zero or multiple known database names, the database remains `"(unknown)"`.
* **Materialization of Resolved Activities**: Because `ql_resolved_activities` is evaluated by both `ql_top_shapes` and `ql_top_callers_per_shape`, it is wrapped in `materialize()` to prevent duplicate resolution joins and guarantee consistent row evaluation in Kusto.

### 14. Server-Side Top 3 Caller Ranking and Dynamic Bag Packing (User Story 3)

To identify microservices and client applications driving query shape spend without streaming unaggregated records:

* **Bounded Caller Scope**: Caller aggregation joins `ql_resolved_activities` against `ql_top_shape_keys` (`inner join on ql_db_name, ql_coll_name, ql_shape_id`). Caller spend is calculated strictly for the top $N$ shapes, avoiding expensive workspace-wide caller grouping.
* **Identifier Preference**: Resolves `ql_caller_id = iff(isnotempty(ql_aad_principal), ql_aad_principal, ql_client_ip)` and sets `ql_caller_type` to `"aad_principal"`, `"client_ip"`, or `"none"`. Executions lacking both identifiers are filtered out (`where isnotempty(ql_caller_id) and ql_caller_type != "none"`).
* **Guaranteed Per-Shape Top 3 Ranking**: Rather than relying on `make_list` ordering, callers are aggregated per `(ql_db_name, ql_coll_name, ql_shape_id, ql_caller_id, ql_caller_type)` and ordered by partition keys and caller RU descending with identifier tie-breaker. Deterministic ranking is generated via `serialize ql_caller_rank = row_number(1, ql_db_name != prev(ql_db_name) or ql_coll_name != prev(ql_coll_name) or ql_shape_id != prev(ql_shape_id))` and strictly bounded via `where ql_caller_rank <= 3` before collecting into dynamic property bags with `make_list(bag_pack(...))`.
* **Left Outer Join & Empty Dynamic Array Default**: Left-outer-joins callers onto `ql_top_shapes` and projects `ql_top_callers = coalesce(ql_top_callers, dynamic([]))`, ensuring shapes without identifiable callers preserve empty lists without schema deviation.
* **Strict Deserialization & Tie-Breaker Ordering**: In `service.py`, `_parse_top_callers` accepts only a list of dictionaries with valid keys (`identifier`, `caller_ru`, `identifier_type`) and types. Callers are sorted by `caller_ru` descending with `identifier` ascending as tie-breaker. Any malformed shapes (flat arrays, nested pair arrays, > 3 callers, negative or excess RU share > 100.05%) raise `InternalConsistencyError`, handled cleanly by the CLI with exit code 1.
