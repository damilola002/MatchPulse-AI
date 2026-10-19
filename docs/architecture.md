# Architecture

## Status and baselines

Phases 1 and 2 are implemented, reviewed, committed, and pushed. Phase 3 implementation and local test verification complete; awaiting final review, commit, and push. The reported full-suite result is 82 passed, 0 failed, and 55 warnings. The frontend, Azure AI narratives, personalization, recaps, and deployment remain planned. Initial baselines are Python 3.12 and Node.js 22 LTS with React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. Backend dependency versions are pinned in `pyproject.toml`; Azure model, region, and deployment topology remain undecided.

## Current implementation boundary

The `src/matchpulse_sim` Python package generates entirely fictional events from immutable configuration and fictional team/player fixtures. It uses a local SplitMix64 PRNG, derives stable run/event identities, validates every event against the packaged JSON Schema v1, and emits canonical JSON or JSONL. A shared reducer validates complete streams and incremental prefixes. Phase 2 adds HTTP ingestion, PostgreSQL event persistence and stable state projection, finalized-event SSE, and a local playback CLI. The browser frontend, advanced analytics beyond Phase 3, Azure integration, and production deployment remain planned. Phase 3 deterministic match statistics and explainable insight detection have been implemented and locally tested, but have not yet been committed or pushed.

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

The implemented generator provides a seed/run identity so a simulation can be reproduced. Phase 2 validates schema version and match scope, enforces sequence ordering and idempotency, and persists a rebuildable projection. Phase 3 derives synthetic event-count metrics and three deterministic, evidence-linked insight rules from the finalized prefix. Its read-only API is on-demand and does not alter the Phase 2 raw-event SSE contract. Narrative Generation will later receive structured evidence and output constraints through a provider adapter. Personalized Presentation will choose the approved audience representation without changing underlying facts.

## Planned boundaries

- **Domain and event contracts:** synthetic event JSON Schema v1 is implemented and packaged; unsupported versions and unknown fields are rejected. Phase 2 API contracts are exposed through FastAPI OpenAPI.
- **Backend:** FastAPI exposes match start, batch ingestion, state, event-page, SSE, and Phase 3 read-only intelligence routes. OpenAPI exposes API contracts; Phase 3 metrics/rules consume only the finalized prefix. Narratives remain a later phase.
- **Persistence (Phase 2 implemented):** PostgreSQL is the authoritative append-only event log and stores the Match State projection, run metadata, canonical digests, and reducer checkpoints. SQLAlchemy provides data access and Alembic migration source defines the schema; migration execution requires explicit approval.
- **Frontend:** React + TypeScript + Vite consumes backend APIs and SSE; it renders dashboards and overlays, with synthetic labeling always visible.
- **AI provider:** application-owned abstraction accepts bounded evidence and returns structured candidate narrative output. Azure-hosted AI is one provider; validation and evidence association stay in application code.
- **Phase 3 intelligence (implemented locally; local test verification reported complete; awaiting final review, commit, and push):** pure deterministic metrics and rule functions consume only events through a captured Phase 2 finalized watermark. Results are derived on demand from the append-only log with bounded input (10,000 events/16 MiB), at most 100 insights and 1 MiB per response page. Pagination uses an HMAC-protected cursor pinned to match/run, rule versions, finalized watermark, page limit, and sort position. Goals-per-shot uses a four-place decimal string rounded half-even. Activity episodes use inclusive 600,000 ms within-half windows and rearm on any finalized match-clock advance. No intelligence table or intelligence SSE is introduced; Phase 2 raw-event SSE is unchanged. See [the Phase 3 contract](phase3-intelligence-contract.md).
- **Local infrastructure:** Docker Compose defines only PostgreSQL with a named volume, environment-based credentials, a health check, and explicit loopback host binding. The Phase 2 API is started separately on loopback; no application containers are defined.
- **Deployment:** Azure deployment is a later phase. Managed identity, secret storage, network boundaries, observability, and cost controls must be settled before deployment.

## Local port assignments

MatchPulse AI reserves these development ports to avoid conflicts with other projects on the same machine:

| Component | Development host port | Current status |
|---|---:|---|
| PostgreSQL | `5434` | Defined in Compose, bound to `127.0.0.1` |
| FastAPI | `8001` | Phase 2 local API default; loopback only |
| Vite | `5174` | Planned for a future phase; no frontend service exists |

The PostgreSQL container continues to listen on port `5432` internally. The host port can be changed with `POSTGRES_HOST_PORT`; its bind address remains fixed to loopback. The API is not a Compose service.

## Data and delivery flow

The event is the durable evidence record. Every processed event has stable identity and a match-scoped timestamp/order. Replays use the same deterministic ordering and event identity; duplicate events must not double-apply. Derived state can be rebuilt from accepted events. Statistics and insights retain references to source event identifiers (or an explicitly described evidence set). Narratives retain the insight/evidence identifiers and model/provider metadata needed for audit, subject to privacy/security review.

SSE messages use Phase 1 event IDs as cursors. A monotonically advancing sequence serves committed history and live arrivals; clients may deduplicate at-least-once delivery. Connections are bounded, poll at a fixed interval, heartbeat, and close after full-time. Retention reset/snapshot recovery is not implemented.

## Operational qualities

Planned operational requirements include bounded event processing latency, observable lag and validation failures, deterministic replay, graceful provider timeouts/fallback behavior, rate and cost limits for AI calls, database backups for deployed state, and accessibility/performance checks for live presentation. Concrete targets should be approved before implementation and deployment.
