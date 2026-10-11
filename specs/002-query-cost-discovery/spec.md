# Feature Specification: Cosmos DB Query Cost Discovery (`querylens discover`)

**Feature Branch**: `002-query-cost-discovery`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Query cost discovery from Cosmos DB diagnostic logs (\"querylens discover\")"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover High-Cost Query Shapes from Log Analytics (Priority: P1)

A platform engineer or backend developer maintaining a high-scale service backed by Azure Cosmos DB for NoSQL has hundreds of code repositories and LINQ-generated queries. Because queries are generated dynamically at runtime across distributed services, the team cannot manually enumerate queries into a static workload file. The engineer executes `querylens discover` pointing to their Azure Log Analytics workspace. QueryLens queries diagnostic logs over a specified time window, performs server-side aggregation in KQL, groups query executions by target database, container, and normalized query shape, and displays a ranked summary table showing which query patterns generate the highest cumulative Request Unit (RU) spend, their execution volume, average and maximum RU costs, and their share of total database consumption. The engineer can also supply `--json` to feed these metrics into automated reporting pipelines.

The summary reports overall workload metrics including total database RU consumption (the sum of all data plane requests in scope and window), total query-attributed RU consumption, and unattributed RU consumption (operations such as point reads, writes, administrative calls, or queries without runtime statistics that did not join to a query shape) along with its percentage share.

**Why this priority**: Discovering unknown high-cost query shapes from production diagnostic logs unlocks cost observability for teams that cannot construct pre-determined workload files. This delivers the primary business value of feature 002 as a viable standalone capability.

**Independent Test**: Can be tested independently by providing a target Log Analytics workspace ID and time window. The command queries Log Analytics via the Azure Monitor Query SDK, receives aggregated shape records, and outputs a ranked terminal table and JSON summary showing query shapes sorted by total RU consumption.

**Acceptance Scenarios**:

1. **Given** a valid workspace ID and active Entra ID credentials with `Log Analytics Reader` access, **When** the engineer runs `querylens discover`, **Then** QueryLens executes a server-side KQL aggregation over the default 24-hour window and renders a ranked Rich table of the top 20 query shapes sorted descending by total RU.
2. **Given** custom flags `--time-window 7d`, `--top 50`, and `--account my-cosmos-account`, **When** executed, **Then** QueryLens restricts analysis to the specified account and 7-day duration, returning up to 50 ranked shapes.
3. **Given** query executions across databases and containers, **When** grouped, **Then** QueryLens groups executions by the composite tuple `(database, container, query shape)`.
4. **Given** diagnostic logs where `shapesignature_s` is populated, **When** shapes are aggregated, **Then** QueryLens identifies query shapes using `shapesignature_s`.
5. **Given** diagnostic logs where `shapesignature_s` is missing or null, **When** shapes are aggregated, **Then** QueryLens identifies query shapes by a deterministic cryptographic hash of `querytext_s`.
6. **Given** the global `--json` flag, **When** execution completes, **Then** QueryLens outputs structured JSON conforming to the discovery JSON Schema to standard output with exit code 0.
7. **Given** query shapes with executions, **When** metrics are displayed, **Then** the output displays: executions count, total RU, average RU, max RU, share of total database RU (%), average rows returned, RU per returned row (or `n/a` when 0 rows returned), throttled (429) count where joinable, database name, container name, top 3 callers with their RU shares, and an obfuscated query text sample.
8. **Given** database operations in the time window, **When** reported, **Then** QueryLens computes and displays the unattributed RU summary (operations not joining to a query shape) and its percentage share of total database RU spend.
9. **Given** the `--print-kql` flag, **When** executed with valid CLI arguments, **Then** QueryLens validates inputs, prints the constructed KQL query to standard output, makes zero network calls, requires zero credentials, and exits 0.

---

### User Story 2 - Preflight Workspace Diagnostic Inspection (`--check`) (Priority: P2)

A developer or platform engineer onboarding a new Log Analytics workspace or troubleshooting missing metrics needs to verify that Cosmos DB diagnostic logs are actively streaming with necessary columns before running full discovery queries. The engineer runs `querylens discover --check`. QueryLens inspects the workspace for the target time window and emits a diagnostic health report detailing which categories exist (`DataPlaneRequests`, `QueryRuntimeStatistics`), category row counts, earliest and latest log timestamps, field population percentages (for `shapesignature_s`, `querytext_s`, `aadPrincipalId_g`, `aadPrincipalId_s`, `clientIpAddress_s`, `useragent_s`), and an authentication token type breakdown (`authTokenType_s`). Crucially, the check reports only quantitative counts, percentages, and timestamps—masking the workspace ID to its last 4 characters and omitting user query text, tenant identifiers, or literal values—making the output safe to share internally; contains only counts, percentages and timestamps.

**Why this priority**: Diagnostic log configurations frequently suffer from missing categories, partial column streaming, or misconfigured diagnostic settings. A safe preflight check prevents failed discovery runs and helps users rapidly verify their workspace configuration without sharing sensitive query data.

**Independent Test**: Can be tested independently by running `querylens discover --check` against a workspace. The command outputs a formatted table and JSON showing category presence, row counts, time ranges, and column population percentages with 0% data values exposed.

**Acceptance Scenarios**:

1. **Given** a workspace with active diagnostic streaming, **When** the engineer executes `querylens discover --check`, **Then** QueryLens reports category row counts, time boundaries, column population percentages, and auth token breakdown without emitting any sensitive column values.
2. **Given** preflight report output, **When** workspace identity is displayed, **Then** QueryLens masks the workspace ID to show only its last 4 characters (e.g. `...1234`).
3. **Given** a workspace where `QueryRuntimeStatistics` is not enabled in diagnostic settings, **When** checked, **Then** QueryLens explicitly reports `QueryRuntimeStatistics` as missing with 0 rows and warns the user that query-level diagnostics cannot be discovered.
4. **Given** the `--check` flag combined with `--json`, **When** executed, **Then** QueryLens outputs a structured preflight JSON object containing purely counts, percentages, and timestamps.

---

### User Story 3 - Caller Attribution & Sensitive Query Text Privacy (Priority: P3)

A platform engineer investigating an unexpected RU spike needs to determine which microservice or client application is responsible for an expensive query shape, while adhering to organizational data governance rules regarding query text exposure. QueryLens performs best-effort caller attribution: identifying up to the top 3 callers per query shape, each annotated with their individual RU share (%) within that shape, displaying the calling principal GUID (`aadPrincipalId_g`) when populated, falling back to client IP address (`clientIpAddress_s`), or omitted if blank. By default, QueryLens treats Microsoft-obfuscated query text as sensitive: query text is truncated in console tables, omitted entirely from JSON outputs, and never recorded in application debug logs. If the engineer explicitly passes `--show-text`, full obfuscated query text is displayed in the terminal and included in JSON output.

**Why this priority**: Knowing the responsible client accelerates remediation without compromising privacy. Enforcing opt-in query text exposure prevents unintended leakage of proprietary query structures into automated log pipelines or dashboards.

**Independent Test**: Can be tested independently by running `querylens discover` on logs containing principal IDs and verifying that the console displays up to 3 callers with RU shares without resolving external directory identities. Running with and without `--show-text` verifies that full text is truncated/omitted by default and included only upon explicit request.

**Acceptance Scenarios**:

1. **Given** diagnostic log records containing caller information, **When** reported, **Then** QueryLens attributes each shape to up to 3 top callers, each displaying their identifier (principal GUID or IP fallback) and their percentage share of that shape's total RU.
2. **Given** log records where `aadPrincipalId_g` is null but `clientIpAddress_s` is present, **When** reported, **Then** QueryLens falls back to displaying the raw client IP address with its RU share.
3. **Given** log records where both principal and IP are blank, **When** reported, **Then** caller attribution for that execution is omitted without error.
4. **Given** standard discovery execution without `--show-text`, **When** results are rendered, **Then** query text is truncated in console tables, omitted from `--json` results, and never logged to internal structlog loggers.
5. **Given** discovery execution with `--show-text`, **When** results are rendered, **Then** full obfuscated query text samples are displayed in the terminal and included in JSON output.
6. **Given** query text returned by Azure Monitor, **When** processed by QueryLens, **Then** QueryLens preserves the text as logged and NEVER attempts to reconstruct, guess, or deobfuscate parameter literals.

---

### Edge Cases

- **Empty workspace / Zero matching log rows**: If the Log Analytics workspace contains 0 records matching the `MICROSOFT.DOCUMENTDB` filter within the specified time window, QueryLens exits cleanly with exit code 0. When `--json` is set, `stdout` MUST contain a valid JSON document conforming to schema with `results: []` and 0 totals, and any informational messages MUST be directed to `stderr` to preserve machine readability.
- **Zero returned rows for query shape**: When a query shape returns a total of 0 documents across all executions (e.g., queries with non-matching filters), `ru_per_returned_row` is explicitly `null` to prevent division by zero, rendered as `n/a` in terminal tables.
- **QueryRuntimeStatistics category missing**: If `DataPlaneRequests` exists but `QueryRuntimeStatistics` is not enabled, QueryLens informs the user that request charges cannot be mapped to query text without runtime statistics and recommends enabling `QueryRuntimeStatistics` in Azure Diagnostic Settings.
- **Mapped column missing from log schema**: If Azure Log Analytics returns rows where an expected column (e.g., `shapesignature_s` or `useragent_s`) is absent from the result schema, QueryLens degrades gracefully by using fallbacks or null values rather than throwing exceptions.
- **Partial results from SDK**: If the Azure Monitor Query SDK returns a partial query status (e.g., due to Log Analytics query limits or memory caps), QueryLens renders the partial results, displays a warning indicating incomplete data, and notes the truncation.
- **Log Analytics query timeout / network failure**: If the remote query exceeds the timeout or the endpoint is unreachable, QueryLens reports an actionable connection error on `stderr` and exits with code 3 (matching ADR 0004).
- **Workspace shared with unrelated Azure services**: QueryLens strictly filters KQL queries by `ResourceProvider =~ "MICROSOFT.DOCUMENTDB"` to prevent interference or data leakage from other Azure services sharing the workspace.
- **Data retention truncation inferred from data**: If the earliest record timestamp returned in the query results is later than the requested time window start, QueryLens emits a warning noting that data older than the earliest available record timestamp is not represented. QueryLens infers this strictly from result data and MUST NOT add an Azure management SDK dependency.
- **Missing RBAC permissions**: If the Entra ID credentials lack `Log Analytics Reader` permissions on the workspace (HTTP 401/403), QueryLens displays a clear permission error and terminates immediately with exit code 5 (matching ADR 0004).
- **Injection attempts in input parameters**: If a user supplies injection characters or malformed strings for workspace ID or account filter, QueryLens rejects the inputs during CLI option parsing with exit code 1 before issuing any network requests.
- **Silent-Zero Guard (Zero attributed RU or absent key columns)**: If `DataPlaneRequests` records exist in the evaluation window but `attributed_total_ru` is 0, or if essential diagnostic columns (`requestCharge_s`, `activityId_g`, `querytext_s`) are entirely absent or unpopulated, QueryLens terminates with exit code 1, emitting an actionable error message directing the user to run `querylens discover --check` rather than rendering a misleading table of zeros.
- **Malformed caller dynamic structures**: If the Azure Monitor service returns unexpected dynamic structures for top callers (e.g. flat lists or nested pair arrays due to serialization differences, or caller RU exceeding shape total RU), the caller parser raises `InternalConsistencyError` to signal the contract mismatch cleanly to the user rather than silently dropping attribution data or producing corrupted metrics.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a `querylens discover` CLI command accepting:
  - `--workspace-id` / `-w` (or environment variable `QUERYLENS_WORKSPACE_ID`), strictly validated as a standard GUID (UUIDv4/RFC 4122 format).
  - Optional `--account` / `-a` filtering Cosmos DB account names, validated against a strict alphanumeric/hyphen pattern (`^[a-zA-Z0-9][-a-zA-Z0-9]{1,42}[a-zA-Z0-9]$`).
  - Optional `--time-window` / `-t` specifying the lookback duration (default `24h`), validated as a bounded positive duration (e.g. `1h`, `24h`, `7d`, `14d`). The time window MUST be passed to the SDK via its native query timespan parameter and MUST NOT be interpolated into the KQL query string.
  - Optional `--top` / `-n` specifying the number of query shapes to return (default 20, validated integer between 1 and 100).
  - Optional `--timeout` specifying the server query timeout in integer seconds (default 180, validated between 10 and 600).
  - Optional `--show-text` flag to expose full query text.
  - Optional `--check` flag to trigger preflight diagnostic inspection.
  - Optional `--print-kql` flag to build and print the generated KQL query to stdout without making network calls or requiring credentials.
- **FR-002**: System MUST authenticate against Azure Monitor Log Analytics exclusively using Microsoft Entra ID via `DefaultAzureCredential` in read-only mode, requiring the `Log Analytics Reader` Azure RBAC role.
- **FR-003**: System MUST execute server-side KQL queries against the legacy `AzureDiagnostics` table filtering by `ResourceProvider =~ "MICROSOFT.DOCUMENTDB"`, joining request charges from `DataPlaneRequests` to query details from `QueryRuntimeStatistics` by `activityId_g`, applying container-scoped database resolution for `(shape, container)` pairs with exactly one distinct known database name in the window, and aggregating metrics grouped by the composite tuple `(database, container, query shape)`. System executes two KQL queries: a shapes query returning at most N top shapes, and a totals query returning window-level and attributed totals (`window_total_ru`, `attributed_total_ru`, `total_executions`, and `min(TimeGenerated)` from `DataPlaneRequests`). System MUST NEVER retrieve or paginate through unaggregated raw log rows.
- **FR-004**: System MUST determine query shape identifiers using `shapesignature_s` when present and non-empty, falling back to a SHA-256 hash of `querytext_s` when `shapesignature_s` is missing or null.
- **FR-005**: System MUST compute and report the following metrics for each discovered query shape:
  - Total execution count
  - Cumulative Request Units (total RU)
  - Average Request Units per execution (avg RU)
  - Maximum Request Units for a single execution (max RU)
  - Percentage share of total database RU spend (RU %), where the denominator is the sum of `requestCharge_s` across all `DataPlaneRequests` in scope and window
  - Average documents returned per execution
  - Ratio of total RU per returned document (MUST emit `null` when total returned rows is 0)
  - Count of throttled executions (HTTP 429) where correlated from `DataPlaneRequests`
  - Target database name (`databaseName_s`) and container name (`collectionName_s`), defaulting to `"(unknown)"` if missing/empty in diagnostic records so spend is never discarded
  - Up to top 3 callers with their individual RU share percentages within the shape
  - Sample obfuscated query text
- **FR-006**: System MUST compute and report an unattributed RU summary representing data-plane operations in the scope and window that did not join to a query shape (such as point reads, point writes, administrative calls, or queries without runtime statistics), reporting total unattributed RUs and its percentage share of total database RU spend in both terminal and JSON outputs.
- **FR-007**: System MUST perform metric-only aggregation in this cycle; the system MUST NOT perform SQL parsing or evaluate text-pattern diagnostic rules on discovered queries.
- **FR-008**: System MUST perform best-effort caller attribution for each discovered query shape, reporting up to the top 3 callers per shape ranked by RU spend within that shape, along with each caller's percentage share of the shape's RU spend. Callers MUST be identified by `aadPrincipalId_g` (raw GUID) when present, falling back to `clientIpAddress_s` (raw IP address), or omitted if neither is populated. The system MUST NOT make external directory calls (such as Microsoft Graph). Caller dynamic results returned from Log Analytics MUST be validated strictly: the parser accepts only a list of dictionaries with valid caller keys; malformed shapes (flat arrays, nested pairs, invalid types, more than 3 callers) or invalid RU share (> 100%) MUST raise an `InternalConsistencyError` with a clear diagnostic message, handled cleanly by the CLI with exit code 1, and NEVER be silently dropped or return an empty result.
- **FR-009**: System MUST render discovery results as a formatted terminal table sorted descending by total RU, and MUST support the global `--json` flag emitting structured output matching a dedicated JSON Schema. When `--json` is specified and no query shapes match, `stdout` MUST output valid JSON with an empty `results` list (`[]`), while informational messages are routed exclusively to `stderr`.
- **FR-010**: System MUST support `querylens discover --check` preflight mode reporting for the target workspace and time window:
  - Detection and row counts for categories (`DataPlaneRequests`, `QueryRuntimeStatistics`)
  - Earliest and latest record timestamps per category
  - Population percentages for columns (`shapesignature_s`, `querytext_s`, `aadPrincipalId_g`, `aadPrincipalId_s`, `clientIpAddress_s`, `useragent_s`)
  - Breakdown counts of `authTokenType_s`
  - Masked workspace ID showing only the last 4 characters
  - All preflight metrics MUST contain only counts, percentages, and timestamps, strictly excluding database values or query text, safe to share internally.
- **FR-011**: System MUST infer retention truncation from query result timestamps: if the earliest record timestamp is later than the requested time window start, the system MUST emit a warning notice without querying Azure management APIs.
- **FR-012**: System MUST enforce query text privacy: query text MUST NOT be logged to structured application logs, MUST be truncated in console tables unless `--show-text` is passed, and MUST be omitted from `--json` output unless `--show-text` is passed. System MUST NEVER attempt to deobfuscate query text.
- **FR-013**: System MUST isolate all table and column names into a dedicated column mapping module to allow future support for resource-specific diagnostic tables (`CDBQueryRuntimeStatistics`, `CDBDataPlaneRequests`) without architectural refactoring.
- **FR-014**: System MUST inject the `LogsQueryClient` instance to allow comprehensive unit testing with fake results without network dependencies.
- **FR-015**: System MUST terminate with deterministic exit codes conforming to ADR 0004:
  - `0`: Successful execution or clean empty result.
  - `1`: Invalid CLI options, failed parameter validation, or malformed inputs.
  - `3`: Log Analytics network connection failure, unreachable workspace, or service timeout.
  - `5`: Authentication failure or missing RBAC permissions.
- **FR-016**: System MUST support a `--print-kql` option: when specified, the system builds and prints the generated KQL query text for both the shapes query and the totals query to stdout after validating all CLI options, makes zero network calls, requires zero Azure credentials, and exits with code 0. This enables offline inspection and direct copy-pasting into the Azure portal Logs editor for syntax and column verification.
- **FR-017**: System MUST enforce a silent-zero guard: if `attributed_total_ru` is 0 while `DataPlaneRequests` records exist in the evaluation window, or if essential diagnostic columns (`requestCharge_s`, `activityId_g`, `querytext_s`) are entirely absent or unpopulated, the system MUST terminate with exit code 1 and emit a clear error message directing the user to run `querylens discover --check` rather than rendering a misleading table of zeros.

### Key Entities *(include if feature involves data)*

- **DiscoveredQueryShape**: Represents an aggregated query shape across multiple executions, identified by `(database_name, container_name, shape_id)`.
  - `database_name`: Name of the target Cosmos DB database (defaults to `"(unknown)"` if missing or empty in diagnostic records).
  - `container_name`: Name of the target Cosmos DB container (defaults to `"(unknown)"` if missing or empty in diagnostic records).
  - `shape_id`: Unique shape identifier (`shapesignature_s` string or SHA-256 hash of query text).
  - `execution_count`: Total number of times this shape executed within the time window.
  - `total_ru`: Cumulative Request Units consumed across all executions.
  - `avg_ru`: Mean Request Units per execution.
  - `max_ru`: Maximum Request Units observed in a single execution.
  - `ru_percentage`: Proportion of total database RU spend accounted for by this shape.
  - `avg_returned_rows`: Mean documents returned per execution.
  - `ru_per_returned_row`: Efficiency metric calculating total RUs divided by total returned rows (null when total returned rows is 0).
  - `throttled_count`: Total number of executions resulting in HTTP 429 throttling.
  - `top_callers`: List of up to 3 caller attribution records (`CallerAttribution`), each with caller identifier and percentage share of this shape's RU spend.
  - `sample_query_text`: Obfuscated sample SQL string as logged by Cosmos DB (truncated or null based on `--show-text`).
- **CallerAttribution**: Represents a caller identified for a query shape.
  - `caller_id`: Principal GUID or client IP address string.
  - `caller_type`: Classification enum (`aad_principal` or `client_ip`).
  - `ru_percentage`: Percentage share of the query shape's RU spend consumed by this caller.
- **WorkloadDiscoverySummary**: Overall summary for the discovery execution.
  - `time_window`: Lookback duration evaluated.
  - `total_database_ru`: Total RUs across all data plane requests in scope and window.
  - `total_query_ru`: Total RUs attributed to discovered query shapes.
  - `unattributed_ru`: Cumulative RUs of operations not joined to query shapes.
  - `unattributed_ru_percentage`: Percentage of total database RU spend that is unattributed.
  - `shapes`: Ordered list of `DiscoveredQueryShape` records.
- **PreflightCheckReport**: Quantitative diagnostic summary of workspace readiness.
  - `workspace_id_suffix`: Last 4 characters of the target Log Analytics workspace GUID (e.g. `...1234`).
  - `time_window`: Evaluated duration string.
  - `categories`: Mapping of diagnostic categories to row counts, earliest timestamp, and latest timestamp.
  - `field_population`: Percentage of records containing non-null values for key columns.
  - `auth_token_distribution`: Distribution of authentication token types observed in logs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Discovery query execution transfers zero unaggregated log records across the network; the client receives at most N shape rows plus one totals row (where N is the configured --top value, defaulting to 20, bounded between 1 and 100), enforced by a documented server-side query timeout.
- **SC-002**: The `discover` command makes no calls to the Cosmos DB data plane and requires zero Cosmos DB credentials or permissions.
- **SC-003**: Preflight check reports (`--check`) are safe to share internally; containing 100% quantitative counts, percentages, and timestamps with 0% customer database values, query text, or tenant secrets.
- **SC-004**: 100% of malicious injection characters in CLI inputs (workspace ID, account filter) are rejected during input validation before dispatching remote network queries.
- **SC-005**: 100% of CLI exit codes strictly adhere to the project's deterministic exit code hierarchy (0, 1, 3, 5).
- **SC-006**: Unit test suite runs with 0 live cloud dependencies using injected mock query clients, maintaining the project's >= 85% code coverage threshold.

## Assumptions

- Target Cosmos DB accounts have enabled Diagnostic Settings sending logs to an Azure Log Analytics workspace using the legacy `AzureDiagnostics` destination table.
- The user's Entra ID identity possesses at least `Log Analytics Reader` permissions on the target Log Analytics workspace.
- The `shapesignature_s` field in `AzureDiagnostics` is an undocumented Microsoft field; when absent, falling back to a SHA-256 hash of `querytext_s` provides equivalent shape grouping.
- Replaying discovered queries against an active Cosmos container is out of scope for this cycle because query text is obfuscated by Microsoft (string and numeric literals replaced with parameters or hashes).
- Generating workload YAML files from discovered shapes is deferred to a future feature cycle.
- Resource-specific diagnostic tables (`CDBQueryRuntimeStatistics`, `CDBDataPlaneRequests`) will be addressed in a subsequent cycle via the centralized column mapping module.
- The Azure Monitor Logs SDK may not support parameterized KQL queries; injection safety relies on strict allowlist input validation (e.g. GUID formats, account name regex) combined with a dedicated KQL string-literal escaping function, with both mechanisms verified by Hypothesis property-based tests. The time window is passed exclusively through the SDK's native `timespan` parameter (ISO 8601 duration / interval) and is never interpolated into the KQL query string.
