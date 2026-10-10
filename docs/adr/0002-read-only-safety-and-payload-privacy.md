# Read-Only Safety, Payload Privacy, and Per-Page RU Budget Guard

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: Profiling queries on production Azure Cosmos DB containers must never mutate data, leak sensitive customer payloads, or cause unconstrained billing spikes due to runaway queries.

## Context and Problem Statement

When profiling query performance against live or pre-production Cosmos DB containers, query results may contain confidential or regulated customer data (PII, financial data, health records). Furthermore, non-selective queries or full-table scans can consume thousands of Request Units (RUs), risking throttling for operational workloads or driving unexpected cloud spend. How should QueryLens guarantee safety, privacy, and budget containment?

## Decision Drivers

* Constitution Principle I: Zero-Impact, Read-Only Safety Guarantees.
* Data privacy: QueryLens is a query cost profiler, not a data extraction tool; document payloads must not touch memory, disk, or logs.
* Identity & Access: Prioritize modern passwordless authentication (Entra ID) with least-privilege RBAC.
* Budget containment: Stop execution immediately if a query exceeds a predetermined RU ceiling.

## Considered Options

* Option 1: Entra ID RBAC (Cosmos DB Built-in Data Reader), streaming item discard during iteration, and per-page cumulative RU budget checking.
* Option 2: Buffering query results in memory or disk cache to allow offline item inspection, with post-query budget evaluation.
* Option 3: Permissive credential support (write keys permitted) with opt-in payload logging.

## Decision Outcome

Chosen option: "Option 1", because:

1. **Entra ID First**: `DefaultAzureCredential` is the primary auth path; documentation explicitly recommends assigning the built-in "Cosmos DB Built-in Data Reader" role. (Primary/secondary master keys and emulator keys are supported as fallback/local dev options).
2. **Payload Privacy**: When enumerating query results (`CosmosItemPaged`), result item bodies are consumed and immediately discarded (`for _ in page: pass`). No document payloads are ever stored in memory, written to disk, or logged.
3. **Per-Page Budget Guard**: The cumulative Request Units consumed are tracked across each response page. If the cumulative charge exceeds the configured `--budget-ru` ceiling, iteration halts immediately, and the query is marked `is_partial=True`, exiting with code 2.

### Positive Consequences

* Impossible to accidentally leak sensitive customer payloads through QueryLens CLI outputs, logs, or error dumps.
* Runaway cross-partition queries are cut off before consuming excessive RUs.
* Read-only RBAC ensures the CLI cannot perform writes, deletions, or schema alterations even if compromised.

### Negative Consequences

* QueryLens cannot display query output previews or verify query correctness (e.g. checking if returned documents match expected business criteria). Users must use standard query clients for data inspection.

## Pros and Cons of the Options

### Option 1: Entra ID Reader, Discard Iteration, Per-Page Budget Guard (Chosen)

* Good, because strictly enforces Constitution Principle I.
* Good, because protects against cloud billing spikes.
* Good, because guarantees zero compliance or PII exposure risk.
* Bad, because precludes sample data output in reports.

### Option 2: In-Memory/Disk Caching and Post-Execution Budget Check

* Good, because allows users to view what documents were returned by the query.
* Bad, because violates data privacy guarantees and risks huge memory footprint on multi-gigabyte queries.
* Bad, because post-execution budget checks cannot prevent runaway RU consumption that already occurred.

### Option 3: Permissive Credentials and Logging

* Good, because requires less auth setup configuration.
* Bad, because write keys violate least-privilege principles and risk accidental data mutation.
