<!--
SYNC IMPACT REPORT
==================
- Version change: Unversioned Scaffold → 1.0.0
- List of modified principles:
  * [PRINCIPLE_1_NAME] → I. Read-Only Safety & Privacy-First Security
  * [PRINCIPLE_2_NAME] → II. Minimal Abstraction Architecture
  * [PRINCIPLE_3_NAME] → III. Test-First Rule Development & Property Verification
  * [PRINCIPLE_4_NAME] → IV. CLI-First Contract & Deterministic Diagnostics
  * [PRINCIPLE_5_NAME] → V. Dependency Discipline (Reuse Over Reinvention)
- Added sections:
  * Code Quality & Static Analysis Standards
  * Development Workflow & Change Management
- Removed sections:
  * None (placeholder sections concretized)
- Follow-up TODOs:
  * None (all principles and governance rules fully defined)
-->

# QueryLens Constitution

## Core Principles

### I. Read-Only Safety & Privacy-First Security
QueryLens is an analytical advisor and MUST operate with zero trust toward target database integrity and sensitive user data:
- **Read-Only Invariant**: QueryLens MUST be strictly read-only. It MUST NEVER execute write, update, delete, or administrative/schema modifications against any target database.
- **Zero-Secret Footprint**: Source code, test fixtures, configuration files, and log streams MUST NEVER contain credentials or connection secrets. Authentication MUST resolve exclusively via Microsoft Entra ID (through `azure-identity`) or managed environment variables.
- **Payload Privacy**: Query result record bodies MUST NEVER be persisted, cached, or logged. The engine MUST retain only query text structure, execution cost metrics (e.g., Azure Cosmos DB Request Units / RUs), and runtime engine statistics.
- **Opt-In LLM Redaction**: Integration with Large Language Models (LLMs) MUST be explicitly opt-in. Prior to transmitting query text to any external or cloud-hosted model, all literal values (literals, parameters, string and numeric values) MUST be redacted.
- **Input Validation**: All external inputs (workload traces, configuration files, CLI options, and raw LLM responses) MUST be parsed and validated through strict Pydantic schemas before consumption.

*Rationale*: QueryLens will analyze production and pre-production database workloads. Guaranteeing read-only behavior eliminates operational risk, while literal redaction and strict secret hygiene protect organizational compliance and customer privacy.

### II. Minimal Abstraction Architecture
QueryLens maintains an intentionally lean abstraction layer centered on a single cost model:
- **Protocol-Based Adapters**: Database interactions MUST be encapsulated behind a minimal `DatabaseAdapter` `typing.Protocol`.
- **Target Sequencing**: Azure Cosmos DB for NoSQL is the primary target backend. Additional database engines MAY be introduced only after the Cosmos DB implementation is proven and stable.
- **Unified Domain Model**: Each database adapter MUST map native engine metrics into a shared `QueryCost` domain model.
- **Rule Independence**: Cost analysis and optimization rules MUST operate exclusively on the `QueryCost` model and generic query AST metadata, never against vendor-specific driver constructs.
- **Abstraction Gate**: No additional intermediate layers, abstractions, or design patterns (e.g., repository layers, complex plugin registries) MAY be introduced without an approved Architecture Decision Record (ADR) justifying the complexity.

*Rationale*: Premature generalization across diverse database paradigms leads to leaky abstractions and unneeded complexity. A single adapter protocol and a uniform `QueryCost` model provide clean extensibility while keeping development focused on real Cosmos DB performance gains.

### III. Test-First Rule Development & Property Verification
Testing is a first-class engineering contract that prevents regressions and guarantees diagnostic accuracy:
- **Test-First Implementation (TDD)**: All cost analysis, diagnostic checks, and recommendation rules MUST follow a test-first workflow. Unit tests defining expected detections and remedies MUST be authored and failing prior to rule implementation.
- **Property-Based Verification**: The rule evaluation engine MUST be tested using `hypothesis` to assert safety invariants across generated edge-case query structures, parameter permutations, and cost boundary conditions.
- **CI Coverage Threshold**: CI pipelines MUST enforce a minimum test coverage threshold of 85% across all core and adapter logic. Pull requests dropping below this threshold MUST NOT be merged.
- **Real-World Integration Verification**: Database integration tests MUST execute against local emulator instances (specifically the Azure Cosmos DB Linux emulator in Docker). CI and automated test runs MUST NOT depend on live cloud resources.

*Rationale*: Erroneous query advice can misguide engineering teams into suboptimal indexing or schema changes. Property-based tests and emulator integration verify that analysis logic holds true under production-grade Cosmos DB behaviors without incurring cloud costs.

### IV. CLI-First Contract & Deterministic Diagnostics
QueryLens delivers diagnostic insights through a dependable command-line interface suitable for human developers and automation:
- **Dual Output Formats**: Every command MUST support structured machine-readable JSON via a global `--json` flag in addition to human-friendly terminal formatting.
- **Predictable Exit Codes**: Commands MUST terminate with distinct, documented exit codes separating standard completion, detected rule violations, configuration errors, and execution failures.
- **Clean Diagnostic Presentation**: Error messages presented to users MUST be concise and actionable. Raw exception stack traces MUST NOT be exposed on `stderr` unless the `--debug` flag is explicitly provided.
- **Actionable Remedies**: Cost analyses MUST accompany detected inefficiencies with clear, concrete recommendations (e.g., composite indexing suggestions, partition key re-evaluations, query rewrites).

*Rationale*: CLI tools must seamlessly bridge interactive terminal inspection and automated CI/CD deployment gates. Explicit exit codes, structured JSON output, and sanitized diagnostic messages prevent pipeline brittleness and provide a polished developer experience.

### V. Dependency Discipline (Reuse Over Reinvention)
QueryLens values long-term maintainability over custom reinvented utility code:
- **Library Preference**: Established, actively maintained open-source libraries MUST be preferred over in-house custom implementations for non-core capabilities.
- **No Bespoke Infrastructure**: Custom implementations MUST NOT be written for non-trivial parsing, network retries, authentication handshakes, configuration parsing, or terminal formatting when a standard ecosystem package exists.
- **Documented Justification**: Every proposed dependency MUST include a one-line justification in the feature plan detailing its explicit necessity, maintenance health, and license suitability.
- **Package Management**: Dependencies MUST be declared and managed strictly via `uv` with a committed lockfile (`uv.lock`).

*Rationale*: Writing custom parsing, retry, or authentication logic introduces subtle security bugs and expands maintenance overhead. Relying on vetted packages keeps the QueryLens codebase focused strictly on its primary value: database query cost analysis.

## Code Quality & Static Analysis Standards
To ensure a reliable and maintainable open-source codebase, QueryLens enforces strict static quality gates:
- **Runtime Target**: Python 3.12 or newer MUST be required across all environments.
- **Dependency Toolchain**: `uv` MUST be used for package resolution, dependency installation, and virtual environment orchestration.
- **Linting & Formatting**: `ruff` is the sole linter and formatter. The configuration MUST enable rulesets `D` (pydocstyle), `DOC` (documentation formatting), and `S` (flake8-bandit security checks). Code MUST format cleanly under default Ruff rules.
- **Documentation Standard**: All public modules, classes, and callable functions MUST feature Google-style docstrings, including explicit `Args:`, `Returns:`, and `Raises:` sections.
- **Type Safety**: `pyrefly` MUST enforce strict type checking across all packages. Untyped public APIs and undocumented `Any` fallbacks are strictly prohibited.
- **Pre-Commit Enforcement**: A configured `pre-commit` hook pipeline MUST execute formatting, linting, type validation, and hygiene checks before any commit is recorded locally.

## Development Workflow & Change Management
Team collaboration and repository changes adhere to predictable open-source practices:
- **License**: All QueryLens code, documentation, and releases are distributed under the MIT License.
- **Commit History**: Commits MUST adhere to the Conventional Commits specification (e.g., `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **Atomic Pull Requests**: Pull requests MUST be small, scoped to a single logical change or feature increment, and accompanied by comprehensive tests.
- **Architecture Decision Records (ADRs)**: Significant architectural additions, schema changes, new database backends, or deviations from constitutional principles MUST be recorded as an ADR within `docs/adr`.

## Governance
This Constitution represents the authoritative governance specification for the QueryLens project:
- **Supremacy**: The principles and technical standards articulated in this document supersede conflicting team conventions, documentation, or historical practices.
- **Amendment Process**: Amendments to this constitution MUST be proposed via Pull Request and MUST include:
  1. An ADR in `docs/adr` explaining the context, problem, evaluated alternatives, and trade-offs.
  2. Formal review and approval from project maintainers.
  3. A corresponding semantic version increment in accordance with the versioning policy.
- **Versioning Policy**:
  - **MAJOR** increment (e.g., 1.0.0 → 2.0.0): Incompatible alterations, removal or fundamental redefinition of core principles.
  - **MINOR** increment (e.g., 1.0.0 → 1.1.0): Introduction of new principles, structural sections, or materially expanded guidelines (such as onboarding an additional database engine).
  - **PATCH** increment (e.g., 1.0.0 → 1.0.1): Clarifications, non-semantic wording updates, or typo corrections.
- **Compliance Verification**: All automated pull request checks (CI) and human peer reviews MUST confirm compliance with constitutional rules, test coverage thresholds, and security controls before merging.

**Version**: 1.0.0 | **Ratified**: 2026-10-10 | **Last Amended**: 2026-10-10
