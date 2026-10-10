# Azure Cosmos SDK Contracts and Metrics Extraction

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: Before writing `CosmosAdapter`, confirm the exact signatures and response header specifications for `azure-cosmos` 4.17.1 to ensure robust, non-breaking metrics extraction and error handling.

## Context and Problem Statement

QueryLens relies on low-level query metrics returned by Azure Cosmos DB to calculate Request Units (RUs), scanned vs returned document ratios, execution latencies, physical partition fan-out, and index utilization. These metrics are exposed via HTTP response headers and SDK callback mechanisms. How does QueryLens reliably capture these metrics using `azure-cosmos==4.17.1` while preserving zero-payload privacy?

## Decision Drivers

* Constitution Principle I: Zero-Impact, Read-Only Safety Guarantees (payload discard).
* Exact verification of installed `azure-cosmos==4.17.1` API signatures.
* Accurate parsing of semi-structured query metrics headers and Base64-encoded index utilization JSON.
* Accurate discrimination between network/not found errors (exit code 3) and auth/permission errors (exit code 5).

## Considered Options

* Option 1: Use `ContainerProxy.query_items` with `populate_query_metrics=True`, `populate_index_metrics=True`, `response_hook` callback to aggregate headers across physical partitions/pages, discarding document items via streaming page iteration.
* Option 2: Inspecting internal `CosmosItemPaged.get_response_headers()` after consuming the entire result set.
* Option 3: Wrapping the underlying HTTP transport with a custom pipeline policy.

## Decision Outcome

Chosen option: "Option 1", because:

### 1. Verified SDK Signatures (`azure-cosmos==4.17.1`)
- Method: `ContainerProxy.query_items(query, parameters=None, partition_key=None, enable_cross_partition_query=None, max_item_count=None, populate_query_metrics=None, populate_index_metrics=None, response_hook=None, ...)`
- Parameter mappings:
  - `query`: SQL query string.
  - `parameters`: Optional list of dicts `[{"name": "@param", "value": val}]`.
  - `partition_key`: Scalar value or list of 1–3 scalars for hierarchical partition keys.
  - `populate_query_metrics=True`: Tells the Cosmos DB gateway/backend to emit execution metrics.
  - `populate_index_metrics=True`: Tells the Cosmos DB engine to emit index utilization and recommendations.
  - `response_hook`: Callback receiving `(headers: Mapping[str, str], body: dict[str, Any])` for each HTTP page/partition response.

### 2. Verified Response Header Constants (`azure.cosmos.http_constants.HttpHeaders`)
- `HttpHeaders.RequestCharge` (`"x-ms-request-charge"`): Float string representing the RU cost consumed by that page.
- `HttpHeaders.QueryMetrics` (`"x-ms-documentdb-query-metrics"`): Semicolon-delimited key-value string containing:
  - `retrievedDocumentCount=N`
  - `outputDocumentCount=M`
  - `totalExecutionTimeInMs=X`
  - `queryCompileTimeInMs=Y`
  - `indexLookupTimeInMs=Z`
  - `documentLoadTimeInMs=W`
  - `documentWriteTimeInMs=V`
- `HttpHeaders.IndexUtilization` (`"x-ms-cosmos-index-utilization"`): Base64-encoded UTF-8 string that decodes to a JSON structure:
  - `UtilizedSingleIndexes`: list of utilized single index paths
  - `PotentialSingleIndexes`: list of recommended single index paths
  - `UtilizedCompositeIndexes`: list of utilized composite index paths
  - `PotentialCompositeIndexes`: list of recommended composite index paths

### 3. Iteration and Zero-Payload Discard
- The returned `CosmosItemPaged` is iterated by page:
  ```python
  for page in paged_results.by_page():
      for _ in page:
          pass  # Zero-Impact: payload immediately dropped
  ```
- Cumulative RUs are tracked via the `response_hook` or page response headers. If cumulative RUs exceed `--budget-ru`, iteration breaks immediately, marking `is_partial=True` and exiting with code 2.

### 4. Exception Handling Contract
- **Exit Code 5 (Authentication / Authorization)**:
  - `azure.core.exceptions.ClientAuthenticationError`
  - `azure.cosmos.exceptions.CosmosHttpResponseError` when `error.status_code in (401, 403)`
- **Exit Code 3 (Connection / Resource Not Found)**:
  - `azure.cosmos.exceptions.CosmosResourceNotFoundError` (HTTP 404, database/container not found)
  - `azure.core.exceptions.ServiceRequestError` (connection refused, DNS failure)
  - `azure.cosmos.exceptions.CosmosClientTimeoutError` / `azure.core.exceptions.ServiceRequestTimeoutError`

### Positive Consequences

* Clean, standards-based integration using official SDK public extensibility points (`response_hook`).
* Zero memory pressure from large result sets.
* Robust header parsing resilient to variations in metric header whitespace or missing optional metrics.
* Accurate exit codes aligned with enterprise security and DevOps requirements.

### Negative Consequences

* Index metrics header parsing requires base64 decoding and JSON parsing, adding minor CPU overhead when `--diagnose` or index metrics are requested (negligible compared to network I/O).

## Pros and Cons of the Options

### Option 1: Public `query_items` with `response_hook` (Chosen)

* Good, because officially supported public SDK callback.
* Good, because captures metrics per physical partition and per page in multi-partition fan-out queries.
* Good, because enables real-time cumulative RU tracking for mid-query aborts.
* Bad, because callback receives empty/internal body representation that must simply be ignored.

### Option 2: Post-Iterative Header Inspection

* Good, because avoids callback setup.
* Bad, because `get_response_headers()` only reflects the last page received, losing per-partition metrics in fan-out queries.

### Option 3: Custom HTTP Pipeline Policy

* Good, because intercepts raw network bytes.
* Bad, because violates Constitution Principle II; unnecessarily complex when `response_hook` is available.
