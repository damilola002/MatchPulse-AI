# Security and environment configuration

## Local configuration

- `POSTGRES_PASSWORD` is intentionally blank in `.env.example`. Developers must set a non-empty local password in their untracked `.env`; Compose rejects missing or blank password configuration. Never commit the local database password or a populated `.env` file.
- No actual passwords belong in documentation or source control. Compose receives database configuration through environment substitution; credentials are not embedded in Compose. The host port binds to `127.0.0.1` by default.
- The Phase 2 API reads the same local database configuration and binds to `127.0.0.1:8001`. It has no authentication and is intended for local development only.
- API request bodies are capped at 1 MiB before JSON parsing and event batches at 100. These bounds limit local resource use and are not an abuse-control system.
- PostgreSQL integration tests require `MATCHPULSE_TEST_DATABASE_URL` and an explicit `MATCHPULSE_TEST_DATABASE_NAME`. The normalized host, port, and database name must differ from the development target; a `_test` suffix alone is not sufficient. Tests clean up only their uniquely created schema.
- Alembic requires explicit `MATCHPULSE_MIGRATION_TARGET=development` or `test`. Test migrations also require a matching `MATCHPULSE_TEST_MIGRATION_CONFIRM` value and verify the connected database target before executing. The application does not run migrations automatically. Database passwords must not be logged.
- Event-page responses are capped at 1 MiB and 100 events. An event that cannot fit as the first page item returns a non-retryable 413 with the blocking cursor position instead of being skipped.
- The Phase 3 intelligence API requires `MATCHPULSE_INTELLIGENCE_CURSOR_KEY` from untracked local/runtime configuration. Supply an unpadded base64url encoding of at least 32 random bytes and keep it stable while cursors are valid. The endpoint fails closed when it is missing or invalid; never log or commit the key. Rotation invalidates existing cursors.
- Do not place secrets in source, docs, examples, test fixtures, logs, screenshots, or generated artifacts. Rotate any secret accidentally exposed.
- `.gitignore` and `.dockerignore` exclude environment files, key/certificate formats, local data, caches, and build artifacts.

## Application and data controls

- Validate database configuration when starting the API and fail clearly when required values are absent or malformed.
- Give application and migration identities only the database privileges they need; separate credentials where appropriate.
- Validate event schemas and size/range bounds at the ingestion boundary. Preserve provenance and audit-relevant evidence references.
- Restrict access to match streams and narrative generation according to an approved authorization design.
- Keep tokens, personal data, and sensitive prompt content out of routine logs. Define retention and deletion policies before deployment.
- Bound Azure AI calls with timeouts, rate/cost controls, output validation, and safe failure behavior. Treat model output as untrusted data.

## Azure deployment (future phase)

Before deployment, approve Azure service selection, region, identity model, network exposure, secret storage, TLS, backup/retention, monitoring, cost limits, and incident/rollback procedures. Prefer managed identity and a managed secret store over application-stored cloud credentials. Local Compose configuration is not a production deployment recipe.

## Synthetic content

Clearly label all generated match data as synthetic in persisted provenance, API/event metadata, dashboards, broadcast graphics, recaps, and exported content. Do not imply affiliation, official status, or live real-world accuracy.
