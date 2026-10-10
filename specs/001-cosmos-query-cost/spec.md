# Feature Specification: Cosmos DB Query Cost Analyzer

**Feature Branch**: `001-cosmos-query-cost`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Build querylens, a CLI that runs a list of queries against Azure Cosmos DB for NoSQL and shows which ones cost the most request units (RUs) and why."

## Clarifications

### Session 2026-10-10

- Q: Should the CLI provide an option to exit with a non-zero exit code when query inefficiencies are detected? (FR-012) → A: Support `--fail-on <severity>` accepting `critical`, `high`, or `medium` (default off). Exit code 4 indicates at least one finding at or above the specified severity threshold.
- Q: At what granularity should the cumulative RU budget be evaluated during workload execution? (FR-008) → A: Option B (Per-page evaluation: Check cumulative RUs after every page response and halt immediately mid-query, recording partial metrics and an "aborted mid-query" status).
- Q: How should hierarchical partition keys be validated in the workload file? (FR-001) → A: `partition_key` accepts either a single scalar value (string, number, boolean) or a list of 1 to 3 scalar values. Empty lists, nested lists, and null values are strictly rejected with a descriptive validation error and exit code 1.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Profile and Rank Query Workload by Cost (Priority: P1)

A backend engineer who owns a service backed by Azure Cosmos DB for NoSQL wants to profile a batch of application queries against their container. The engineer provides a YAML workload file defining query statements, optional SQL parameters, and optional partition keys. The CLI executes each query in read-only mode, records the Request Unit (RU) consumption, and displays a clean terminal table ranked from highest to lowest RU cost. The engineer can also supply `--json` to receive structured machine-readable metrics for automated scripts or dashboards.

**Why this priority**: Ranking queries by RU charge is the foundational value proposition of QueryLens. Without the ability to run queries, capture RU charges, and present a ranked cost summary, no diagnostic value can be delivered.

**Independent Test**: Can be tested independently by supplying a workload YAML file with 3 sample queries against a Cosmos DB instance. The command completes and outputs a table listing all 3 queries sorted by RU charge in descending order, and with `--json` outputs a valid JSON array of cost records.

**Acceptance Scenarios**:

1. **Given** a valid workload YAML file containing multiple SQL queries and valid connection configuration, **When** the engineer executes the profile command, **Then** QueryLens executes each query in read-only mode and outputs a terminal table sorted descending by RU cost with query identifier/text, RU charge, and execution latency.
2. **Given** queries with parameterized values and specified partition keys in the workload file, **When** executed, **Then** QueryLens passes the parameters and targets the specified partition key during execution.
3. **Given** the `--json` flag on the command line, **When** execution completes, **Then** QueryLens outputs structured JSON containing complete per-query metrics to standard output.
4. **Given** a valid workload run, **When** query execution completes, **Then** 0% of the retrieved query result documents are saved, written to disk, or displayed in output.

---

### User Story 2 - Diagnose Query Inefficiencies with Metric Evidence (Priority: P2)

The backend engineer needs to understand *why* particular queries consume excessive RUs so they can remediate them. QueryLens evaluates each executed query against built-in diagnostic rules and flags issues with an assigned severity (e.g., Medium, High, Critical) accompanied by concrete metric evidence:

- **Cross-partition fan-out**: Queries executing without a single partition key that fan out across physical/logical partitions.
- **Excessive document scan gap**: Queries where the count of documents scanned significantly exceeds the count of documents returned (indicating missing or underutilized indexing).
- **High RU consumption**: Queries whose total RU cost exceeds normal operating thresholds.
- **Index metrics**: Index utilization evidence indicating whether indexes were utilized, composite indexes were recommended by the engine, or full scans occurred.

**Why this priority**: Knowing that a query is expensive without knowing the underlying reason leaves engineers guessing. Flagging root-cause evidence (scanned vs returned, fan-out, indexing) provides the necessary context to take immediate action.

**Independent Test**: Can be tested independently by running queries with known anti-patterns (e.g., an unindexed filter, a query missing a partition key) and verifying that the output table and JSON results contain explicit diagnostic findings, severity levels, and metric evidence.

**Acceptance Scenarios**:

1. **Given** a query executed without a partition key that spans multiple partitions, **When** analyzed, **Then** QueryLens flags the query with a cross-partition fan-out warning and includes partition fan-out metric evidence.
2. **Given** a query where 5,000 documents are scanned but only 5 are returned, **When** analyzed, **Then** QueryLens flags an excessive scan gap with severity and cites the exact documents scanned (5,000) versus returned (5).
3. **Given** a query exceeding the high RU threshold (e.g. > 100 RUs), **When** analyzed, **Then** QueryLens flags the query with high RU severity and includes the total RU charge.
4. **Given** a query where index metrics are returned by the database engine, **When** analyzed, **Then** QueryLens reports index utilization evidence (e.g., utilized indexes, potential index gaps).
5. **Given** a workload resulting in diagnostic findings, **When** executed with `--fail-on <severity>` (accepting `critical`, `high`, or `medium`), **Then** QueryLens completes reporting and exits with exit code 4 if at least one finding has a severity at or above the specified threshold.

---

### User Story 3 - Safe Execution with Configurable RU Budget Guards (Priority: P3)

The backend engineer runs queries against a shared pre-production or production container with provisioned throughput limits. To avoid exhausting provisioned throughput or starving production services, the engineer configures a cumulative RU budget limit (e.g., `--ru-budget 2000` or defined in the workload file). As queries execute sequentially, QueryLens tracks cumulative RU spend. If the budget is reached or exceeded, QueryLens immediately stops executing remaining queries, displays the partial analysis for queries executed so far with a clear budget-exceeded alert, and exits with a dedicated non-zero exit code.

**Why this priority**: Operational safety is a core project principle. A tool diagnosing cost must never cause an accidental outage or unexpected cloud spend spike.

**Independent Test**: Can be tested independently by configuring a 100 RU budget and submitting a workload of 5 queries where the first two consume 120 RUs combined. QueryLens halts after the second query, does not dispatch queries 3-5, reports the first two queries, and exits with the budget-exceeded exit code.

**Acceptance Scenarios**:

1. **Given** a configured RU budget of 500 RUs and a query whose paginated retrieval causes cumulative spend to reach or exceed 500 RUs, **When** that page response completes, **Then** QueryLens immediately halts further page retrieval and stops subsequent queries, records the partial metrics gathered for the active query, and marks it as aborted mid-query.
2. **Given** an aborted execution due to budget limit, **When** reporting results, **Then** QueryLens renders the ranked table and JSON for all queries and pages completed prior to the abort, marks any partial query clearly, outputs a prominent budget-exceeded warning, and exits with exit code 2.
3. **Given** no budget limit specified, **When** executed, **Then** QueryLens runs all queries in the workload to completion.

---

### Edge Cases

- **Workload file syntax or schema error**: If the YAML workload file is malformed, missing required fields (e.g., no queries defined), or has invalid types, QueryLens rejects the file with a descriptive validation error before attempting any database connection and exits with a distinct exit code.
- **Target database or container not found**: If the configured database or container does not exist on the target account, QueryLens halts before executing queries with a clear connection/resource error and distinct exit code.
- **Authentication failure**: If Entra ID credentials or environment tokens are invalid or expired, QueryLens reports an authentication error without displaying internal stack traces unless `--debug` is specified.
- **Individual query syntax failure**: If a single query in the workload has invalid SQL syntax while others are valid, QueryLens records the query execution error, assigns an error diagnostic, and continues profiling remaining queries in the workload (unless an abort condition is met).
- **Throttling / Rate-limiting (HTTP 429)**: If the target Cosmos DB container responds with rate limiting (429 RequestRateTooLarge), QueryLens retries according to standard backoff policies. If retries are exhausted, the query is marked as throttled with captured partial metrics and the error is clearly reported.
- **Zero documents returned with high scan count**: When an unindexed query returns 0 documents after scanning large numbers of documents, QueryLens flags the scan gap as Critical severity with specific evidence (scanned > 0, returned == 0).
- **Single query exceeds entire budget**: If the first query in the workload immediately exceeds the entire configured RU budget, QueryLens records the query's metrics, flags the budget overrun, halts further queries, and exits with the budget-exceeded exit code.
- **Empty workload file**: If the workload YAML file contains an empty query list, QueryLens exits gracefully with a message indicating zero queries were provided.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a workload file in YAML format specifying an ordered list of queries, optional SQL parameters (name and value mappings), and an optional partition key value (either a single scalar string, number, or boolean, or a list of 1 to 3 scalar values for hierarchical partition keys). The system MUST validate that any list provided for `partition_key` has a length between 1 and 3 items and contains only primitive scalar values; empty lists, nested lists, and null values MUST be rejected with a clear validation error message and exit code 1.
- **FR-002**: System MUST authenticate against Azure Cosmos DB for NoSQL using Microsoft Entra ID or environment credentials in a strictly read-only execution mode.
- **FR-003**: System MUST execute queries sequentially and record for each query: total Request Unit (RU) charge, execution latency in milliseconds, documents scanned count, documents returned count, partition execution scope (single partition vs cross-partition fan-out), and index utilization metrics.
- **FR-004**: System MUST rank all executed queries in descending order by total Request Unit (RU) charge in the terminal table output.
- **FR-005**: System MUST provide a global `--json` command-line option that outputs all execution metrics, rankings, and diagnostic findings as valid, structured JSON to standard output.
- **FR-006**: System MUST evaluate diagnostic rules for each executed query and assign a severity level (Info, Medium, High, Critical) along with supporting metric evidence for:
  - High RU cost (total RU consumption exceeding configured or default threshold).
  - Cross-partition fan-out (query executing across multiple physical/logical partitions).
  - Disproportionate scan-to-return gap (count of documents scanned substantially exceeding count of documents returned).
- **FR-007**: System MUST support a configurable cumulative RU budget limit, passable via CLI option (e.g., `--ru-budget <N>`) or workload configuration.
- **FR-008**: System MUST evaluate cumulative RU consumption after each paginated response and immediately halt further execution (even mid-query) when the configured RU budget is reached or exceeded, recording partial metrics and marking the active query as aborted mid-execution.
- **FR-009**: System MUST display partial results for all completed queries and return a distinct exit code when execution is halted due to budget overrun.
- **FR-010**: System MUST NOT execute any write, update, delete, or administrative modifying operations against the target database under any circumstance.
- **FR-011**: System MUST NOT store, cache, log, or persist result item document payloads to disk, logs, or terminal output; only cost and execution metrics may be captured and displayed.
- **FR-012**: System MUST terminate with distinct, documented exit codes:
  - `0`: Success (all queries executed without budget breach; or findings detected when `--fail-on` is not set or findings are below the specified severity threshold).
  - `1`: Validation or configuration error (invalid workload YAML, invalid partition key length/type, missing arguments).
  - `2`: Cumulative RU budget exceeded (execution halted before completing all queries).
  - `3`: Database connection failure (network unreachable, endpoint resolution failure, target database or container not found).
  - `4`: Diagnostic findings detected at or above the severity threshold specified via `--fail-on <severity>` (accepting `critical`, `high`, or `medium`; default off).
  - `5`: Authentication or authorization failure (invalid credentials, missing Cosmos DB Data Reader role, HTTP 401 Unauthorized, HTTP 403 Forbidden).
- **FR-013**: System MUST sanitize error messages on standard error and suppress raw execution stack traces unless the `--debug` flag is explicitly passed.

### Key Entities *(include if feature involves data)*

- **Workload Definition**: The top-level input artifact; defines workload metadata, target database and container identifiers, optional run settings (e.g. default RU budget), and an ordered collection of Query Items.
- **Query Item**: An individual query specification within the workload; contains a unique query identifier or label, SQL query text, optional parameter dictionary, and an optional partition key value (either a single scalar string, number, or boolean, or a list of 1 to 3 scalars; rejects nested lists, nulls, and empty lists).
- **Query Execution Cost**: The recorded runtime cost profile for a single query execution; contains total RU charge, execution latency, document scan count, document return count, partition fan-out flag/count, index utilization details, and an `is_partial` flag indicating whether execution was aborted mid-query due to budget limits.
- **Diagnostic Finding**: A specific detected performance problem on an executed query; contains rule identifier, issue type (High RU, Cross-Partition Fan-out, Scan-to-Return Gap), assigned severity (Info, Warning, Critical), human-readable explanation, and quantitative metric evidence values.
- **Workload Run Summary**: The aggregated output artifact; contains execution timestamp, target database/container info, total queries attempted/completed, total cumulative RUs spent, budget status (within budget or exceeded), and the ranked list of queries with their associated costs and diagnostic findings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Engineers can profile a workload of queries and receive ranked RU cost results in terminal table format via a single CLI invocation.
- **SC-002**: 100% of queries exhibiting cross-partition fan-out, excessive scan-to-return ratios, or high RU charges are flagged with their exact quantitative metric evidence in both terminal and JSON outputs.
- **SC-003**: In 100% of test runs where the cumulative RU charge exceeds the specified budget, execution halts immediately with zero additional queries dispatched.
- **SC-004**: 0% of database result document payloads or sensitive payload values are stored in memory after metric extraction, logged, or written to disk.
- **SC-005**: 100% of `--json` invocations produce valid JSON adhering to a defined schema, enabling direct parsing in CI/CD pipelines and downstream scripts.
- **SC-006**: Terminal summary and JSON output are produced within 2 seconds of the final query completing execution.

## Assumptions

- **Target Container Exists**: The target database and container already exist and contain sample or production-like data suitable for performance profiling.
- **Sequential Execution**: Queries within a workload are executed sequentially to ensure accurate per-query latency and cumulative RU tracking against the budget limit.
- **Default Severity Thresholds**: Reasonable default thresholds are applied for diagnostic rules when not explicitly configured (e.g., High RU: Warning > 50 RUs, Critical > 200 RUs; Scan-to-Return Ratio: Warning > 10x, Critical > 100x or scanned > 1,000 with 0 returned; Cross-Partition: any multi-partition execution without partition key is Warning).
- **Read-Only Enforced**: Read-only behavior is enforced at the driver/request options level (e.g., read-only queries with no transactional writes) and validated against query syntax.
- **Workload Container Specification**: The workload file may define a default database and container, which can be overridden via CLI arguments (`--database`, `--container`).
- **Individual Query Errors Do Not Crash Workload**: If an individual query fails due to bad SQL syntax, QueryLens records the error as a finding for that query and proceeds with the rest of the workload unless the RU budget or network connection is severed.

## Out of Scope

- AI-generated query optimization suggestions or automated LLM prompt generation.
- Generation of Markdown, HTML, or PDF export reports.
- Ingestion of Azure Monitor / Diagnostic Log Streams or Log Analytics historical query logs.
- Hot partition skew detection across historical database traffic.
- Support for databases other than Azure Cosmos DB for NoSQL in this initial version.
- Web, desktop, or graphical user interface.
