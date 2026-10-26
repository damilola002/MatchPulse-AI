# Decision 0002: Phase 4 grounded narrative provider boundary

- **Status:** Accepted for the authorized Phase 4 implementation.
- **Date:** 2026-10-20
- **Decision owners:** Project owner

## Context

Phase 4 must turn Phase 3 finalized insights into concise neutral English language without allowing model output to become a new match fact. The service is internal and on demand. There is no approved narrative endpoint, persistence, frontend, or SSE.

## Decision

- Use a provider-neutral async protocol with a deterministic local fake.
- Implement an Azure OpenAI-compatible Chat Completions adapter using the `/openai/v1/chat/completions` route and structured JSON-schema output. The endpoint and deployment are environment configuration; no API version query is required for the v1 route.
- Use the externally configured API key for local/runtime Azure authentication. Do not include a credential, endpoint, deployment, or model name in source.
- Keep `httpx==0.28.1` as the existing pinned dependency and make it a runtime dependency for the adapter. Tests use `httpx.MockTransport`; no SDK, live Azure call, or credentials are needed for core tests.
- Provider output may order approved claims and select exact application-owned neutral wording. It may not return free-form prose. The application renders factual blocks and attaches trusted claim, insight, and event references.
- Prepare claims from the current Phase 3 finalized snapshot and resolve all event evidence within the same caller-owned read-only database transaction.
- Keep narratives ephemeral: no database table, new public API route, or SSE change in Phase 4.
- Apply documented request/response/token/concurrency/time budgets and no more than one retry for explicitly eligible transient failures.

## Consequences

Facts remain deterministic and auditable, and the Azure adapter can be tested offline. Language variation is deliberately narrow: a model chooses a safe phrase option instead of writing arbitrary prose. A future decision is required before free-form text, narrative storage, endpoint exposure, audience-specific output, or recap generation.

## References

- [Phase 4 narrative contract](../phase4-narrative-contract.md)
- [Microsoft Azure OpenAI Chat Completions REST reference](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/chat)
