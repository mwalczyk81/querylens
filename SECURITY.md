# Security Policy

## Supported Versions

Only the latest active minor release line receives security updates and patches.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

If you identify a security vulnerability, please report it responsibly:

- Do not open a public GitHub issue, pull request, or discussion for security vulnerabilities.
- Use GitHub Private Vulnerability Reporting: navigate to the [Security Advisories](https://github.com/mwalczyk81/querylens/security/advisories/new) page of the repository and click **Report a vulnerability**.
- Provide a description of the vulnerability, reproduction steps, impact assessment, and any proof-of-concept material.

### Expected Response Times

- Initial acknowledgment: within 48 hours of receipt.
- Triage and status assessment: within 7 business days, confirming whether the issue is reproducible and assessing severity.
- Fix and disclosure: target a security patch release within 30 days of confirmed triage, coordinated with public disclosure.

## Security Posture & Architecture

QueryLens follows several security and privacy practices:

- QueryLens issues read queries (`SELECT`) to Azure Cosmos DB only. It never invokes write, update, or delete operations.
- Item document payloads returned by the SDK are discarded immediately during streaming page iteration (`for _ in page: pass`). QueryLens never caches, persists, logs, or exports item document bodies to disk or external services.
- Authentication safeguards:
  - Master key authentication (`QUERYLENS_COSMOS_KEY` or `--key`) is restricted to local emulator endpoints (`localhost` or `127.0.0.1`). Any attempt to use master keys against a remote Azure Cosmos DB account is rejected.
  - Remote endpoints require Microsoft Entra ID passwordless authentication via `DefaultAzureCredential`.
- Local emulator keys and credentials use Pydantic `SecretStr` models to prevent serialization into logs or error messages. Structured logs route to `stderr` with sensitive payload dictionaries scrubbed.
- Remote endpoints require `https://` transport schemes.
