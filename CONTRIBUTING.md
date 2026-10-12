# Contributing to QueryLens

Thank you for your interest in contributing to QueryLens. This document provides guidelines for setting up your local development environment, running tests, proposing architectural changes, and submitting contributions.

---

## Development Setup

QueryLens requires **Python 3.12+** and uses [uv](https://docs.astral.sh/uv/) to manage dependencies and virtual environments.

### 1. Clone & Synchronize Dependencies

Clone the repository and install all dependencies (including dev tools, test runners, and linters) with `uv`:

```bash
git clone https://github.com/mwalczyk81/querylens.git
cd querylens
uv sync --locked
```

### 2. Install Pre-Commit Hooks

Formatting, linting, and typing run on every commit. Install the pre-commit git hooks:

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

### Code Coverage & Codecov

CI enforces a minimum 85% test coverage gate (`pytest --cov=querylens --cov-fail-under=85 -m "not integration"`). Coverage reports (`coverage.xml`) upload to [Codecov](https://codecov.io/gh/mwalczyk81/querylens) via the `codecov/codecov-action` step.

The workflow references `${{ secrets.CODECOV_TOKEN }}` to authenticate uploads with Codecov. The upload step sets `fail_ci_if_error: false`. If the secret is missing or the job runs in an external fork, the upload fails without failing the CI job. The local coverage gate in `pytest` remains authoritative. In addition, `codecov.yml` sets project and patch coverage checks to `informational: true`, so missing Codecov statuses do not block pull request merges.

### Type Checking

Run type checking with [Pyrefly](https://github.com/facebook/pyrefly):

```bash
uv run pyrefly check
```

### Offline Discovery Testing

Log Analytics discovery tests (KQL query construction, parameter validation, caller attribution, service orchestration, and output formatting) run offline without Azure network calls or credentials using synthetic fixtures:

```bash
uv run pytest tests/unit/test_discover_* tests/integration/test_discover_snapshots.py
```

### Live-Gate Policy & Synthetic Regression Fixtures

KQL queries are never executed against live Azure infrastructure in automated CI pipelines. Instead, releases and discovery features gate on the live workspace qualification procedure in `docs/manual-testing.md` and `docs/live-gate.md`.

Any code change that alters generated KQL queries (producing a diff in `tests/unit/__snapshots__/test_discover_kql_snapshots.ambr`) invalidates prior live qualification and requires re-executing the live workspace gate against a real workspace before merging or releasing.

Every discrepancy, edge case, or unexpected server serialization encountered during live-gate qualification must produce a regression fixture in `tests/fixtures/synthetic_logs.py` mirroring the server result shape with synthetic values only. Live findings are codified into offline regression tests.

### Regenerating README Assets

The terminal SVG demo in the README (`docs/assets/querylens-demo.svg`) is generated from sample run metrics (`docs/assets/sample-run.json`).

To regenerate the SVG from existing sample data:

```bash
uv run python scripts/gen_readme_assets.py
```

To re-run against the local emulator to refresh `sample-run.json` and the SVG:

```bash
uv run python scripts/gen_readme_assets.py --refresh
```

When refreshing sample run metrics, ensure the single-query `--json` excerpt in `README.md` is updated to match. A drift test in `tests/unit/test_readme_assets.py` runs in CI to verify byte-for-byte equality for the SVG and consistency of the README JSON excerpt against `sample-run.json`.

### Regenerating the Demo

The terminal GIF in the README Quickstart (`docs/assets/demo.gif`) is recorded from `docs/demo.tape`. Before recording, have the Cosmos DB emulator running and seeded (see [Local Cosmos DB Emulator Quickstart](#local-cosmos-db-emulator-quickstart)) The tape sets the two environment variables it needs, `QUERYLENS_ENDPOINT` and `QUERYLENS_COSMOS_KEY`, to the emulator's public defaults; edit the `Env` lines if your emulator differs. Then run:

```bash
vhs docs/demo.tape
```

This requires [vhs](https://github.com/charmbracelet/vhs), `ttyd` and `ffmpeg` on your `PATH`. Regeneration is not part of CI because it needs the emulator.

### Continuous Fuzzing (ClusterFuzzLite & Atheris)

To detect parser crashes, unhandled exceptions, and regressions, QueryLens integrates continuous fuzzing using [ClusterFuzzLite](https://google.github.io/clusterfuzzlite/) and [Atheris](https://github.com/google/atheris).

Fuzz targets live in `.clusterfuzzlite/`:

- `fuzz_query_metrics.py`: tests `parse_query_metrics_header` with arbitrary unicode strings for semicolon-delimited header parsing.
- `fuzz_index_utilization.py`: tests `parse_index_utilization_header` with arbitrary strings for Base64 decoding and JSON handling.
- `fuzz_kql_escaping.py`: tests `escape_kql_string` for KQL injection invariants (null stripping, quote/control character escaping).
- `fuzz_duration_parser.py`: tests `parse_duration_string` for bounds checks and clean `DiscoveryValidationError` handling.
- `fuzz_discovery_options.py`: tests `DiscoveryOptions` Pydantic validators.

Seed inputs live in `.clusterfuzzlite/*_seed_corpus.zip` to accelerate coverage exploration. The CI fuzzing workflow (`.github/workflows/cflite_pr.yml`) runs on pull requests targeting `main` in `code-change` mode with a 30-second time budget.

Atheris requires C runtime instrumentation linked against Clang's libFuzzer. It is omitted from `pyproject.toml` and developer virtual environments so Windows and macOS developers can install dependencies without C toolchain requirements. Atheris is installed only inside the base builder image (`gcr.io/oss-fuzz-base/base-builder-python`), which is pinned by SHA256 digest in `.clusterfuzzlite/Dockerfile`.

#### Pinned Build Inputs & Refreshing Pins

ClusterFuzzLite build inputs are pinned to prevent supply chain tampering and ensure reproducible fuzz builds:

1. **Docker Base Image**: The base image in `.clusterfuzzlite/Dockerfile` is pinned by SHA256 digest with the tag tracked in a comment:

   ```dockerfile
   # tag: latest
   FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:756c7196c97d62a66c448e70bdeecce400e68ae2ee96d4393cb38d58ffca18d2
   ```

   To look up and refresh the latest digest:

   ```bash
   docker buildx imagetools inspect gcr.io/oss-fuzz-base/base-builder-python:latest
   ```

2. **Python Dependencies & Hashes**: Runtime dependencies and the `hatchling` build backend are hash-pinned in `.clusterfuzzlite/requirements.txt` and verified via `pip install --require-hashes`. To refresh dependencies or update constraints, edit `.clusterfuzzlite/requirements.in` and recompile:

   ```bash
   uv pip compile .clusterfuzzlite/requirements.in --python-version 3.11 --generate-hashes --output-file .clusterfuzzlite/requirements.txt
   ```

   QueryLens itself is not installed via `pip install` inside the container; instead, `PYTHONPATH` is exported pointing to `$SRC/querylens/src` (and `--paths` is passed to `compile_python_fuzzer`), so fuzz targets import QueryLens directly from the source tree. This eliminates the need for `--ignore-requires-python` on the container's Python 3.11 runtime, while PyInstaller bundles the pure Python source into the compiled fuzz binaries.

3. **Dependabot Updates**: Dependabot monitors `/.clusterfuzzlite` weekly for both Docker base image updates (`docker` ecosystem) and Python dependency updates (`pip` ecosystem), grouping minor and patch updates under the `chore(fuzz)` commit prefix.

#### Running Fuzz Targets Locally

To run fuzz targets locally, use Docker or a Linux environment (such as WSL):

```bash
# Option A: Run via Docker (recommended on Windows / macOS)
docker build -t querylens-fuzz -f .clusterfuzzlite/Dockerfile .
docker run -it --rm querylens-fuzz python3 .clusterfuzzlite/fuzz_query_metrics.py -max_total_time=30

# Option B: Run in a Linux / WSL virtual environment with Atheris installed
pip install atheris
python .clusterfuzzlite/fuzz_query_metrics.py -max_total_time=30
```

---

## Local Cosmos DB Emulator Quickstart

To run the full integration suite or profile sample workloads locally, spin up the Linux Azure Cosmos DB emulator using Docker Compose:

### 1. Start the Emulator

```bash
docker compose up -d
```

Wait until the emulator endpoint becomes healthy (approximately 60-90 seconds):

```bash
curl -k -f https://localhost:8081/_explorer/emulator.pem
```

### 2. Seed Test Data

Run the seeding script to populate test containers across partitioned and unindexed schemas:

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

## CI/CD Security & Action Pinning Policy

In accordance with OpenSSF Scorecard recommendations:

- All third-party GitHub Actions across workflow files (`ci.yml`, `release.yml`, `scorecard.yml`, `dependency-review.yml`, `cflite_pr.yml`) must be pinned to 40-character commit SHAs, accompanied by an inline comment showing the tag or version (for example `uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`).
- Reusable workflows called via `workflow_call` cannot always be pinned by commit SHA if GitHub requires a tag, and some composite actions require external dependencies. Any exception must be documented in an inline workflow comment. QueryLens currently has no action-pinning exceptions; all actions are pinned by commit SHA.

---

## Spec-Driven Development Workflow

QueryLens was developed using the [Spec-Kit](https://github.com/mwalczyk/spec-kit) methodology, creating requirements specifications, design artifacts, and contracts before writing code. Feature definitions, research findings, data models, and test matrices live under `specs/` (such as `specs/001-cosmos-query-cost/`). When proposing new features or major changes, draft specification and task artifacts before implementation.
