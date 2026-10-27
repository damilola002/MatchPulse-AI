# Architecture

## Status and baselines

Phases 1–3 are implemented, reviewed, committed, and pushed. Phase 4 narrative generation and the minimum Phase 5 dashboard are implemented locally and await final review; Phases 6–8 remain planned. Initial baselines are Python 3.12 and Node.js 22 LTS with React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. Backend dependencies are pinned in `pyproject.toml`; frontend dependencies are pinned under `frontend/`. Vite's selected baseline requires Node.js 22.12 or newer within the Node 22 line.

## Current implementation boundary

The `src/matchpulse_sim` Python package generates entirely fictional events from immutable configuration and fictional team/player fixtures. It uses a local SplitMix64 PRNG, derives stable run/event identities, validates every event against the packaged JSON Schema v1, and emits canonical JSON or JSONL. A shared reducer validates complete streams and incremental prefixes. Phases 2–3 add HTTP ingestion, PostgreSQL event persistence and stable state projection, finalized-event SSE, playback, deterministic match statistics, and evidence-linked insights. Phase 4 adds an on-demand narrative service and an explicitly enabled, loopback-only POST route; generated narratives are not persisted. Phase 5 adds a local React dashboard that consumes existing APIs and SSE. Personalization, recaps, Azure deployment, and advanced analytics beyond Phase 3 remain planned.

## Logical pipeline

```text
Synthetic Event Generator
          ↓ versioned synthetic events
       Ingestion [Phase 2 implemented]
          ↓ validated, idempotent, ordered events
      Match State [Phase 2 implemented]
          ↓ current projection and replay position
       Statistics
          ↓ deterministic metrics
   Insight Detection
          ↓ evidence-linked insight
 Narrative Generation ← provider abstraction → Azure-hosted AI
          ↓ validated grounded narrative
     Live Delivery
          ↓ SSE stream
Personalized Presentation
          ├── fan dashboard
          ├── analyst view
          └── broadcaster overlays
```

The implemented generator provides a seed/run identity so a simulation can be reproduced. Phase 2 validates schema version and match scope, enforces sequence ordering and idempotency, and persists a rebuildable projection. Phase 3 derives synthetic event-count metrics and three deterministic, evidence-linked insight rules from the finalized prefix. Its read-only API is on-demand and does not alter the Phase 2 raw-event SSE contract. Phase 4 prepares approved claims from those Phase 3 outputs and uses an Azure OpenAI-compatible provider only to order claims and select from exact application-owned wording options. The application renders the returned narrative blocks and preserves their claim, insight, and event references. Personalized Presentation will later choose the approved audience representation without changing underlying facts.

## Planned boundaries

- **Domain and event contracts:** synthetic event JSON Schema v1 is implemented and packaged; unsupported versions and unknown fields are rejected. Phase 2 API contracts are exposed through FastAPI OpenAPI.
- **Backend:** FastAPI exposes match start, batch ingestion, state, event-page, SSE, Phase 3 read-only intelligence, and a local-demo-only narrative POST route. The new route requires `MATCHPULSE_DEMO_MODE=true`, checks loopback access, defaults to the deterministic fake provider, resolves claims from a read-only finalized snapshot, and does not persist output.
- **Persistence (Phase 2 implemented):** PostgreSQL is the authoritative append-only event log and stores the Match State projection, run metadata, canonical digests, and reducer checkpoints. SQLAlchemy provides data access and Alembic migration source defines the schema; migration execution requires explicit approval.
- **Frontend (Phase 5 local implementation):** React + TypeScript + Vite consumes backend APIs and unchanged finalized-event SSE. It renders the scoreboard, event timeline, supported Phase 3 metrics, evidence-linked insights, connection state, and explicit narrative generation. Replayed SSE events are deduplicated by exact event ID. When local demo mode is enabled, controls call the loopback-only demo playback API to generate a unique match and start the existing playback helper. The copyable CLI command remains available as a fallback; no new ingestion or SSE contract is introduced.
- **AI provider (Phase 4 implemented locally; awaiting review):** a provider-neutral async interface calls an Azure OpenAI-compatible Chat Completions adapter. The provider selects ordering and exact wording only from approved application templates; application code constructs factual text and attaches provenance. No model-supplied free-form prose is accepted.
- **Phase 3 intelligence (implemented, committed, and pushed):** pure deterministic metrics and rule functions consume only events through a captured Phase 2 finalized watermark. Results are derived on demand from the append-only log with bounded input (10,000 events/16 MiB), at most 100 insights and 1 MiB per response page. Pagination uses an HMAC-protected cursor pinned to match/run, rule versions, finalized watermark, page limit, and sort position. Goals-per-shot uses a four-place decimal string rounded half-even. Activity episodes use inclusive 600,000 ms within-half windows and rearm on any finalized match-clock advance. No intelligence table or intelligence SSE is introduced; Phase 2 raw-event SSE is unchanged. See [the Phase 3 contract](phase3-intelligence-contract.md).
- **Phase 4 narrative service (implemented locally; awaiting review):** selected insights are recalculated from the finalized prefix using the existing Phase 3 engine and replay. Claims have stable identities and exact source event IDs. Provider output is limited to ordering and selecting exact application-owned wording options; arbitrary model text is rejected. No narrative table or SSE change is introduced. The POST route is for the loopback demo only, not production-authenticated.
- **Local infrastructure:** Docker Compose defines only PostgreSQL with a named volume, environment-based credentials, a health check, and explicit loopback host binding. The Phase 2 API is started separately on loopback; no application containers are defined.
- **Deployment:** Azure deployment is a later phase. Managed identity, secret storage, network boundaries, observability, and cost controls must be settled before deployment.

## Local port assignments

MatchPulse AI reserves these development ports to avoid conflicts with other projects on the same machine:

| Component | Development host port | Current status |
|---|---:|---|
| PostgreSQL | `5434` | Defined in Compose, bound to `127.0.0.1` |
| FastAPI | `8001` | Phase 2 local API default; loopback only |
| Vite | `5174` | Implemented local Phase 5 development server, bound to `127.0.0.1`; started separately from Compose |

The PostgreSQL container continues to listen on port `5432` internally. The host port can be changed with `POSTGRES_HOST_PORT`; its bind address remains fixed to loopback. The API is not a Compose service.

## Data and delivery flow

The event is the durable evidence record. Every processed event has stable identity and a match-scoped timestamp/order. Replays use the same deterministic ordering and event identity; duplicate events must not double-apply. Derived state can be rebuilt from accepted events. Statistics and insights retain references to source event identifiers (or an explicitly described evidence set). Phase 4 narratives are ephemeral and retain exact insight/evidence identifiers in the response; any future narrative retention requires a separate privacy/security decision.

SSE messages use Phase 1 event IDs as cursors. A monotonically advancing sequence serves committed history and live arrivals; clients may deduplicate at-least-once delivery. Connections are bounded, poll at a fixed interval, heartbeat, and close after full-time. Retention reset/snapshot recovery is not implemented.

## Operational qualities

Planned operational requirements include bounded event processing latency, observable lag and validation failures, deterministic replay, graceful provider timeouts/fallback behavior, rate and cost limits for AI calls, database backups for deployed state, and accessibility/performance checks for live presentation. Concrete targets should be approved before implementation and deployment.
