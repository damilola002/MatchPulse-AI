# MatchPulse AI

MatchPulse AI is an independent project for the Microsoft × Premier League Synthetic Match Insights Engine challenge. It is planned as a real-time synthetic football match intelligence platform. All generated match content must be clearly identified as synthetic.

## Status

Phase 0 established repository guidance and PostgreSQL-only local environment scaffolding. Phase 1 implements an offline, deterministic synthetic event generator, schema v1, canonical JSON/JSONL serialization, and pure match replay. Ingestion, persistence, analytics, AI, delivery, and presentation remain planned.

## Planned pipeline

**Implemented:** Synthetic Event Generator → pure Match State replay. **Planned:** ingestion, persistent match state, statistics, insight detection, narrative generation, live delivery, and personalized presentation.

See [the blueprint](docs/blueprint.md), [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [data contracts](docs/data-contracts.md).

## Initial development baselines

Python 3.12, Node.js 22 LTS, React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. Phase 1 pins `jsonschema==4.26.0` and the development extra pins `pytest==9.1.1`; other component dependencies remain undecided.

## Local environment

Copy `.env.example` to `.env`, set a strong local-only database password, then use Docker Compose when development is authorized. Compose currently defines PostgreSQL only. Do not commit `.env`; never use local credentials in deployed environments. No containers are started by this repository setup.

Follow [development guidance](docs/development.md) and [security guidance](docs/security.md). Work must follow [AGENTS.md](AGENTS.md) and the phase approval workflow. Do not implement a later phase without explicit approval.
