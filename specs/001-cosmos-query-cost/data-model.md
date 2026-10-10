# Data Models: Cosmos DB Query Cost Analyzer

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Feature Spec**: [spec.md](./spec.md)

This document formalizes the Pydantic v2 domain models, schema constraints, and entity relationships for QueryLens.

---

## 1. Domain Entities & Schemas

### Severity Enum
```python
from enum import StrEnum


class Severity(StrEnum):
    INFO = "INFO"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def level(self) -> int:
        """Numeric rank for threshold comparisons (INFO=1, MEDIUM=2, HIGH=3, CRITICAL=4)."""
        ranks = {"INFO": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        return ranks[self.value]

    def __ge__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.level >= other.level
```

---

### Workload Ingestion Models (`model.py`)

#### `QueryParameter`
Represents an individual SQL query parameter binding.
* `name: str` — Parameter name (e.g., `"@category"`). Must start with `@`.
* `value: Any` — Bound parameter literal value (string, integer, float, boolean, or null).

#### `QueryDefinition`
Represents an individual query statement in a workload.
* `id: str` — Unique identifier or descriptive label for the query within the workload.
* `query: str` — SQL query statement (e.g., `"SELECT * FROM c WHERE c.active = true"`).
* `parameters: list[QueryParameter]` — Optional list of parameter bindings (defaults to empty).
* `partition_key: str | int | float | bool | list[str | int | float | bool] | None` — Optional partition key value.
  * **Validation Rules**:
    * Accepts single primitive scalar (`str`, `int`, `float`, `bool`).
    * If a list is provided, its length MUST be between 1 and 3 (`min_length=1, max_length=3`).
    * All items within the list MUST be primitive scalars.
    * Empty lists (`[]`), nested lists, and null (`None`) values within or as the list are strictly rejected with a validation error resulting in exit code 1.

#### `Workload`
The root specification model parsed from the YAML workload file.
* `version: str` — Workload format version (default: `"1"`).
* `database: str | None` — Target Cosmos DB database name (can be overridden via CLI).
* `container: str | None` — Target Cosmos DB container name (can be overridden via CLI).
* `ru_budget: float | None` — Optional workload-level cumulative RU limit.
* `queries: list[QueryDefinition]` — Ordered collection of queries to execute. Must contain at least 1 query.

---

### Execution & Cost Models (`model.py`)

#### `IndexUtilization`
Structured representation of index utilization extracted from `x-ms-cosmos-index-utilization`.
* `utilized_single: list[dict[str, Any]]` — Index paths successfully used.
* `potential_single: list[dict[str, Any]]` — Recommended single indexes that would improve performance.
* `utilized_composite: list[dict[str, Any]]` — Composite index specifications utilized.
* `potential_composite: list[dict[str, Any]]` — Recommended composite indexes.

#### `QueryCost`
The core engine contract produced by database adapters.
* `query_id: str` — Identifier referencing `QueryDefinition.id`.
* `query_text: str` — The query string executed.
* `request_charge: float` — Total RUs consumed (must be `>= 0.0`).
* `latency_ms: float` — Execution latency in milliseconds (must be `>= 0.0`).
* `documents_scanned: int` — Total documents loaded from the storage engine (must be `>= 0`).
* `documents_returned: int` — Total documents returned to the client (must be `>= 0`).
* `is_cross_partition: bool` — Whether the query fanned out across multiple partitions.
* `is_partial: bool` — Whether query execution was terminated mid-stream by the RU budget guard (default: `False`).
* `index_metrics: IndexUtilization | None` — Decoded index utilization, if available.
* `error_message: str | None` — Error description if the individual query failed execution.

---

### Diagnostic Rule Models (`model.py`)

#### `Finding`
An individual performance issue detected on an executed query.
* `rule_id: str` — Unique rule code (e.g., `"QL001"`, `"QL002"`, `"QL003"`).
* `rule_name: str` — Human-readable rule title (e.g., `"High RU Cost"`, `"Cross-Partition Fan-Out"`, `"Scan-to-Return Gap"`).
* `severity: Severity` — Finding severity level (`INFO`, `WARNING`, `CRITICAL`).
* `summary: str` — Actionable explanation of why this query was flagged.
* `evidence: dict[str, Any]` — Quantitative proof metrics (e.g., `{"request_charge": 254.2, "threshold": 50.0}`).

#### `QueryResultSummary`
Combines an executed query's cost metrics with its diagnostic findings.
* `cost: QueryCost` — The raw execution metrics.
* `findings: list[Finding]` — Collection of diagnostic findings for this query.

#### `WorkloadRunSummary`
The aggregate report artifact produced by the CLI.
* `timestamp: str` — ISO 8601 execution timestamp.
* `database: str` — Target database name.
* `container: str` — Target container name.
* `total_queries: int` — Total queries defined in the workload.
* `completed_queries: int` — Number of queries executed before completion or abort.
* `total_ru_consumed: float` — Cumulative Request Units consumed across all executed queries.
* `ru_budget: float | None` — Configured RU budget limit, if any.
* `budget_exceeded: bool` — Boolean flag indicating whether execution was halted by budget guard.
* `results: list[QueryResultSummary]` — Queries ranked in descending order by `cost.request_charge`.

---

## 2. Configuration Settings Model (`config.py`)

Configured using `pydantic-settings` with `QUERYLENS_` prefix:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Target Connection
    endpoint: str = ""
    database: str = ""
    container: str = ""
    cosmos_key: str | None = None  # ONLY permitted for localhost/emulator

    # Execution & Safety
    ru_budget: float | None = None
    max_item_count: int = 100
    debug: bool = False
    fail_on: str | None = None  # None (off), 'critical', 'high', or 'medium'

    # Rule Thresholds
    high_ru_warning: float = 50.0
    high_ru_critical: float = 200.0
    scan_gap_ratio_warning: float = 10.0
    scan_gap_ratio_critical: float = 100.0
    scan_gap_absolute_threshold: int = 1000

    model_config = {"env_prefix": "QUERYLENS_"}
```
