# MatchPulse AI

MatchPulse AI is an independent project for the Microsoft × Premier League Synthetic Match Insights Engine challenge. It is planned as a real-time synthetic football match intelligence platform. All generated match content must be clearly identified as synthetic.

## Status

Phase 0 establishes repository guidance, architecture, preliminary contracts, roadmap, and local PostgreSQL environment scaffolding. Application components are planned and are not implemented.

## Planned pipeline

Synthetic Event Generator → Ingestion → Match State → Statistics → Insight Detection → Narrative Generation → Live Delivery → Personalized Presentation.

See [the blueprint](docs/blueprint.md), [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [preliminary data contracts](docs/data-contracts.md).

## Initial development baselines

Python 3.12, Node.js 22 LTS, React, TypeScript, Vite, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Server-Sent Events, Docker Compose, and Azure-hosted AI behind a provider abstraction. Version baselines are subject to compatibility verification before implementation; dependency versions have not yet been installed or locked.

## Local environment

Copy `.env.example` to `.env`, set a strong local-only database password, then use Docker Compose when development is authorized. Compose currently defines PostgreSQL only. Do not commit `.env`; never use local credentials in deployed environments. No containers are started by this repository setup.

Follow [development guidance](docs/development.md) and [security guidance](docs/security.md). Work must follow [AGENTS.md](AGENTS.md) and the phase approval workflow. Do not implement a later phase without explicit approval.
