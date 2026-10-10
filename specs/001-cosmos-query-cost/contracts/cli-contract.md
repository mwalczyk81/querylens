# CLI Contract: `querylens`

**Branch**: `001-cosmos-query-cost` | **Date**: 2026-10-10 | **Feature Spec**: [spec.md](../spec.md)

This document formalizes the CLI command options, arguments, exit codes, and output contracts for `querylens`.

---

## 1. Global Command Interface

```text
querylens [--debug] [--version] COMMAND [ARGS]...
```

### Global Options

* `--debug`: Enable verbose diagnostic logging and expose internal Python stack traces on errors. Defaults to `False`.
* `--version`: Show version and exit.
* `--help`: Show help message and exit.

---

## 2. Command: `querylens run`

Profiles and analyzes a workload of Cosmos DB queries.

### Usage

```text
querylens run [OPTIONS] WORKLOAD_FILE
```

### Arguments

* `WORKLOAD_FILE` *(required)*: Path to the YAML workload file containing queries to execute.

### Options

* `-e, --endpoint TEXT`: Azure Cosmos DB account endpoint URL (e.g. `https://myaccount.documents.azure.com:443/`). Defaults to `QUERYLENS_ENDPOINT` env var.
* `-d, --database TEXT`: Target Cosmos DB database name. Defaults to `QUERYLENS_DATABASE` env var or workload YAML `database`.
* `-c, --container TEXT`: Target Cosmos DB container name. Defaults to `QUERYLENS_CONTAINER` env var or workload YAML `container`.
* `-b, --ru-budget FLOAT`: Maximum cumulative Request Units allowed for the run before execution halts. Overrides workload `ru_budget`.
* `--json`: Emit complete structured machine-readable JSON to `stdout` instead of the formatted terminal table.
* `--max-item-count INT`: Query pagination batch size limit (default: 100).
* `--high-ru-warn FLOAT`: Threshold for high RU warning (default: 50.0).
* `--high-ru-crit FLOAT`: Threshold for high RU critical finding (default: 200.0).
* `--scan-gap-warn FLOAT`: Ratio threshold of documents scanned to returned for warning (default: 10.0).
* `--scan-gap-crit FLOAT`: Ratio threshold of documents scanned to returned for critical finding (default: 100.0).
* `--fail-on [critical|high|medium]`: Exit with code `4` if at least one finding at or above the given severity threshold is detected across executed queries (default: off).

---

## 3. Exit Codes Contract

QueryLens enforces deterministic exit codes:

| Exit Code | Meaning | Description |
| :--- | :--- | :--- |
| `0` | **Success** | All workload queries executed successfully without budget exhaustion (and no findings at/above `--fail-on` threshold, or `--fail-on` is off). |
| `1` | **Validation / Usage Error** | Malformed workload YAML, invalid parameters, invalid partition key length/type, missing required arguments, or unparseable inputs. |
| `2` | **Budget Exceeded** | Cumulative RU consumption met or exceeded the configured `--ru-budget`. Execution aborted mid-workload; partial results reported. |
| `3` | **Connection Error** | Network unreachable, host resolution failure, or target database/container not found. |
| `4` | **Diagnostic Threshold Breached** | At least one finding at or above the severity specified by `--fail-on` was detected. |
| `5` | **Authentication / AuthZ Failure** | Invalid credentials, expired token, missing Cosmos DB Data Reader role, or HTTP 401/403 responses. |

---

## 4. Terminal Output Format (Default)

When `--json` is omitted, `querylens` outputs a Rich terminal display containing:

1. **Header Panel**: Target database, container, endpoint, total queries, cumulative RU spend, and budget status.
2. **Ranked Cost Table**:
   * `Query ID`: Identifier from workload.
   * `RU Cost`: Request Units consumed (highlighted in red/yellow for high cost).
   * `Latency`: Roundtrip execution time in milliseconds.
   * `Scanned`: Documents scanned count.
   * `Returned`: Documents returned count.
   * `Fan-Out`: `Yes` or `No`.
   * `Findings`: List of flagged rule codes with color-coded severity (`[CRIT]`, `[WARN]`, `[INFO]`).
3. **Summary & Remediations Panel**: Detailed breakdown of evidence for each flagged query.

---

## 5. Machine Output Contract (`--json`)

When `--json` is specified:

* Output is written to `stdout`.
* Validates against [`run-output-schema.json`](./run-output-schema.json).
* Informational logs are redirected to `stderr` or suppressed.
* Exit codes strictly adhere to Section 3.
