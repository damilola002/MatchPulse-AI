# Development workflow

## Baselines

Initial development baselines: Python 3.12 and Node.js 22 LTS. Planned frontend uses React, TypeScript, and Vite; planned backend uses FastAPI; PostgreSQL is the planned database with SQLAlchemy and Alembic. Phase 1 requires Python 3.12+ and pins `jsonschema==4.26.0`; its development extra pins `pytest==9.1.1`. Other component dependencies and lockfiles belong to their approved implementation phases.

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

## Phase 1 generator usage

Scenario schedules impose minimum total period-clock durations (regulation plus stoppage). Halftime and full-time events occur at those configured period boundaries; they may share a timestamp with the final scripted event because event sequence breaks equal-clock ties. Stoppage time is limited to ten minutes by configuration.

| Scenario | Latest first-half event | Latest second-half event | Minimum first-half duration | Minimum second-half duration |
|---|---:|---:|---:|---:|
| `balanced` | 41 min | 43 min | 41 min | 43 min |
| `late_comeback` | 39 min | 44 min | 39 min | 44 min |
| `sustained_pressure` | 38 min | 23 min | 38 min | 23 min |
| `low_event_defensive` | 41 min | 20 min | 41 min | 20 min |

Configurations below either scenario-specific minimum are rejected before event generation with the scenario, period, required duration, and actual duration in the error.

Create an isolated environment and install this package with its test extra:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Generate canonical JSONL for a fictional balanced match and replay it locally:

```sh
.venv/bin/python -m matchpulse_sim generate --scenario balanced --seed 42 --format jsonl > /tmp/matchpulse-match.jsonl
.venv/bin/python -m matchpulse_sim replay /tmp/matchpulse-match.jsonl
```

Supported scenarios are `balanced`, `late_comeback`, `sustained_pressure`, and `low_event_defensive`. Use `--format json` for an array export. Generated output is synthetic and contains no real clubs or players. The CLI works on local files only; it does not start services or contact external systems. JSON and JSONL replay input is limited to 64 MiB per file or supplied text value. The bound limits memory use for whole-document parsing and leaves ample room for a local synthetic match. Larger datasets should be divided into complete match files; an individual stream above the limit is unsupported in this offline phase.

The generator-v1 golden digest uses the fictional default fixtures, `balanced` scenario, seed `17`, and match ID `golden-balanced-17`. It was fixed from Python 3.12 output; the package declares Python 3.12+ and requires this digest to remain stable on supported interpreter versions. Intentional output or serialization changes require a generator-version change and a reviewed contract update.
