# Live Workspace Qualification Gate Prompt

This prompt is pasted into Claude Code after the user has signed in to Azure (e.g. via Britive or `az login`).

It instructs Claude Code to run non-destructive, read-only validation against a real, non-production Azure Log Analytics workspace containing Cosmos DB diagnostic logs.

**Regression Fixture Policy**: Every live-gate finding must produce a regression fixture mirroring the REAL server result shape, with synthetic values.

```text
You are validating querylens on the checked-out branch against a real, NON-PRODUCTION Azure Log Analytics workspace that contains Cosmos DB diagnostic logs. I have already signed in to Azure myself (Britive / az login). querylens is read-only.

SAFETY RULES
- Never handle credentials, tokens or keys. Do not run az login or Britive commands. Check the session with "az account show" and summarize only the account and subscription names.
- Never display raw query text. Run "querylens discover" ONLY with --json and redirect stdout to a file in the querylens-work folder in my home directory (outside the repo). Never use --show-text. If any output contains SQL-looking text (SELECT, FROM, WHERE), stop immediately, say so, and do not quote it.
- Do not modify, commit or push anything in the repo. Notes go in querylens-work/live-gate-notes.md.
- Ask me for the workspace id and the Cosmos account name; never guess them. Ask before installing anything (including az extensions).

STEPS
1. Run "uv sync --locked" and "uv run pytest -q -m 'not integration'" to confirm the environment works.
2. Run "uv run querylens discover -w <workspace-id> --check" and then the same with --json. Report: exit code, which categories exist, row counts, first and last timestamps, percent populated for each column checked, and the authTokenType breakdown. If it fails with a KQL error, copy the exact error message (column names and positions are safe to quote), then STOP.
3. Run "uv run querylens discover -w <workspace-id> --time-window 1h --top 10 --json > <querylens-work>/out-1h.json" (stderr may show). Then use a small script to print ONLY numeric fields and shape ids from the file: number of shapes, total RU, unattributed RU and percent, retention warning if any, and for the top 5 shapes: shape id, executions, total RU, average RU, max RU, RU share, returned rows, throttled count. Confirm the JSON has no sample_query_text keys.
4. Repeat step 3 with --account <name>, and again with --time-window 24h. Record wall-clock time for each run.
5. Cross-check one number independently: with "az monitor log-analytics query" (ask before installing the extension if needed) run an aggregate-only KQL query that sums todouble(requestCharge_s) for Category == "DataPlaneRequests" over the same 1h window and account, and compare with the window total RU querylens reported. Report the percentage difference.
6. Negative tests: run discover with a random but valid GUID as workspace id (expect a clean error and the documented exit code, no stack trace), and with --top 0 (expect exit 1).

FINAL REPORT (show me and save to live-gate-notes.md)
- Commit SHA (git rev-parse HEAD) and versions of uv, Python and az.
- For every command: exit code and duration.
- Any KQL or SDK error text, verbatim.
- RU cross-check difference.
- Column population percentages and authTokenType breakdown.
- Verdicts: --check works yes/no, discover works yes/no, silent-zero guard did not trigger yes/no, JSON contained no query text yes/no, negative tests clean yes/no.
```
