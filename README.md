# MatchPulse AI

MatchPulse AI is an independent project for the Microsoft × Premier League Synthetic Match Insights Engine challenge. It is being built as a real-time synthetic football match intelligence platform. All generated match content must be clearly identified as synthetic.

## Status

Phases 0–3 are complete, reviewed, committed, and pushed. Phase 1 provides deterministic synthetic event generation and replay. Phase 2 provides local FastAPI ingestion, PostgreSQL event history and stable match state, finalized-event SSE, and playback. Phase 3 provides deterministic statistics and evidence-linked intelligence. Phase 4 narrative generation and the minimum Phase 5 dashboard are implemented locally and awaiting final review. Narratives are explicitly invoked, local-demo gated, and constrained to application-approved wording. Personalization, recaps, and deployment remain planned.

## Planned pipeline

**Implemented:** Synthetic Event Generator → Ingestion → Match State → finalized SSE delivery → deterministic statistics and insight detection. **Implemented locally, awaiting review:** grounded Phase 4 narrative generation and the Phase 5 React dashboard. Playback is launched through the existing local CLI; the browser does not start processes or create an ingestion protocol. **Planned:** personalization, recaps, and deployment.

See [the blueprint](docs/blueprint.md), [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [data contracts](docs/data-contracts.md).

## Initial development baselines

Python 3.12, Node.js 22 LTS, React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. `pyproject.toml` pins backend and test dependencies; `frontend/package.json` and its lockfile pin frontend dependencies.

## Local environment

Copy `.env.example` to `.env` and set a unique local database password. Compose defines PostgreSQL only; it does not start application services. To run Phase 2, load the local environment and follow the API, migration-approval, test database, SSE, and playback instructions in [development guidance](docs/development.md). Do not commit `.env` or use local credentials in deployed environments.

Follow [development guidance](docs/development.md) and [security guidance](docs/security.md). Work must follow [AGENTS.md](AGENTS.md) and the phase approval workflow. Do not implement a later phase without explicit approval.
