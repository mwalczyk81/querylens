# Security Policy

## Supported Versions

Only the latest active minor release line receives security updates and patches.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

We take the security of QueryLens seriously. If you identify a security vulnerability, please report it responsibly:

- **Do NOT open a public GitHub issue, pull request, or discussion** for potential security vulnerabilities.
- **Use GitHub Private Vulnerability Reporting**: Navigate to the [Security Advisories](https://github.com/mwalczyk81/querylens/security/advisories/new) page of the repository and click **Report a vulnerability**.
- Provide a detailed description of the vulnerability, steps to reproduce, impact assessment, and any proof-of-concept material.

### Expected Response Times

- **Initial Acknowledgment**: Within 48 hours of receipt.
- **Triage & Status Assessment**: Within 7 business days with a confirmation of whether the issue is reproducible and its severity.
- **Fix & Disclosure Target**: We aim to provide a security patch release within 30 days of confirmed triage, coordinated with responsible public disclosure.

## Security Posture & Architecture

QueryLens is designed with privacy-first and defense-in-depth principles:

- **Strictly Read-Only Queries**: QueryLens only issues read queries (`SELECT`) to Azure Cosmos DB. It never invokes mutate, update, insert, or delete operations.
- **Immediate Payload Discard**: When executing queries, item document payloads returned by the SDK are discarded immediately during streaming page iteration (`for _ in page: pass`). QueryLens never caches, persists, logs, or exports item document bodies to disk or external services.
- **Authentication Safeguards**:
  - **Local Emulator Only**: Master key authentication (`QUERYLENS_COSMOS_KEY` or `--key`) is strictly restricted to local emulator endpoints (`localhost` or `127.0.0.1`). Any attempt to use master keys against a remote Azure Cosmos DB account is rejected.
  - **Passwordless `DefaultAzureCredential`**: Remote endpoints enforce Microsoft Entra ID passwordless authentication via `DefaultAzureCredential`.
- **Sensitive Data Scrubbing**: Local emulator keys and credentials are encapsulated in Pydantic `SecretStr` models to prevent accidental serialization into logs or error messages. Structured logs route strictly to `stderr` with sensitive payload dictionaries scrubbed.
- **Transport Security**: Remote endpoints require secure `https://` transport schemes.
