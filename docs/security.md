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
- Phase 4 Azure narrative credentials are optional and must be supplied only through untracked local `.env` or a runtime secret store using `MATCHPULSE_AZURE_OPENAI_API_KEY`. Endpoint and deployment are also environment configuration; no endpoint or credential is hardcoded. The adapter sends only bounded approved synthetic claims, never a full event log or database configuration. Do not log prompts, response bodies, keys, or raw events.
- The Phase 4 narrative HTTP route is disabled unless `MATCHPULSE_DEMO_MODE=true`, requires loopback client and host addresses, and is still unauthenticated. Do not expose it outside the local hackathon demo. `MATCHPULSE_NARRATIVE_PROVIDER` defaults to `fake`; choosing `azure` is explicit and keeps the Azure key server-side. The route accepts only snapshot identity and insight IDs, recomputes claims/evidence from the finalized log in a read-only transaction, and returns ephemeral bounded output.
- The Phase 5 browser has no secrets or Azure configuration. Its Vite dev server binds to `127.0.0.1:5174`; its `/api` proxy targets the loopback backend. Browser EventSource uses the existing finalized-only SSE route and stable event IDs.
- The local `POST /api/demo/playbacks` and status routes are disabled unless `MATCHPULSE_DEMO_MODE=true`. They require loopback client and Host addresses, accept only the configured API/Vite ports, and the playback route enforces the shared 1 MiB request limit plus strict scenario, nonnegative signed-BIGINT seed, speed, and UUIDv4 request-ID validation. Only one synthetic run may be active per backend process; at most 32 recent request records are retained in memory. The server uses a fixed loopback API target for the existing playback helper. These routes are unauthenticated: bind FastAPI and Vite only to loopback, do not publicly expose them, and do not treat CORS as authentication. The browser cannot supply events, claims, evidence, provider settings, or credentials through this control.
- Phase 4 accepts provider output only as claim IDs and exact application-owned wording options. The application renders text from validated facts and rejects arbitrary model prose. This limits factual invention; it does not constitute general factuality checking for future free-form generation.
- Narrative generation is bounded to 10 insights, 20 claims, 256 KiB request, 64 KiB provider response, 512 output tokens, four concurrent calls per service instance, 15 seconds per attempt, one eligible retry, and 31 seconds total. No fallback commentary is fabricated on provider failure.
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
