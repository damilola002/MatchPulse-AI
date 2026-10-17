# MatchPulse AI

MatchPulse AI is an independent project for the Microsoft × Premier League Synthetic Match Insights Engine challenge. It is being built as a real-time synthetic football match intelligence platform. All generated match content must be clearly identified as synthetic.

## Status

Phases 0 and 1 established repository guidance, local PostgreSQL scaffolding, a deterministic synthetic event generator, schema v1, canonical JSON/JSONL serialization, and pure match replay. Phase 2 adds local FastAPI event ingestion, PostgreSQL-backed event history and stable match state, finalized-event SSE, and a playback CLI. Phase 2 is awaiting final review; analytics, AI, frontend, and deployment remain planned.

## Planned pipeline

**Implemented:** Synthetic Event Generator → Ingestion → Match State → finalized SSE delivery. **Planned:** statistics, insight detection, narrative generation, and personalized presentation.

See [the blueprint](docs/blueprint.md), [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [data contracts](docs/data-contracts.md).

## Initial development baselines

Python 3.12, Node.js 22 LTS, React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. `pyproject.toml` pins Phase 1 and 2 backend and test dependencies; frontend dependencies are reserved for the frontend phase.

## Local environment

Copy `.env.example` to `.env` and set a unique local database password. Compose defines PostgreSQL only; it does not start application services. To run Phase 2, load the local environment and follow the API, migration-approval, test database, SSE, and playback instructions in [development guidance](docs/development.md). Do not commit `.env` or use local credentials in deployed environments.

Follow [development guidance](docs/development.md) and [security guidance](docs/security.md). Work must follow [AGENTS.md](AGENTS.md) and the phase approval workflow. Do not implement a later phase without explicit approval.
