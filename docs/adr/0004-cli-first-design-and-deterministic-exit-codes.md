# CLI-First Design and Deterministic Exit Code Hierarchy

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: QueryLens is used both interactively by engineers investigating high-cost queries and automatically in CI/CD pull request gates to prevent performance regressions.

## Context and Problem Statement

A command-line tool deployed into automated pipelines must clearly communicate execution status and failure modes to calling orchestrators (GitHub Actions, Azure DevOps, bash/PowerShell scripts). If exit codes are lumped together (e.g. exit 1 for every error), CI scripts cannot distinguish between network transient timeouts, invalid workload schema inputs, security permission denials, budget overruns, and query performance rule violations. How should QueryLens design its CLI interface and exit codes?

## Decision Drivers

* Constitution Principle IV: CLI-First Ergonomics and Automation Readiness.
* Predictable CI/CD automation: Distinct exit codes for distinct failure domains.
* Interactive readability: Beautiful Rich terminal tables with color-coded severity badges and sorted metrics.
* Machine readability: Strict JSON output (`--json`) conforming to `run-output-schema.json`.

## Considered Options

* Option 1: Click-based CLI with Rich interactive console output, strict `--json` serialization to stdout, `--fail-on <severity>` threshold gating, and a 6-code deterministic exit hierarchy (0, 1, 2, 3, 4, 5).
* Option 2: Binary exit code model (0 = success, 1 = any failure) with plain-text output.
* Option 3: Two separate CLI entrypoints: `querylens-ui` for humans and `querylens-ci` for pipelines.

## Decision Outcome

Chosen option: "Option 1", because:

1. **Deterministic Exit Codes**:
   * `0`: Success — all queries executed successfully; findings (if any) are below the `--fail-on` threshold.
   * `1`: Validation / Usage / Query Execution Error — invalid workload YAML, partition key format violation (length not 1..3, nulls, nested lists), missing required options, or one or more queries encountered an execution error (e.g. HTTP 400 syntax error).
   * `2`: Cumulative RU Budget Exceeded — query execution aborted early due to breaching `--budget-ru`; partial results returned.
   * `3`: Connection Error — network unreachable, DNS resolution error, Cosmos database or container not found (HTTP 404).
   * `4`: Diagnostic Threshold Breached — at least one diagnostic finding met or exceeded the `--fail-on` severity (`critical`, `high`, `medium`).
   * `5`: Authentication / Authorization Failure — invalid credentials, missing "Cosmos DB Built-in Data Reader" role, HTTP 401/403.
2. **Exit Code Precedence Hierarchy**:
   * Fatal transport errors (`3` for connection/not-found, `5` for auth failure) terminate immediately.
   * For completed or budget-halted workload runs, exit codes are evaluated with strict precedence:
     1. **`2` (Budget Exceeded)**: Highest post-execution priority; indicates execution was forcibly halted by the RU safety ceiling and results are partial.
     2. **`4` (Diagnostic Gate Breached)**: Explicit policy gate failure (`--fail-on`) takes precedence over individual query errors so CI pipelines evaluate regression gates deterministically.
     3. **`1` (Query Execution / Usage Error)**: Triggered if any query ended with an `error_message` after rendering reports, or if CLI arguments were invalid.
     4. **`0` (Success)**: All queries executed cleanly and no gates were breached.
3. **Dual Output Modes**:
   * Interactive (default): Rich table sorting queries descending by RU cost, formatted latencies, partition fan-out counts, and colored diagnostic tags.
   * Machine (`--json`): Pure JSON written to stdout adhering strictly to `run-output-schema.json` with zero extraneous console noise (logs routed to stderr).
4. **Threshold Gate (`--fail-on`)**:
   * Accepts `critical`, `high`, or `medium` (default off). Allows CI pipelines to enforce quality gates (e.g. block PR if any `high` severity finding is detected).

### Positive Consequences

* Pipeline scripts can implement targeted retry or escalation logic (e.g. retry on 3, alert security on 5, fail PR on 4, warn on 2).
* High developer delight in interactive terminal sessions.
* Seamless integration with automation tools.

### Negative Consequences

* Callers must be aware of the exit code numbering contract when writing custom shell scripts.

## Pros and Cons of the Options

### Option 1: Multi-Level Exit Codes and Dual Output (Chosen)

* Good, because delivers exact operational clarity for both human and automated consumers.
* Good, because unifies human and CI execution into a single, cohesive command.
* Bad, because requires comprehensive test coverage of all exit code pathways.

### Option 2: Binary Exit Codes (0 or 1)

* Good, because simplistic.
* Bad, because CI scripts cannot distinguish between an auth failure, a network drop, or a query diagnostic failure.

### Option 3: Separate CLI Binaries

* Good, because separates human vs machine concerns.
* Bad, because doubles maintenance surface area and creates user confusion.
