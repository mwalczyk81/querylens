# Contributing to QueryLens

Thank you for your interest in contributing to QueryLens! This document provides guidelines and workflows for setting up your local development environment, running tests, proposing architectural changes, and submitting contributions.

---

## Development Setup

QueryLens requires **Python 3.12+** and uses [uv](https://docs.astral.sh/uv/) for high-performance dependency management and virtual environments.

### 1. Clone & Synchronize Dependencies

Clone the repository and install all dependencies (including dev tools, test runners, and linters) with `uv`:

```bash
git clone https://github.com/mwalczyk81/querylens.git
cd querylens
uv sync --locked
```

### 2. Install Pre-Commit Hooks

We enforce strict formatting, linting, and typing on every commit. Install the pre-commit git hooks:

```bash
uv run pre-commit install
```

To run all hooks manually across all files at any time:

```bash
uv run pre-commit run --all-files --show-diff-on-failure
```

---

## Running Tests & Type Checking

Our test suite includes unit tests, property-based tests via Hypothesis, Syrupy snapshot tests, and integration tests.

### Unit Tests & Coverage Gate

Run the unit and snapshot test suite with coverage enforcement (minimum 85% coverage required):

```bash
uv run pytest --cov=querylens --cov-fail-under=85 -m "not integration"
```

### Type Checking

Type checking is performed using [Pyrefly](https://github.com/facebook/pyrefly) in strict mode:

```bash
uv run pyrefly check
```

### Offline Discovery Testing

All Log Analytics discovery tests (KQL query construction, parameter validation, caller attribution, service orchestration, and output formatting) run 100% offline without Azure network calls or credentials using synthetic fixtures:

```bash
uv run pytest tests/unit/test_discover_* tests/integration/test_discover_snapshots.py
```

### Live-Gate Policy & Synthetic Regression Fixtures

In accordance with Constitution Principle I (Read-Only Safety) and Principle III (Offline CI Verification), KQL queries are never executed against live Azure infrastructure in automated CI pipelines. Instead, releases and discovery features are gated on the live workspace qualification procedure in `docs/manual-testing.md` and `docs/live-gate.md`.

- **Golden KQL Snapshot Diff Means Re-Gate**: Any code change that alters generated KQL queries (producing a diff in `tests/unit/__snapshots__/test_discover_kql_snapshots.ambr`) invalidates prior live qualification and **strictly requires re-executing the live workspace gate** against a real workspace before merging or releasing.
- **Synthetic Regression Fixture Policy**: Every discrepancy, edge case, or unexpected server serialization encountered during live-gate qualification must produce a regression fixture in `tests/fixtures/synthetic_logs.py` mirroring the **real server result shape**, populated with synthetic values only. Live findings are permanently codified into offline regression tests.

### Regenerating README Assets

The terminal SVG demo in the README (`docs/assets/querylens-demo.svg`) is generated from deterministic sample run metrics (`docs/assets/sample-run.json`).

To regenerate the SVG from existing sample data:

```bash
uv run python scripts/gen_readme_assets.py
```

To re-run against the local emulator to refresh `sample-run.json` and the SVG:

```bash
uv run python scripts/gen_readme_assets.py --refresh
```

When refreshing sample run metrics, ensure the single-query `--json` excerpt in `README.md` is updated to match. A drift test in `tests/unit/test_readme_assets.py` runs in CI to verify byte-for-byte equality for the SVG and consistency of the README JSON excerpt against `sample-run.json`.

---

## Local Cosmos DB Emulator Quickstart

To run the full integration suite or profile sample workloads locally, spin up the Linux Azure Cosmos DB emulator using Docker Compose:

### 1. Start the Emulator

```bash
docker compose up -d
```

Wait until the emulator endpoint becomes healthy (approximately 60–90 seconds):

```bash
curl -k -f https://localhost:8081/_explorer/emulator.pem
```

### 2. Seed Test Data

Run the deterministic seeding script to populate test containers across partitioned and unindexed schemas:

```bash
uv run python scripts/seed_emulator.py
```

Options:

- `--reset`: Drop and recreate existing databases/containers prior to seeding.
- `--endpoint`: Specify custom local endpoint (default: `https://localhost:8081/`).
- `--key`: Specify emulator master key (defaults to well-known emulator key).

### 3. Run Integration Tests

Run the integration suite against the running emulator:

```bash
uv run pytest -m integration -v
```

To enforce that integration tests fail if the emulator is unreachable (standard in CI):

```bash
QUERYLENS_REQUIRE_EMULATOR=1 uv run pytest -m integration -v
```

---

## Architectural Decision Records (ADRs)

QueryLens uses Architectural Decision Records stored in [`docs/adr/`](docs/adr/) to capture significant architectural, behavioral, and interface choices.

When proposing changes that alter:

- Domain models or the `DatabaseAdapter` protocol
- Exit code semantics or precedence hierarchies
- JSON schema output contracts (`specs/001-cosmos-query-cost/contracts/run-output-schema.json`)
- Safety guarantees, authentication requirements, or metrics extraction

Please create or update the corresponding ADR using the numbered MADR format (`YYYY-short-title.md`) and reference it in your pull request.

---

## Spec-Driven Development Workflow

QueryLens was developed using the [Spec-Kit](https://github.com/mwalczyk/spec-kit) methodology, which emphasizes formal requirements specification, architectural design artifacts, and executable contracts prior to code generation. Feature definitions, research findings, data models, and test matrices are maintained under `specs/` (such as `specs/001-cosmos-query-cost/`). Contributors working on new features or major enhancements are encouraged to structure their proposals by drafting specification and task artifacts before implementation to ensure traceability and architectural alignment.
