# Architecture Boundaries Enforced with import-linter

* Status: accepted
* Deciders: Matt
* Date: 2026-11-01

Technical Story: The module boundaries described in ADR 0001 and in the project constitution (a thin `DatabaseAdapter` seam, rules as plain functions over metrics, a log-discovery path separate from the query-running path) are held in place only by convention. Nothing fails when someone imports across them.

## Context and Problem Statement

QueryLens has two independent workflows. `querylens run` executes queries through an adapter and applies rules to the metrics it gets back. `querylens discover` reads diagnostic logs through a separate package. The two share only the report conventions and the CLI entry point.

The design depends on a few properties staying true:

* Rules and models are plain Python over metrics and do not depend on any Azure SDK. This is what makes the rules testable without cloud access and keeps the adapter seam real.
* The discovery package does not import the adapters, rules, domain model, or settings of the `run` path.
* Dependencies point one way, from the command line down to the models.

These properties currently hold, but a single convenient import could break any of them without a test failing. How do we make the boundaries a checked rule and not a habit?

## Decision Drivers

* Constitution Principle II: no additional layers or abstractions without an ADR, which only means something if the existing layering is stable.
* The review process already found problems that only appeared at module edges, so edges deserve an automated check.
* The check must be fast, run in the existing pre-commit step, and need no new CI job or required status check.

## Considered Options

* Option 1: Convention and code review only.
* Option 2: A custom test that walks the AST of each module and asserts allowed imports.
* Option 3: `import-linter`, a maintained tool that builds the import graph and checks declared contracts.

## Decision Outcome

Chosen option: Option 3, because it expresses the boundaries declaratively, handles indirect imports, and is a small dev-only dependency. A custom AST test would reimplement the same graph logic with less coverage of indirect imports.

The contracts live in `pyproject.toml` under `[tool.importlinter]`:

* **Layered architecture.** The command-line modules sit on top, then `report`, then `adapters`, `rules` and `discovery` as independent siblings, then `model`, `config` and `logging` at the bottom. A lower layer cannot import an upper one, and the three middle siblings cannot import each other.
* **Discovery is decoupled from the run path.** `querylens.discovery` cannot import `adapters`, `rules`, `model`, or `config`.
* **Domain code does not depend on the Azure SDK.** `rules`, `model`, `config`, `report` and `logging` cannot import `azure`.

Imports that exist only for type checking are excluded, so annotations do not create false violations. The check runs through `uv run lint-imports`, wired as a local pre-commit hook, which means CI enforces it inside the existing quality job.

### Consequences

* Good, because an import that crosses a boundary now fails locally and in CI with the offending chain printed.
* Good, because the contracts are documentation: reading `pyproject.toml` shows the intended architecture.
* Bad, because import-linter treats external packages by their root name only, so it cannot distinguish `azure.cosmos` from `azure.monitor`. The separation between the two Azure services is enforced indirectly: `discovery` cannot import `adapters`, and the adapter does not import the discovery package.
* Bad, because contracts must be updated when the architecture changes on purpose.

## Changing the Contracts

A failing contract is a signal to either fix the import or change the design. If the design should change:

1. Open the pull request with the change to the contract in `pyproject.toml`.
2. Explain the new dependency direction in the pull request description and update this ADR, or add a new ADR if the change reverses a decision.
3. Do not add `ignore_imports` entries to silence a violation without a comment naming the reason and the issue that will remove it.

To confirm a contract is live, add a throwaway module that violates it (for example, a file under `src/querylens/rules/` that imports `azure.core`), run `uv run lint-imports`, and expect that contract to report BROKEN. Delete the file afterwards. Do not commit it.
