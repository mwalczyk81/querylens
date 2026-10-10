# Quickstart & Validation Guide: Cosmos DB Query Cost Analyzer

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Feature Spec**: [spec.md](./spec.md)

This guide walks through setting up the local environment, launching the Azure Cosmos DB Linux emulator via Docker, and validating QueryLens end-to-end.

---

## 1. Prerequisites

* **Python**: 3.12 or newer.
* **uv**: Modern Python package and project manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`).
* **Docker & Docker Compose**: For running the local Cosmos DB Linux emulator.

---

## 2. Environment Setup

Install project dependencies in a local virtual environment:

```powershell
# Clone and enter directory
cd querylens

# Synchronize dependencies with uv
uv sync --all-extras

# Activate virtual environment
.venv\Scripts\activate
```

---

## 3. Local Cosmos DB Emulator Setup

Start the Azure Cosmos DB Linux emulator via Docker Compose:

```powershell
docker compose up -d cosmos-emulator
```

The emulator will become available at `https://localhost:8081/`.

Set the required environment variables:

```powershell
$env:QUERYLENS_ENDPOINT = "https://localhost:8081/"
$env:QUERYLENS_COSMOS_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
$env:QUERYLENS_DATABASE = "benchmark_db"
$env:QUERYLENS_CONTAINER = "orders"
```

Initialize test seed data (if running manual validation):
```powershell
uv run python -m tests.scripts.seed_emulator
```

---

## 4. Sample Workload File

Create a sample workload file named `workload.yaml`:

```yaml
version: "1"
database: "benchmark_db"
container: "orders"
ru_budget: 500

queries:
  - id: "point-read-by-pk"
    query: "SELECT * FROM c WHERE c.customerId = @customerId AND c.id = @id"
    partition_key: "cust-1001"
    parameters:
      - name: "@customerId"
        value: "cust-1001"
      - name: "@id"
        value: "ord-9021"

  - id: "fanout-unindexed-status"
    query: "SELECT * FROM c WHERE c.nonIndexedStatus = @status"
    parameters:
      - name: "@status"
        value: "PENDING_REVIEW"

  - id: "scan-gap-filter"
    query: "SELECT * FROM c WHERE c.totalAmount > @amount"
    parameters:
      - name: "@amount"
        value: 1000000
```

---

## 5. Runnable Validation Scenarios

### Scenario A: Standard Terminal Output (Ranked Table)

Execute QueryLens against the workload:

```powershell
uv run querylens run workload.yaml
```

**Expected Outcome**:
* A Rich terminal panel appears with execution summary.
* A ranked table displays all queries sorted descending by RU charge.
* `fanout-unindexed-status` is flagged with `[WARN] Cross-Partition Fan-Out` and `[CRIT] High RU Cost`.
* `scan-gap-filter` is flagged with `[WARN] Scan-to-Return Gap` showing high scanned count vs 0 returned.
* Process exits with code `0`.

---

### Scenario B: Machine Output (`--json`)

Execute with `--json` flag:

```powershell
uv run querylens run workload.yaml --json > output.json
```

**Expected Outcome**:
* `output.json` contains valid JSON adhering to [`run-output-schema.json`](./contracts/run-output-schema.json).
* Per-query metrics contain exact `request_charge`, `latency_ms`, `documents_scanned`, and `documents_returned`.
* Findings array contains `rule_id`, `severity`, and quantitative `evidence`.

---

### Scenario C: RU Budget Overrun Enforcement

Run with an artificially low RU budget to trigger safety abort:

```powershell
uv run querylens run workload.yaml --ru-budget 15.0
```

**Expected Outcome**:
* Execution halts after the first or second query.
* Terminal output displays a warning: `[WARNING] Execution halted: Cumulative RU budget (15.0 RUs) exceeded`.
* Partial results for completed queries are shown.
* Process exits with exit code `2`.

---

## 6. Running Tests & Quality Gates

Run full test suite and verify coverage:

```powershell
# Unit & Property-based tests
uv run pytest tests/unit --cov=src/querylens --cov-report=term-missing --cov-fail-under=85

# Linting and formatting checks
uv run ruff check
uv run ruff format --check

# Strict type checking
uv run pyrefly check
```
