# Development workflow

## Baselines

Initial development baselines: Python 3.12 and Node.js 22 LTS. Planned frontend uses React, TypeScript, and Vite; planned backend uses FastAPI; PostgreSQL is the planned database with SQLAlchemy and Alembic. Baselines are subject to compatibility verification before implementation. Exact dependency versions and lockfiles belong to their approved implementation phases.

## Phase workflow

1. Review current files and Git state read-only.
2. Implement only the explicitly approved phase.
3. Run phase-appropriate tests and validation.
4. Review the final diff read-only and report changed files and results.
5. Commit only after explicit commit approval.
6. Push only after separate explicit push approval.

Do not skip phases or implement future functionality. Read `AGENTS.md` and the relevant roadmap section before work. Do not install packages or start services unless necessary for the approved phase.

## Local PostgreSQL

For a later authorized local run, copy `.env.example` to `.env` and set the blank `POSTGRES_PASSWORD` to a unique local value. Compose exposes PostgreSQL on `127.0.0.1:5434` by default, persists data in a named volume, and waits for the health check. Never commit `.env`. Phase 0 does not start services or create database tables.

The reserved MatchPulse AI development ports are PostgreSQL `5434`, FastAPI `8001` (future phase), and Vite `5174` (future phase). Phase 0 defines no backend or frontend services.

## Planned validation approach

Later backend changes should use isolated pytest unit and integration suites; deterministic logic should use fixed synthetic fixtures. Later frontend changes should cover components/state and critical live flows. Contract validation should test versioned JSON Schema and OpenAPI compatibility. SSE tests should cover ordering, resume, duplicate delivery, and retention/reset behavior. Core tests should not call live Azure AI; use provider test doubles, with separately authorized integration checks where needed.
