# Technical Research: Cosmos DB Query Cost Analyzer

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Feature Spec**: [spec.md](./spec.md)

This document records technical research, verified SDK APIs, architectural trade-offs, and best practices for the QueryLens Cosmos DB implementation.

---

## 1. Azure Cosmos DB Python SDK Verification

### Method & Parameter Contract

Cosmos DB queries are executed via [`ContainerProxy.query_items()`](https://learn.microsoft.com/en-us/python/api/azure-cosmos/azure.cosmos.container.containerproxy#azure-cosmos-container-containerproxy-query-items).

Verified parameter signatures against `azure-cosmos` 4.7.0+:

* `query: str` — SQL query string (e.g. `"SELECT * FROM c WHERE c.category = @cat"`).
* `parameters: list[dict[str, Any]] | None` — Parameter bindings in format `[{"name": "@cat", "value": "electronics"}]`.
* `partition_key: Any | None` — Explicit partition key value when scoping query to a single logical partition.
* `enable_cross_partition_query: bool | None` — Explicitly enabled (`True`) to allow multi-partition queries when `partition_key` is not provided.
* `populate_query_metrics: bool | None` — Must be `True` to trigger emission of `x-ms-documentdb-query-metrics` header.
* `populate_index_metrics: bool | None` — Must be `True` to trigger emission of `x-ms-cosmos-index-utilization` header.
* `max_item_count: int | None` — Page size limit per network roundtrip (used as a safety constraint).
* `response_hook: Callable[[dict[str, str], Any], None] | None` — Callback receiving raw response headers for each HTTP page response.

### Response Headers & Metrics Extraction

Query execution metrics are not embedded in item payloads; they are delivered via HTTP response headers captured through `response_hook` and `container.client_connection.last_response_headers`:

1. **Request Charge (`x-ms-request-charge`)**:
   * Header value: Decimal/Float as string (e.g., `"14.28"`).
   * Represents total Request Units (RUs) consumed by the page request.

2. **Query Metrics Header (`x-ms-documentdb-query-metrics`)**:
   * Semicolon-delimited key-value string:

     ```text
     totalExecutionTimeInMs=0.42;queryCompileTimeInMs=0.08;queryLogicalPlanBuildTimeInMs=0.05;queryPhysicalPlanBuildTimeInMs=0.06;queryOptimizationTimeInMs=0.01;queryEngineTimesInMs=0.22;systemFunctionExecutionTimeInMs=0.00;userFunctionExecutionTimeInMs=0.00;retrievedDocumentCount=1500;retrievedDocumentSizeInBytes=3024000;outputDocumentCount=3;outputDocumentSizeInBytes=450;writeOutputTimeInMs=0.01;indexUtilizationRatio=0.02
     ```

   * Key extracted fields:
     * `retrievedDocumentCount`: Integer count of documents scanned/loaded by storage engine.
     * `outputDocumentCount`: Integer count of documents matching predicates and returned.
     * `totalExecutionTimeInMs`: Engine runtime in milliseconds.

3. **Index Utilization Header (`x-ms-cosmos-index-utilization`)**:
   * Header value: Base64-encoded JSON UTF-8 string.
   * Decoded JSON schema:

     ```json
     {
       "UtilizedSingleIndexes": [{"FilterExpression": "c.category = 'electronics'", "IndexSpec": "/category/?"}],
       "PotentialSingleIndexes": [{"FilterExpression": "c.status = 'active'", "IndexSpec": "/status/?"}],
       "UtilizedCompositeIndexes": [],
       "PotentialCompositeIndexes": [{"IndexSpecs": ["/category/?", "/timestamp/?"], "IndexedPaths": ["category", "timestamp"]}]
     }
     ```

4. **Cross-Partition Fan-Out Extraction**:
   * Cosmos queries without `partition_key` run across all physical partitions.
   * In multi-partition queries, the SDK aggregates headers or issues parallel sub-queries.
   * If `partition_key` is specified in the workload, `is_fanout = False`. If omitted, and the container has multiple physical partitions or diagnostics report multi-partition execution, `is_fanout = True`.

---

## 2. Authentication & Data Plane Security

### Microsoft Entra ID (Production & Remote Accounts)

* **Library**: `azure-identity` using `DefaultAzureCredential`.
* **RBAC Role**: Azure Cosmos DB Data Reader (built-in role ID `00000000-0000-0000-0000-000000000001`).
* **Connection**: `CosmosClient(url=settings.endpoint, credential=DefaultAzureCredential())`.
* **Zero Keys**: No master keys or resource tokens in code or configuration files.

### Local Emulator Key via Environment Variable

* To support offline development and CI integration tests against the Dockerized Cosmos DB Linux emulator (`https://localhost:8081`):
* The standard emulator master key (`C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==`) is accepted **only** when the endpoint URL resolves to `localhost` or `127.0.0.1` and is supplied via `QUERYLENS_COSMOS_KEY` environment variable.
* If a non-localhost endpoint is used with a static key, QueryLens refuses to start and mandates Entra ID authentication.

### Payload Discard & Zero-Persistence Guarantee

* Results are iterated through pagination:

  ```python
  for page in query_iterable.by_page():
      # Consume items to force iteration, but discard immediately
      for _ in page:
          pass
  ```

* Item dictionary objects are never appended to arrays, never assigned to model fields, and never passed to loggers.

---

## 3. RU Budget Guard & Safe Execution

* **Mechanism**: A running tally `cumulative_ru: float` tracks the sum of `x-ms-request-charge` across all executed queries.
* **Evaluation**: Evaluated after every query page. If `cumulative_ru >= budget`:
  * Query execution loop breaks immediately.
  * Remaining workload queries are marked with `status="skipped"`.
  * The runner raises or flags a `BudgetExceededError`.
  * Partial results gathered up to that point are passed to the reporter.
  * The CLI returns exit code `2`.

---

## 4. Rule Engine Architecture & Thresholds

### Function-Based Registry Design

* No heavy plugin framework, reflection, or subclass hierarchies.
* Each rule is a pure function:

  ```python
  RuleFunc = Callable[[QueryCost, RuleSettings], list[Finding]]
  ```

* Registered in an in-memory sequence:

  ```python
  RULE_REGISTRY: list[RuleFunc] = [
      rule_high_ru_cost,
      rule_cross_partition_fanout,
      rule_scan_to_return_gap,
  ]
  ```

### Configurable Thresholds via `pydantic-settings`

Configured via `QUERYLENS_*` environment variables or CLI flags:

* High RU:
  * Warning: `cost.request_charge > high_ru_warning` (default: 50.0 RUs)
  * Critical: `cost.request_charge > high_ru_critical` (default: 200.0 RUs)
* Scan Gap:
  * Warning: `scanned / max(returned, 1) > scan_gap_ratio_warning` (default: 10.0x)
  * Critical: `scanned / max(returned, 1) > scan_gap_ratio_critical` (default: 100.0x)
  * Unindexed Miss: `scanned >= 1000 and returned == 0` (Critical)
* Cross-Partition Fan-Out:
  * Warning if `is_cross_partition is True`

---

## 5. Workload Ingestion & Safe Parsing

* Workload files are parsed using `yaml.safe_load(stream)` (never `yaml.load`).
* Parsed dictionary is validated through `WorkloadSchema` Pydantic v2 model.
* Any malformed syntax or schema deviation yields human-friendly validation error messages and exits with code `1`.

---

## 6. Testing Strategy & CI Integration

### Test Categories

* **Unit Tests (`tests/unit/`)**:
  * Pydantic model validation.
  * Header string parsing (`x-ms-documentdb-query-metrics` and base64 index metrics).
  * Rule evaluation with mocked `QueryCost` instances.
* **Property-Based Tests (`hypothesis`)**:
  * Generate random `QueryCost` values (negative RUs, huge scan gaps, zero returned, random floats).
  * Assert rule invariants: no unhandled exceptions, severity monotonicity, valid evidence keys.
* **Snapshot Tests (`syrupy`)**:
  * Validate terminal table formatting and JSON output schemas against known regression fixtures.
* **Integration Tests (`tests/integration/`)**:
  * Run against Cosmos DB Linux emulator in Docker container.
  * Creates test container, populates 100 documents, runs actual queries, validates RU metric capture and index header decoding.

### CI Workflow

* GitHub Actions with pinned commit SHAs.
* Steps:
  1. `ruff check --select D,DOC,S` & `ruff format --check`
  2. `pyrefly check`
  3. `pytest --cov=querylens --cov-fail-under=85`
  4. `pip-audit`
  5. CodeQL & Gitleaks
  6. Emulator integration job running Dockerized emulator on Ubuntu runner.
