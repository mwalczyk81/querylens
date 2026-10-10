# QueryLens 🔍

[![CI](https://github.com/mwalczyk81/querylens/actions/workflows/ci.yml/badge.svg)](https://github.com/mwalczyk81/querylens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

QueryLens is a fast, developer-friendly command-line profiler for **Azure Cosmos DB for NoSQL** query workloads. It captures Request Units (RUs), execution latencies, physical partition fan-out, and document scan-to-return ratios, ranks queries by cost, and flags anti-patterns with quantitative metric evidence.

---

## ✨ Features

- **Ranked Workload Profiling**: Executes a YAML workload of queries and ranks them descending by Request Units (RUs).
- **Automated Anti-Pattern Diagnostics**:
  - `QL001: High RU Cost` — Flags queries exceeding warning (50 RUs) or critical (200 RUs) thresholds.
  - `QL002: Cross-Partition Fan-Out` — Identifies un-partitioned queries fanning out across physical partitions.
  - `QL003: Scan-to-Return Gap` — Diagnoses queries scanning significantly more documents than returned (10x warning, 100x critical, or 1000+ scanned with 0 returned).
- **Zero-Impact & Payload Privacy Guarantee**:
  - **Read-Only**: Strictly enforces read-only query execution with passwordless Entra ID (`DefaultAzureCredential`).
  - **Zero Payload Persistence**: Result document payloads are immediately consumed and discarded during streaming iteration; document contents are never logged, cached, or written to disk.
  - **Per-Page Budget Guard**: Halts execution mid-query if cumulative RUs exceed `--ru-budget` to prevent billing surprises.
- **CI/CD Quality Gate**:
  - `--fail-on <severity>` exits with code `4` if performance regressions or anti-patterns exceed `critical`, `high`, or `medium` thresholds.
  - Strict machine-readable `--json` output conforming to JSON Schema.

---

## 🚀 Quickstart

### 1. Installation

```bash
# Using uv (recommended)
uv tool install querylens

# Or with pip
pip install querylens
```

### 2. Define a Workload (`workload.yaml`)

```yaml
version: "1"
database: "benchmark_db"
container: "orders"
ru_budget: 500.0

queries:
  - id: "point-read-by-pk"
    query: "SELECT * FROM c WHERE c.customerId = @customerId AND c.id = @id"
    partition_key: "cust-1001"
    parameters:
      - name: "@customerId"
        value: "cust-1001"
      - name: "@id"
        value: "ord-9021"

  - id: "fanout-status-scan"
    query: "SELECT * FROM c WHERE c.status = 'PENDING_REVIEW'"

  - id: "expensive-category-scan"
    query: "SELECT * FROM c WHERE c.totalAmount > 1000000"
```

### 3. Run QueryLens

```bash
# Interactive Rich terminal report (uses DefaultAzureCredential)
querylens run workload.yaml --endpoint https://myaccount.documents.azure.com:443/

# Machine-readable JSON output for automation
querylens run workload.yaml --endpoint https://myaccount.documents.azure.com:443/ --json

# CI/CD pull request gate: Fail pipeline if any HIGH or CRITICAL issues are detected
querylens run workload.yaml --endpoint https://myaccount.documents.azure.com:443/ --fail-on high
```

---

## 🚦 Exit Codes Contract

QueryLens enforces deterministic exit codes designed for automated CI/CD pipeline orchestration:

| Exit Code | Classification | Trigger Condition |
| :---: | :--- | :--- |
| **`0`** | **Success** | All queries executed successfully without budget exhaustion, and all findings are below `--fail-on` threshold. |
| **`1`** | **Validation / Usage Error** | Invalid YAML, missing arguments, or invalid partition key format (length not 1–3, nulls, nested lists). |
| **`2`** | **Budget Exceeded** | Cumulative Request Units exceeded `--ru-budget`. Execution aborted mid-query; partial results returned. |
| **`3`** | **Connection Error** | Network unreachable, DNS resolution error, or target database/container not found (HTTP 404). |
| **`4`** | **Diagnostic Gate Breached** | At least one diagnostic finding met or exceeded `--fail-on <severity>`. |
| **`5`** | **Authentication / Authorization Failure** | Invalid credentials, expired token, missing `Cosmos DB Built-in Data Reader` role, or HTTP 401/403. |

---

## 🛡️ Security & Privacy

QueryLens is built with security-first invariants:
1. **Entra ID Passwordless Authentication**: Prioritizes `DefaultAzureCredential`. Master key authentication is strictly restricted to the local Cosmos DB emulator (`localhost` / `127.0.0.1`).
2. **Least Privilege**: Only requires the Azure Cosmos DB built-in role `Cosmos DB Built-in Data Reader`.
3. **Payload Discard**: Iterates over query results using `for _ in page: pass`, dropping item bodies immediately. QueryLens extracts only metadata headers (`x-ms-request-charge`, `x-ms-documentdb-query-metrics`, `x-ms-cosmos-index-utilization`).

---

## 🧪 Local Development & Testing

```bash
# Clone the repository
git clone https://github.com/mwalczyk81/querylens.git
cd querylens

# Synchronize virtual environment with uv
uv sync

# Run full test suite with coverage gate (>= 85%)
uv run pytest --cov=querylens --cov-fail-under=85

# Run property tests with Hypothesis
uv run pytest tests/unit/test_rules_property.py

# Run linters and strict type checks
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
```

### Running with Docker Cosmos DB Emulator

```bash
# Start emulator
docker compose up -d cosmos-emulator

# Run integration tests against emulator
uv run pytest -m integration
```

---

## 📄 License

MIT © [Matt Walczyk](https://github.com/mwalczyk81)