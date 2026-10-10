# Test-First Property Testing and Docker Cosmos Emulator Integration

* Status: accepted
* Deciders: Matt
* Date: 2026-10-10

Technical Story: QueryLens must reliably diagnose query anti-patterns and parse Cosmos DB metrics without regression or silent metric discrepancies.

## Context and Problem Statement

Diagnostic rules evaluate numerical thresholds across multiple interacting dimensions (Request Units, documents scanned vs returned, physical partitions). Manual edge case test cases often miss subtle boundary bugs, float precision issues, or ordering inconsistencies. Furthermore, relying solely on mocks for Azure Cosmos DB risks discrepancies with actual service behavior. How should QueryLens structure its test suite to guarantee correctness and maintainability?

## Decision Drivers

* Constitution Principle III: Rigorous Quality Gates, Test-First Discipline, and Property Verification.
* Constitution Principle V: Observability and Reproducibility.
* Minimum 85% branch and line coverage requirement.
* Rule stability: Invariant properties (e.g. monotonicity of severity ratings as scan gaps increase) must be proven across randomized inputs.
* Real wire verification: Verifying against actual Cosmos DB response headers without paying cloud costs.

## Considered Options

* Option 1: Multi-tiered testing: Test-first TDD for rule units, Hypothesis property-based testing for rule invariants, Syrupy snapshot testing for CLI formatting, and Docker Cosmos DB Linux emulator for end-to-end integration tests.
* Option 2: Pure mock unit testing with Pytest, omitting property testing and containerized emulator integration.
* Option 3: End-to-end integration testing requiring live Azure subscription resources.

## Decision Outcome

Chosen option: "Option 1", because:
1. **Test-First Discipline**: Rule tests (e.g. `HIGH_RU`, `FANOUT`, `SCAN_GAP`) and CLI exit codes (0, 1, 2, 3, 4, 5) are authored first, establishing unambiguous behavioral contracts before production code is written.
2. **Property-Based Verification**: `hypothesis` is utilized to generate thousands of synthetic `QueryCost` instances, verifying:
   - Non-negative scores and valid `Severity` levels.
   - Monotonic severity ordering (as scanned-to-returned ratio increases, severity never decreases).
   - Boundary condition stability around thresholds (e.g. 50 RUs, 1000 RUs, 10x ratio).
3. **Cosmos DB Linux Emulator**: `docker-compose.yml` configures `mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator` enabling realistic SDK wire protocol tests in local dev and CI.
4. **CLI Snapshots**: `syrupy` captures deterministic CLI terminal rendering (tables, colors, exit codes) to detect unintentional UX regressions.

### Positive Consequences

* High confidence in diagnostic rule accuracy across all numeric input ranges.
* Safe refactoring enabled by property invariant tests.
* Integration tests run locally and in GitHub Actions without cloud credentials or Azure recurring costs.
* Adheres to the 85% coverage constitutional mandate.

### Negative Consequences

* Running the Docker Cosmos emulator locally requires Docker Desktop and takes ~1-2 minutes to initialize. Integration tests must be marked (`@pytest.mark.integration`) and decoupled from quick unit test loops.

## Pros and Cons of the Options

### Option 1: Multi-Tiered (TDD + Hypothesis + Emulator + Snapshots) (Chosen)

* Good, because delivers rock-solid correctness guarantees.
* Good, because tests rule invariants rather than just hand-crafted cherry-picked examples.
* Good, because emulator validates actual Azure SDK behavior without cloud spend.
* Bad, because increases initial test infrastructure setup time.

### Option 2: Mock-Only Unit Testing

* Good, because fast execution.
* Bad, because mocks often drift from actual Cosmos DB SDK response structure (e.g. header formats, pagination quirks).
* Bad, because fails to test edge cases found by generative property fuzzing.

### Option 3: Live Azure Subscription Integration

* Good, because 100% production fidelity.
* Bad, because introduces billing costs, latency, secret management complexity in CI, and flakiness on network transient errors.
