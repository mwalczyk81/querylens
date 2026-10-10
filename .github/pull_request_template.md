## Summary

<!-- Provide a concise description of the changes introduced by this pull request. Explain the rationale and approach. -->

## Test Evidence

<!-- Provide proof of testing: command output, test counts, coverage report, or emulator integration test results. -->

- `uv run pre-commit run --all-files`
- `uv run pytest --cov=querylens --cov-fail-under=85`

## Contract & Exit Code Changes

<!-- Note any updates to exit code semantics or the JSON schema contract (specs/001-cosmos-query-cost/contracts/run-output-schema.json). If none, indicate "None". -->

## Checklist

- [ ] All pre-commit hooks pass cleanly (`ruff`, `ruff-format`, `markdownlint-cli2`, `pyrefly`).
- [ ] Pyrefly strict type check passes with 0 errors.
- [ ] Test suite passes with >= 85% coverage (`pytest --cov=querylens`).
- [ ] Documentation (`README.md`) and relevant ADRs (`docs/adr/`) updated for any behavioral or interface changes.
- [ ] Any exit code hierarchy or JSON contract alterations documented.
