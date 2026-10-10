# KQL Injection Defense, Input Validation, and Time Window Handling

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: Because the Azure Monitor Logs Query REST API and SDK do not support parameterized queries or query argument bindings, dynamic KQL construction introduces potential injection risks if user inputs are untrusted. Define a defense-in-depth security model to eliminate KQL injection while preserving optimal query execution performance.

## Context and Problem Statement

When users invoke `querylens discover`, several parameters dictate the scope and filtering of the log analysis:

* `--workspace-id` (or `QUERYLENS_WORKSPACE_ID`): Log Analytics workspace identifier.
* `--account`: Optional Cosmos DB database account filter.
* `--window`: Lookback time window (e.g., `24h`, `7d`).
* `--top`: Maximum number of expensive query shapes to return (e.g., `20`).

As established in [ADR 0006](file:///docs/adr/0006-azure-monitor-logs-query-contracts.md), the Azure Monitor Logs Query API does not accept parameterized queries (e.g., `@param` or variable declarations). How does QueryLens construct secure, performant KQL queries without exposing the system to injection vulnerabilities or data plane exfiltration?

## Decision Drivers

* Constitution Principle I: Zero-Impact, Read-Only Safety Guarantees & Input Validation (strict Pydantic schemas, validation before network dispatch).
* Constitution Principle III: Test-First Rule Development & Property Verification (Hypothesis fuzz testing for injection boundaries).
* Constitution Principle IV: CLI-First Contract & Deterministic Exit Codes (rejecting invalid input with exit code 1).
* Performance: Utilizing Azure Monitor's native time-based partition extent pruning.

## Considered Options

* Option 1: Two-layer defense-in-depth: strict allowlist validation on all inputs before query generation, programmatic KQL string-literal escaping, and routing time windows exclusively through the SDK's native `timespan` keyword argument.
* Option 2: Relying solely on KQL string escaping without regex/type allowlists.
* Option 3: Interpolating `where TimeGenerated >= ago(...)` directly into KQL query text.

## Decision Outcome

Chosen option: "Option 1", because:

### 1. Layer 1: Strict Allowlist Input Validation

All inputs are validated before any KQL string construction or network requests occur:

* **Workspace ID**:
  * Must be a valid RFC 4122 UUID string (`UUIDv4` format: `^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`).
  * Validated via standard library `uuid.UUID(workspace_id)`.
  * Passed directly to the SDK method `query_workspace(workspace_id, ...)` as the target resource; it is never interpolated into KQL.
* **Account Name Filter (`--account`)**:
  * Azure Cosmos DB account names adhere to strict naming rules: 3 to 44 characters, lowercase letters, numbers, and hyphens; cannot start or end with a hyphen.
  * Regex validation: `^[a-zA-Z0-9][-a-zA-Z0-9]{1,42}[a-zA-Z0-9]$`.
  * Any value failing this pattern is rejected immediately with an informative error message and CLI exit code 1. No query is constructed or dispatched.
* **Top N Limit (`--top`)**:
  * Strictly validated as an integer bounded between 1 and 100 (`1 <= top <= 100`).
  * Rejects non-integer, negative, zero, or excessively large limits with exit code 1.
* **Lookback Window (`--window`)**:
  * Parsed using a dedicated duration parser supporting units `m` (minutes), `h` (hours), `d` (days) (e.g., `30m`, `24h`, `7d`).
  * Enforces boundary limits: minimum 5 minutes, maximum 90 days (standard Azure Log Analytics interactive retention window).
  * Returns a standard Python `datetime.timedelta`.

### 2. Layer 2: Dedicated KQL String-Literal Escaping

When optional filter strings (such as `--account`) are interpolated into KQL string literals, they are escaped via a dedicated function `escape_kql_string`:

```python
def escape_kql_string(value: str) -> str:
    """Escape characters in a string value for safe insertion into KQL double-quoted string literals.

    Args:
        value: Input string to escape.

    Returns:
        Escaped string safe for inclusion within KQL double quotes.
    """
    # Backslashes must be escaped first, followed by double quotes
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

In KQL, string literals enclosed in double quotes use backslash as the escape character:

```kusto
| where _ResourceId has "/databaseaccounts/{escaped_account}"
```

Combined with Layer 1's regex validation, injection into KQL syntax is mathematically impossible.

### 3. Native SDK `timespan` Routing

The time window is **never** interpolated into KQL text (e.g., QueryLens never writes `| where TimeGenerated > ago(24h)`).

Instead, QueryLens passes the validated `datetime.timedelta` directly to the `LogsQueryClient.query_workspace(..., timespan=window_delta)` parameter:

* **Partition Pruning**: Azure Monitor uses the HTTP `timespan` query parameter to prune storage shards and extents before the Kusto execution engine evaluates the query. This significantly reduces server-side scan overhead and execution latency.
* **Timezone Safety**: By passing a structured `timedelta`, Azure Monitor evaluates the exact relative window server-side without clock drift or ISO timestamp formatting ambiguities.
* **Zero Injection Surface**: Time window logic is completely absent from the KQL text, eliminating any potential date-manipulation injection vectors.

### 4. Property-Based Testing Verification

To uphold Constitution Principle III, `escape_kql_string` and input validation are subjected to generative property-based testing with `hypothesis`:

* Generates randomized strings with control characters, quotes (`"`, `'`, `\```), semicolons, comment sequences (`//`,`/*`), pipes (`|`), and Unicode line breaks.
* Asserts that `escape_kql_string` produces output that does not contain unescaped quotes or allow delimiter breakout.
* Verifies that the regex validator rejects 100% of invalid account strings containing shell metacharacters, spaces, or punctuation.
