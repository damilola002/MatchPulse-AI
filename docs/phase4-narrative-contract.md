# Phase 4 — Azure AI narrative generation contract

**Status:** Narrative domain, approved local demo API, and fake-provider tests are implemented locally and await final review. Phases 1–3 are complete, committed, and pushed.

Phase 4 converts selected, finalized Phase 3 insights into concise neutral English commentary. The application owns football facts. Azure AI may order approved claims and select exact application-owned wording, but it cannot author free-form text or change facts. All output remains labeled synthetic.

## Scope and boundaries

- Internal on-demand narrative service plus an explicitly enabled, loopback-only local demo POST route. No database table, migration, narrative persistence, SSE, personalization, recap workflow, or changes to Phase 1–3 contracts are introduced.
- Inputs are computed using the Phase 3 intelligence engine and shared Phase 2 replay path. Do not implement a second metric, insight, score, lifecycle, or possession reducer.
- Narrative kind is `match_insight_explanation`; language is `en`.
- Phase 5 owns presentation, Phase 6 personalization, and Phase 7 recap/multilingual workflows.

## Versioned contracts

Pydantic v1 domain contracts live in `src/matchpulse_sim/narrative/contracts.py`. The browser request contract is `NarrativeGenerationRequest`; it accepts the run ID, exact finalized `as_of`, and selected insight IDs only. Client-supplied claims or event evidence are prohibited. The response is `NarrativeResponseV1`.

### `NarrativeRequestV1`

The request includes `schema_version: 1`, `narrative_kind`, `language`, `match_id`, `simulation_run_id`, `synthetic: true`, exact `as_of` (`sequence`, `event_id`, `match_elapsed_ms`), and one or more `ApprovedClaimV1` records. Every claim must match the request's match, run, and complete snapshot marker.

An approved claim includes a stable `claim_id`, claim/rule kind and version, team ID and home/away role, period and event clock, structured observed facts, optional activity window, and exact ordered `evidence_event_ids`. Supported claim kinds map exactly to Phase 3 `score_change`, `shot_activity`, or `pressure_activity` insights. Claim facts use the Phase 3 fact field shapes.

Claim identity is `claim:v1:` plus SHA-256 of canonical JSON containing claim schema version, match/run identity, full finalized watermark, insight and rule identity, team, facts, window, and ordered evidence IDs. Repeated preparation for the same snapshot and selected insight yields the same claim ID.

### Evidence and snapshot rules

The caller supplies the exact `as_of` returned by Phase 3. Claim preparation reads the current match and finalized watermark in the caller's read-only transaction, then uses the existing finalized-prefix reader and `calculate_intelligence`. If the supplied marker differs from the current finalized snapshot, fail with `stale_snapshot`; do not silently move the request forward.

Selected insight IDs must exist in the recomputed Phase 3 output for the same match/run/snapshot. Every supporting event ID must resolve to a validated event within that finalized prefix. Reject unknown insights, missing/cross-match/cross-run evidence, duplicate IDs, and evidence beyond the finalized sequence. The Phase 3 engine/replay remains authoritative for event and insight meaning.

### `NarrativeResponseV1`

The response includes schema version, stable narrative ID, kind/language, match/run identity, `synthetic: true`, exact finalized marker, narrative contract version, non-secret provider/model metadata, prompt version, and ordered blocks. Each block contains exactly one approved claim ID, its Phase 3 insight ID, exact supporting event IDs, and application-rendered text.

The narrative ID is `narrative:v1:` plus SHA-256 of canonical JSON containing the versioned request, rendered blocks, provider/model identifiers, and prompt version. This is a content identity, not a promise that model selection will be reproducible across independent calls.

## Claim grounding and wording validation

The application builds claims only from validated Phase 3 insight records and finalized event evidence. v1 supports:

- Score changes: score before/after, scoring team role, goal event evidence.
- Shot activity: threshold count, team role, period, inclusive event-time window, exact shot event evidence.
- Pressure activity: threshold count, team role, period, inclusive event-time window, exact pressure event evidence.

The provider receives structured claims and the application-generated allowed phrase variants. It returns only a complete ordering of claim IDs and exact phrase strings selected from those variants. The application validates exact claim coverage, uniqueness, and byte-for-byte phrase membership, then attaches trusted insight/evidence IDs and returns the selected text. Additional, altered, or unsupported model text is rejected as `unsupported_factual_assertion`; it is never returned or silently replaced with fallback commentary.

This deliberately limits linguistic variation. It gives deterministic application-owned factual wording and avoids treating a JSON schema or a second model judge as proof of grounding. New claim kinds or free-form paraphrasing require a reviewed contract and a stronger validation design.

## Provider boundary and Azure configuration

`NarrativeProvider` is an async provider-neutral protocol. `DeterministicFakeProvider` provides local deterministic behavior. `AzureOpenAIProvider` calls the Azure OpenAI-compatible `POST {endpoint}/openai/v1/chat/completions` route with structured JSON output. The deployment name is sent as `model`; API version is not separately required on this v1 route. See the [Microsoft REST reference](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/chat).

The adapter requires these external environment values:

- `MATCHPULSE_AZURE_OPENAI_ENDPOINT`: HTTPS Azure resource endpoint; no path, query, fragment, or embedded credentials.
- `MATCHPULSE_AZURE_OPENAI_DEPLOYMENT`: configured deployment name.
- `MATCHPULSE_AZURE_OPENAI_API_KEY`: local/runtime credential; never tracked, logged, or returned.

No endpoint, deployment, API key, region, SDK, or live Azure access is needed to import the package or run core tests. The adapter uses the pinned `httpx` runtime dependency and supports an injected mock transport. Do not send PostgreSQL URLs, local secrets, or raw unrelated event logs to Azure.

The local API route is `POST /api/matches/{match_id}/narratives`. It is disabled unless `MATCHPULSE_DEMO_MODE=true`, rejects non-loopback clients/hosts, and remains unauthenticated; it must not be publicly exposed. Provider selection is `MATCHPULSE_NARRATIVE_PROVIDER=fake|azure`, defaults to `fake`, and Azure is constructed only when explicitly selected. The route performs claim preparation inside a read-only transaction and verifies the requested run and snapshot. HTTP failures use the stable error shape and do not return fallback commentary. The Vite app receives no Azure credentials.

## Resource budgets and retry policy

Defaults are intentionally bounded. Insight, claim, request/response, token, and concurrency limits may be lowered through the matching `MATCHPULSE_NARRATIVE_*` environment settings; values outside their ceilings fail closed. Attempt timeout, retry delay, and total duration are fixed in v1 rather than environment-configurable.

| Limit | Default | Hard ceiling |
|---|---:|---:|
| Selected insights | 10 | 10 |
| Approved claims | 20 | 20 |
| Serialized provider request | 256 KiB | 256 KiB |
| Provider response body | 64 KiB | 64 KiB |
| Output tokens | 512 | 512 |
| Concurrent generations per service instance | 4 | 4 |
| Timeout per provider attempt | 15 seconds | 15 seconds |
| Retry delay | 0.25 seconds | 0.25 seconds |
| Total operation duration, including queue, retries, and delay | 31 seconds | 31 seconds |

The service makes at most two attempts. Retry only explicitly transient provider timeout/network failures and HTTP 429, 502, 503, or 504. Do not retry authentication/authorization failures, other client errors, malformed JSON, invalid structured output, unsupported claims, or size violations. The concurrency wait counts against total duration. No live-provider retry is performed in tests.

## Safe failures

Internal errors are `NarrativeError` with stable safe codes. They do not include endpoint values, credentials, raw provider bodies, prompts, or event payloads. Relevant codes include `read_only_transaction_required`, `invalid_narrative_request`, `empty_insight_selection`, `unknown_insight`, `stale_snapshot`, `unfinalized_evidence`, `narrative_input_limit`, `narrative_provider_not_configured`, `provider_timeout`, `provider_unavailable`, `rate_limited`, `authentication_failed`, `invalid_provider_output`, `unsupported_claim_reference`, `unsupported_factual_assertion`, and `narrative_output_limit`.

No provider failure returns a fabricated or template fallback. Application-owned templates are only used for exact wording options supplied to the provider and validated before output.

## Testing and acceptance

Core tests use the deterministic fake and SQLite where database evidence resolution is needed. HTTP tests exercise the explicit route gate and fake provider; Azure adapter tests use `httpx.MockTransport` and never call live Azure or require credentials. Tests cover stable claim IDs, finalized snapshot/evidence checks, stale/cross-scope rejection, exact references, request/response/concurrency limits, deterministic fake output, exact wording rejection, malformed structured output, timeout/retry classification, rate limits, auth failures, oversized responses, and secret-safe errors.

Acceptance requires:

- Every output claim is prepared from the current finalized Phase 3 snapshot and carries exact evidence references.
- Existing Phase 1–3 public schemas, behavior, and tests remain unchanged.
- Provider output cannot add, alter, omit, or duplicate facts/claims; only the order and approved wording choice may vary.
- Limits, safe error classifications, and no-live-Azure test behavior are verified.
- `.env` stays untracked and no credential appears in repository content or logs.
