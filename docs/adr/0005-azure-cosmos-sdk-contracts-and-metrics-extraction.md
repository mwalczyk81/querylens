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

* Method: `ContainerProxy.query_items(query, parameters=None, partition_key=None, enable_cross_partition_query=None, max_item_count=None, populate_query_metrics=None, populate_index_metrics=None, response_hook=None, ...)`
* Parameter mappings:
  * `query`: SQL query string.
  * `parameters`: Optional list of dicts `[{"name": "@param", "value": val}]`.
  * `partition_key`: Scalar value or list of 1–3 scalars for hierarchical partition keys.
  * `populate_query_metrics=True`: Tells the Cosmos DB gateway/backend to emit execution metrics.
  * `populate_index_metrics=True`: Tells the Cosmos DB engine to emit index utilization and recommendations.
  * `response_hook`: Callback receiving `(headers: Mapping[str, str], body: dict[str, Any])` for each HTTP page/partition response.

### 2. Verified Response Header Constants (`azure.cosmos.http_constants.HttpHeaders`)

* `HttpHeaders.RequestCharge` (`"x-ms-request-charge"`): Float string representing the RU cost consumed by that page.
* `HttpHeaders.QueryMetrics` (`"x-ms-documentdb-query-metrics"`): Semicolon-delimited key-value string containing:
  * `retrievedDocumentCount=N`
  * `outputDocumentCount=M`
  * `totalExecutionTimeInMs=X`
  * `queryCompileTimeInMs=Y`
  * `indexLookupTimeInMs=Z`
  * `documentLoadTimeInMs=W`
  * `documentWriteTimeInMs=V`
* `HttpHeaders.IndexUtilization` (`"x-ms-cosmos-index-utilization"`): Base64-encoded UTF-8 string that decodes to a JSON structure:
  * `UtilizedSingleIndexes`: list of utilized single index paths
  * `PotentialSingleIndexes`: list of recommended single index paths
  * `UtilizedCompositeIndexes`: list of utilized composite index paths
  * `PotentialCompositeIndexes`: list of recommended composite index paths

### 3. Iteration and Zero-Payload Discard

* The returned `CosmosItemPaged` is iterated by page:

  ```python
  for page in paged_results.by_page():
      for _ in page:
          pass  # Zero-Impact: payload immediately dropped
  ```

* Cumulative RUs are tracked via the `response_hook` or page response headers. If cumulative RUs exceed `--budget-ru`, iteration breaks immediately, marking `is_partial=True` and exiting with code 2.

### 4. Exception Handling Contract

* **Exit Code 5 (Authentication / Authorization)**:
  * `azure.core.exceptions.ClientAuthenticationError`
  * `azure.cosmos.exceptions.CosmosHttpResponseError` when `error.status_code in (401, 403)`
* **Exit Code 3 (Connection / Resource Not Found)**:
  * `azure.cosmos.exceptions.CosmosResourceNotFoundError` (HTTP 404, database/container not found)
  * `azure.core.exceptions.ServiceRequestError` (connection refused, DNS failure)
  * `azure.cosmos.exceptions.CosmosClientTimeoutError` / `azure.core.exceptions.ServiceRequestTimeoutError`

### 5. Cross-Partition Detection & Partition Key Range Signals

* **Problem**: The initial heuristic evaluated `len(headers_list) > 1`, which produced false positives on single-partition queries with multiple result pages.
* **Empirical Findings (Emulator Verification)**:
  * Azure Cosmos DB returns `HttpHeaders.PartitionKeyRangeID` (`x-ms-documentdb-partitionkeyrangeid`) in each response header dictionary.
  * In single-partition multi-page queries, every page returns the same partition key range ID (e.g., `['0', '0', '0']`), yielding 1 distinct ID.
  * In cross-partition fan-out queries across multiple physical partitions (e.g., container provisioned with > 10,000 RU/s across `AZURE_COSMOS_EMULATOR_PARTITION_COUNT=3`), responses arrive with distinct partition key range IDs (e.g., `['0', '1']`).
* **Contract**:
  1. If `query_def.partition_key` is set, `is_cross_partition` is strictly `False`.
  2. Otherwise, `is_cross_partition` evaluates to `len(distinct_pkr_ids) > 1` based on `HttpHeaders.PartitionKeyRangeID`.

### 6. Linux Emulator Image Selection (`vnext-preview` vs `2.14.28`)

* **Empirical Evaluation of `vnext-preview`** (`mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview`):
  * Architecture is built on PostgreSQL + `pgcosmos` extension with a Rust gateway.
  * Protocol: Listens on HTTP by default (`http://0.0.0.0:8081`). Attempting HTTPS connections triggers `[SSL] record layer failure (_ssl.c:1010)`. This violates QueryLens HTTPS-only security invariant.
  * Partitioning: Ignores `AZURE_COSMOS_EMULATOR_PARTITION_COUNT` and only exposes single partition key range `0`.
  * Index Metrics: Emits `{}` instead of the standard Base64-encoded JSON index utilization payload.
* **Selection of Pinned Tag `2.14.28`** (`mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:2.14.28`):
  * Corresponds to `latest` digest `sha256:9a4f69121f20c1d6502db84625c71ebb441ab61b01880a7b2d3d8031c6dac429`.
  * Supports native HTTPS via self-signed cert (`_explorer/emulator.pem`).
  * Emits standard Base64-encoded index utilization and full semicolon-delimited query metrics.
  * Supports physical partition partitioning (`AZURE_COSMOS_EMULATOR_PARTITION_COUNT=3`).
* **Decision**: Pin both `docker-compose.yml` and `.github/workflows/ci.yml` strictly to `mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:2.14.28` rather than floating `:latest`.

### Positive Consequences

* Clean, standards-based integration using official SDK public extensibility points (`response_hook`).
* Zero memory pressure from large result sets.
* Robust header parsing resilient to variations in metric header whitespace or missing optional metrics.
* Accurate exit codes aligned with enterprise security and DevOps requirements.
* True cross-partition detection without false positives on paginated single-partition queries.

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
