# Minimal DatabaseAdapter Protocol and Unified Cost Model

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: QueryLens needs to profile query execution costs across database engines, beginning with Azure Cosmos DB for NoSQL and expanding to other engines in the future, without introducing premature abstraction layers.

## Context and Problem Statement

Multi-database query profilers often suffer from leaky abstractions, premature generalization, and bloated ORM-style wrappers. How should QueryLens decouple its diagnostic rules and CLI reporting from vendor-specific database SDKs while keeping development focused on Azure Cosmos DB for NoSQL?

## Decision Drivers

* Constitution Principle II: Minimal Abstraction Architecture.
* Simplicity: Rules should be stateless and operate exclusively on cost metrics, not database drivers.
* Future extensibility: Easy addition of subsequent database engines without rewriting analysis logic.
* Rule testability: Pure domain models enable fast in-memory unit tests and property testing without database drivers.

## Considered Options

* Option 1: Minimal `DatabaseAdapter` `typing.Protocol` with a single unified `QueryCost` domain model and plain-function rules.
* Option 2: Full Repository & Unit-of-Work pattern with an abstract base class hierarchy and dynamic plugin framework.
* Option 3: Direct integration with `azure-cosmos` inside the CLI and rule engine without any abstraction protocol.

## Decision Outcome

Chosen option: "Option 1", because:

1. It defines a minimal structural interface `collect(workload: Workload) -> Iterator[QueryCost]`.
2. Diagnostic rules are pure functions `(QueryCost, Settings) -> list[Finding]` that know nothing about Cosmos DB drivers.
3. Avoids premature repository layers or plugin reflection frameworks, satisfying the constitution's minimal abstraction gate.

### Positive Consequences

* The rule engine is completely decoupled and tested with plain Pydantic models.
* Adding a new backend only requires implementing one `collect` method that maps vendor metrics to `QueryCost`.
* No complex dependency injection or plugin registration lifecycle.

### Negative Consequences

* Database-specific execution nuances must be normalized into `QueryCost` attributes (or structured metadata fields).

## Pros and Cons of the Options

### Option 1: Minimal Protocol and Unified QueryCost (Chosen)

* Good, because structural typing (`Protocol`) avoids hard inheritance coupling.
* Good, because rules remain pure, deterministic, and easily testable.
* Bad, because vendor-specific metrics not captured in `QueryCost` require schema updates.

### Option 2: Full Repository & Dynamic Plugin Architecture

* Good, because highly modular for enterprise multi-tenant plugins.
* Bad, because violates Constitution Principle II; introduces unnecessary boilerplate and abstraction overhead.

### Option 3: Direct Coupling to Cosmos SDK

* Good, because zero abstraction layers.
* Bad, because rules become untestable without Cosmos DB objects, and adding future databases requires rewriting the entire application.
