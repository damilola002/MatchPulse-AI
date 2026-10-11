# Security and environment configuration

## Local configuration

- `POSTGRES_PASSWORD` is intentionally blank in `.env.example`. Developers must set a non-empty local password in their untracked `.env`; Compose rejects missing or blank password configuration. Never commit the local database password or a populated `.env` file.
- No actual passwords belong in documentation or source control. Compose receives database configuration through environment substitution; credentials are not embedded in Compose. The host port binds to `127.0.0.1` by default.
- Do not place secrets in source, docs, examples, test fixtures, logs, screenshots, or generated artifacts. Rotate any secret accidentally exposed.
- `.gitignore` and `.dockerignore` exclude environment files, key/certificate formats, local data, caches, and build artifacts.

## Application and data controls (planned)

- Validate configuration at startup and fail clearly when required values are absent or malformed.
- Give application and migration identities only the database privileges they need; separate credentials where appropriate.
- Validate event schemas and size/range bounds at the ingestion boundary. Preserve provenance and audit-relevant evidence references.
- Restrict access to match streams and narrative generation according to an approved authorization design.
- Keep tokens, personal data, and sensitive prompt content out of routine logs. Define retention and deletion policies before deployment.
- Bound Azure AI calls with timeouts, rate/cost controls, output validation, and safe failure behavior. Treat model output as untrusted data.

## Azure deployment (future phase)

Before deployment, approve Azure service selection, region, identity model, network exposure, secret storage, TLS, backup/retention, monitoring, cost limits, and incident/rollback procedures. Prefer managed identity and a managed secret store over application-stored cloud credentials. Local Compose configuration is not a production deployment recipe.

## Synthetic content

Clearly label all generated match data as synthetic in persisted provenance, API/event metadata, dashboards, broadcast graphics, recaps, and exported content. Do not imply affiliation, official status, or live real-world accuracy.
