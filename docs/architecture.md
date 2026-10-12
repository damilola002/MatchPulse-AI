# Architecture

## Status and baselines

The end-to-end product remains planned, with the Phase 1 offline generator and pure replay reducer implemented. Initial baselines are Python 3.12 and Node.js 22 LTS with React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. Generator package dependencies are pinned in `pyproject.toml`; other components' exact versions, Azure model, region, and deployment topology remain undecided.

## Current implementation boundary

The `src/matchpulse_sim` Python package generates entirely fictional events from immutable configuration and fictional team/player fixtures. It uses a local SplitMix64 PRNG, derives stable run/event identities, validates every event against the packaged JSON Schema v1, and emits canonical JSON or JSONL. A pure reducer validates complete streams and derives lifecycle state, score, current possession, and shot counts. This code has no network, database, web, Azure, or frontend integration. Everything after generation/replay in the pipeline below remains planned.

## Logical pipeline

```text
Synthetic Event Generator
          ↓ versioned synthetic events
       Ingestion
          ↓ validated, deduplicated, ordered events
      Match State
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

The implemented generator provides a seed/run identity so a simulation can be reproduced, and the local reducer replays a full stream. Future ingestion will validate schema version and match scope, assign deterministic ordering, and handle duplicate delivery idempotently. Persistent Match State will maintain a replayable projection. Statistics will derive from that state. Insight Detection will apply deterministic, documented rules and store evidence references. Narrative Generation will receive structured evidence and output constraints through a provider adapter. Live Delivery will expose updates over SSE. Personalized Presentation will choose the approved audience representation without changing underlying facts.

## Planned boundaries

- **Domain and event contracts:** synthetic event JSON Schema v1 is implemented and packaged; unsupported versions and unknown fields are rejected. API contracts will be exposed through future FastAPI OpenAPI.
- **Backend (planned):** FastAPI will own API endpoints, ingestion coordination, persisted match projections, statistics, insights, narratives, and SSE. FastAPI OpenAPI will expose API contracts.
- **Persistence:** PostgreSQL stores runs, match data, event history, projections, insights, and narrative records. SQLAlchemy provides data access; Alembic will manage later approved schema changes.
- **Frontend:** React + TypeScript + Vite consumes backend APIs and SSE; it renders dashboards and overlays, with synthetic labeling always visible.
- **AI provider:** application-owned abstraction accepts bounded evidence and returns structured candidate narrative output. Azure-hosted AI is one provider; validation and evidence association stay in application code.
- **Local infrastructure:** Docker Compose currently defines only PostgreSQL with a named volume, required environment-based credentials, a health check, and loopback host binding by default.
- **Deployment:** Azure deployment is a later phase. Managed identity, secret storage, network boundaries, observability, and cost controls must be settled before deployment.

## Local port assignments

MatchPulse AI reserves these development ports to avoid conflicts with other projects on the same machine:

| Component | Planned host port | Phase 0 status |
|---|---:|---|
| PostgreSQL | `5434` | Defined in Compose, bound to `127.0.0.1` |
| FastAPI | `8001` | Planned for a future phase; no backend service exists |
| Vite | `5174` | Planned for a future phase; no frontend service exists |

The PostgreSQL container continues to listen on port `5432` internally. The host port can be changed with `POSTGRES_HOST_PORT`; its bind address remains fixed to loopback.

## Data and delivery flow

The event is the durable evidence record. Every processed event has stable identity and a match-scoped timestamp/order. Replays use the same deterministic ordering and event identity; duplicate events must not double-apply. Derived state can be rebuilt from accepted events. Statistics and insights retain references to source event identifiers (or an explicitly described evidence set). Narratives retain the insight/evidence identifiers and model/provider metadata needed for audit, subject to privacy/security review.

SSE messages will use a stable delivery identifier and sequence so clients can resume from the last accepted event. There is no SSE implementation yet; reconnection semantics, retention bounds, and reset behavior require final approval in the relevant implementation phase. See [data contracts](data-contracts.md).

## Operational qualities

Planned operational requirements include bounded event processing latency, observable lag and validation failures, deterministic replay, graceful provider timeouts/fallback behavior, rate and cost limits for AI calls, database backups for deployed state, and accessibility/performance checks for live presentation. Concrete targets should be approved before implementation and deployment.
