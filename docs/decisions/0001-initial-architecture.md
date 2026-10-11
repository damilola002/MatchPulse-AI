# Decision 0001: Initial architecture and development baselines

- **Status:** Accepted for Phase 0 planning; implementation details remain subject to compatibility verification and later approval.
- **Date:** 2026-10-11
- **Decision owners:** Project owner

## Context

MatchPulse AI needs a real-time synthetic match pipeline, explainable derived insights, evidence-grounded narratives, and browser-based live presentation. The repository must remain independent and development must be phased with explicit approval.

## Decision

- Use Python 3.12 as the initial backend development baseline with FastAPI.
- Use Node.js 22 LTS as the initial frontend development baseline with React, TypeScript, and Vite.
- Use PostgreSQL with SQLAlchemy and Alembic for planned persistence and schema evolution.
- Use Server-Sent Events for planned server-to-browser live updates.
- Use Docker Compose for local infrastructure; Phase 0 defines PostgreSQL only.
- Use Azure-hosted AI behind an application-owned provider abstraction.
- Expose API contracts through FastAPI OpenAPI and synthetic event contracts through versioned JSON Schema.
- Preserve deterministic event replay, evidence traceability, and visible synthetic provenance throughout the pipeline.

## Consequences

The stack gives separate backend and browser presentation boundaries, relational storage for event history and derived records, and a replaceable AI provider boundary. Exact library versions, API/event fields, AI model, Azure topology, and performance targets remain open. The listed runtime versions are initial baselines, not claims that compatibility has already been tested. Future schema/API decisions require documented review before implementation.

## Alternatives and rationale

WebSockets were not selected for the initial one-way server-to-browser update need; SSE is simpler for this direction and supports event IDs/resumption. AI provider coupling inside domain rules was rejected to keep statistics and insights deterministic and provider-independent. Production deployment services are deferred until the Azure phase.
