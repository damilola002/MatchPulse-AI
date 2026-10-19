# Development workflow

## Baselines

Initial development baselines: Python 3.12 and Node.js 22 LTS. The React, TypeScript, and Vite frontend remains planned. Phase 2 adds FastAPI, SQLAlchemy, Alembic, psycopg, Uvicorn, Pydantic, and HTTPX with pinned versions in `pyproject.toml`; verify versions against the selected interpreter before installation.

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

Development ports: PostgreSQL `5434`, FastAPI `8001`, and Vite `5174` (future frontend phase). These are local defaults, not a guarantee of availability. The API binds to `127.0.0.1` and CORS allows only `http://localhost:5174`; the React frontend does not exist in Phase 2.

## Phase 2 API and playback

Create an untracked `.env` from `.env.example` and set a non-empty local `POSTGRES_PASSWORD`. Before running the API or Alembic from a shell, export those settings with `set -a; . ./.env; set +a`. The API uses `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_HOST_PORT` to connect to PostgreSQL at `127.0.0.1`.

PostgreSQL integration tests require both `MATCHPULSE_TEST_DATABASE_URL` and `MATCHPULSE_TEST_DATABASE_NAME`. The URL database must exactly match the explicitly designated name, use loopback, and differ from the normalized development host/port/database target. A `_test` suffix is an additional check, not the sole isolation guard. The tests create and drop only a unique temporary schema within that dedicated test database. Never point the test URL at the development database.

Alembic requires `MATCHPULSE_MIGRATION_TARGET=development` or `MATCHPULSE_MIGRATION_TARGET=test`; there is no implicit default. Test migrations additionally require `MATCHPULSE_TEST_MIGRATION_CONFIRM` to equal the designated test database name. Before an approved migration, verify the connected database name, server address, and port. Test migrations use the explicit test URL; development migrations continue to use the `POSTGRES_*` configuration. Neither selection runs automatically. Never put database passwords in command arguments or logs.

The event-page endpoint returns at most 100 events and at most 1 MiB of compact serialized JSON. If the first event after a cursor cannot fit, it returns a non-retryable `413 event_exceeds_page_budget` with the blocking sequence; the cursor is not advanced and the event is not skipped. Clients must surface the error rather than retrying the same page indefinitely.

## Phase 3 intelligence API

With the Phase 3 API running, query `GET /api/matches/{match_id}/intelligence?limit=100`. The response includes `metric_snapshot`, an ordered `insights` page, the pinned `as_of` finalized watermark, and an optional `next_cursor`. Continue pagination with `?cursor=<opaque-value>`; do not reuse a cursor with a different match or change its page size. The endpoint computes from finalized events only, is bounded to 10,000 events/16 MiB per calculation and 100 insights/1 MiB per response, and does not add intelligence SSE or database tables.

Before using the endpoint, set `MATCHPULSE_INTELLIGENCE_CURSOR_KEY` in the untracked `.env` to an unpadded base64url encoding of at least 32 random bytes. Keep it stable while cursors are in use; changing it invalidates existing cursors. The API fails closed when the key is missing or malformed. Never place the key in source control, command examples, logs, or issue reports. After sourcing `.env` as described above, the API process inherits the setting.

Install package/test dependencies in the isolated virtual environment described above. After PostgreSQL is running and its credentials are configured:

```sh
.venv/bin/python -m matchpulse_sim serve --host 127.0.0.1 --port 8001
```

The server does not run migrations automatically. Migration commands such as `.venv/bin/alembic upgrade head` alter database structure and require explicit approval for the target database. Do not run them against development without separate authorization.

Ingest through `POST /api/matches` with `{"start_event": <match_start event>}`, then submit ordered batches of up to 100 events to `POST /api/matches/{match_id}/events`. Raw request bodies are limited to 1 MiB. Query stable state at `/state`, accepted events at `/events?after_sequence=0&limit=100`, and subscribe to finalized committed events at `/stream`; reconnect with the most recent SSE `Last-Event-ID`.

Feed a reproducible generated stream, or a previously exported complete JSON/JSONL file, with:

```sh
.venv/bin/python -m matchpulse_sim play --scenario balanced --seed 42 --speed 10
.venv/bin/python -m matchpulse_sim play --input /tmp/matchpulse-match.jsonl --speed 10
.venv/bin/python -m matchpulse_sim play --input /tmp/matchpulse-match.jsonl --resume --speed 10
```

Playback uses simulation-clock deltas, preserves event IDs and contents, retries uncertain requests idempotently, and can be interrupted with Ctrl-C. Resume checks match, run, accepted sequence, and event identity before sending the remaining suffix. The initial incremental reducer and ingestion path replay the accepted prefix for each addition, so processing cost grows with match history; this implementation is intended for the small synthetic matches used in local demonstrations. Phase 2 has no browser controls, authentication, production deployment, stream retention/reset protocol, or automatic projection repair.

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
