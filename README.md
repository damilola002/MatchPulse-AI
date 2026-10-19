# MatchPulse AI

MatchPulse AI is an independent project for the Microsoft × Premier League Synthetic Match Insights Engine challenge. It is being built as a real-time synthetic football match intelligence platform. All generated match content must be clearly identified as synthetic.

## Status

Phases 0–2 are complete, reviewed, committed, and pushed. Phase 1 provides deterministic synthetic event generation and replay. Phase 2 provides local FastAPI ingestion, PostgreSQL event history and stable match state, finalized-event SSE, and playback. Phase 3 implementation and local test verification complete; awaiting final review, commit, and push. The reported full-suite result is 82 passed, 0 failed, and 55 warnings. See the [Phase 3 intelligence contract](docs/phase3-intelligence-contract.md). AI narratives, frontend, personalization, recaps, and deployment remain planned.

## Planned pipeline

**Implemented locally:** Synthetic Event Generator → Ingestion → Match State → finalized SSE delivery → deterministic statistics and insight detection. Phase 3 implementation and local test verification complete; awaiting final review, commit, and push. **Planned:** narrative generation and personalized presentation.

See [the blueprint](docs/blueprint.md), [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [data contracts](docs/data-contracts.md).

## Initial development baselines

Python 3.12, Node.js 22 LTS, React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. `pyproject.toml` pins Phase 1 and 2 backend and test dependencies; frontend dependencies are reserved for the frontend phase.

## Local environment

Copy `.env.example` to `.env` and set a unique local database password. Compose defines PostgreSQL only; it does not start application services. To run Phase 2, load the local environment and follow the API, migration-approval, test database, SSE, and playback instructions in [development guidance](docs/development.md). Do not commit `.env` or use local credentials in deployed environments.

Follow [development guidance](docs/development.md) and [security guidance](docs/security.md). Work must follow [AGENTS.md](AGENTS.md) and the phase approval workflow. Do not implement a later phase without explicit approval.
