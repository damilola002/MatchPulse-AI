# Phased roadmap

Each phase requires explicit approval before implementation. Acceptance criteria below define the proposed exit bar; phase scope and criteria may be refined through an approved review. Phase 0 and Phase 1 are implemented; Phases 2–8 remain unimplemented and require approval.

## Phase 0 — Repository and architecture

- **Objective:** Establish independent project guidance, architecture, preliminary contracts, roadmap, and environment scaffolding.
- **Scope:** Initialize local Git on `main`; add approved documentation and ignore files; define PostgreSQL-only local Compose configuration.
- **Deliverables:** `AGENTS.md`, project README, architecture/blueprint/roadmap/contracts/development/security docs, decision record, `.env.example`, Compose and ignore configuration.
- **Exclusions:** Application code, package manifests, dependencies, tests, migrations, running containers, remotes, commits, and pushes.
- **Acceptance:** Approved files exist; docs agree about status and stack; Git is local on `main` without configured remote; Compose syntax is validated if tooling exists; no secrets or product implementation are present; working tree is reviewed.

## Phase 1 — Synthetic event generator

**Status: Implemented; awaiting final read-only review.**

- **Objective:** Produce reproducible synthetic football event streams.
- **Scope:** Immutable validated match configuration; fictional fixtures; isolated SplitMix64 seeded generation; v1 event schema and provenance; four defined scenarios; pure lifecycle/possession/score/shot replay; canonical JSONL and JSON-array serialization; offline CLI.
- **Deliverables:** Python package, packaged versioned JSON Schema, deterministic fixture/scenario definitions, replay reducer, pytest suite, pinned `jsonschema` runtime dependency, and usage documentation.
- **Exclusions:** Persistence, live ingestion, APIs, AI narratives, UI, real-match feeds, streaming, and downstream analytics.
- **Acceptance:** Same seed/config/generator version yields byte-identical canonical output; IDs and order are stable; all events validate; replay enforces lifecycle, references, goal linkage, and possession transitions; scenario constraints and serialization round trips pass automated tests.

## Phase 2 — Event ingestion and live match state

- **Objective:** Accept synthetic events and maintain replayable match state.
- **Scope:** FastAPI ingestion boundary, validation, idempotency, ordering, PostgreSQL persistence, state projection, and controlled replay.
- **Deliverables:** API contract, SQLAlchemy entities and approved Alembic migrations, ingestion service, projection logic, integration tests.
- **Exclusions:** Advanced insight rules, AI narrative generation, and dashboard features.
- **Acceptance:** Valid events persist once; malformed or unsupported versions are rejected clearly; replay reconstructs equivalent state; ordering is deterministic; integration tests pass.

## Phase 3 — Statistics and explainable insight detection

- **Objective:** Derive useful match statistics and explainable developments from state/evidence.
- **Scope:** Deterministic metric definitions, rule-based insight detection, evidence linkage, thresholds, and domain tests.
- **Deliverables:** Metric/rule documentation, implementation, evidence references, tests and representative examples.
- **Exclusions:** AI-written narratives, audience-specific presentation, and speculative claims.
- **Acceptance:** Identical state yields identical metrics/insights; each insight has rule/version and evidence references; claims can be checked against source events; tests cover boundaries.

## Phase 4 — Azure AI narrative generation

- **Objective:** Generate readable narratives grounded in approved evidence.
- **Scope:** Provider abstraction, Azure-hosted AI adapter, structured prompts/outputs, validation, timeouts, retries, and safe failure behavior.
- **Deliverables:** Provider interface, configuration strategy, narrative service, grounding/output validation, test doubles, security and cost controls.
- **Exclusions:** Frontend, personalization policy, recap workflows, and ungrounded free-form match analysis.
- **Acceptance:** Output claims are constrained to supplied evidence and validated; invalid/provider-failure cases are safely handled; core tests do not require live AI; credentials remain external.

## Phase 5 — Live dashboard and broadcast overlays

- **Objective:** Present live match state and developments to users.
- **Scope:** React/TypeScript/Vite application, SSE consumption, match dashboard, and broadcast graphics/overlay layout.
- **Deliverables:** Responsive accessible UI, connection/reconnect states, visible synthetic labeling, UI and stream-flow tests.
- **Exclusions:** Audience personalization, final recaps, and production deployment.
- **Acceptance:** Live state updates from the approved feed; reconnect behavior is clear; synthetic content is unmistakably labeled; key flows meet approved accessibility and test criteria.

## Phase 6 — Fan, analyst, and broadcaster personalization

- **Objective:** Adapt explanations and presentation to three audience needs while preserving facts.
- **Scope:** Audience-specific detail, terminology, narrative length, and presentation controls.
- **Deliverables:** Personalization rules/configuration, UX controls, representative examples, tests.
- **Exclusions:** Changing event truth or unsupported audience inference.
- **Acceptance:** Each audience gets the approved format and depth from the same evidence; factual claims and provenance remain consistent; tests verify the variants.

## Phase 7 — Match recaps and multilingual narratives

- **Objective:** Produce post-match recaps and multilingual narrative variants.
- **Scope:** Final-state evidence selection, recap generation, language selection/translation, validation, and storage/delivery decisions.
- **Deliverables:** Recap workflow, supported language policy, grounding checks, examples and tests.
- **Exclusions:** Live event generation changes and languages without an approved quality approach.
- **Acceptance:** Recaps reflect completed state and cite evidence internally; translated variants preserve claims and synthetic labeling; failures and unsupported languages are handled explicitly.

## Phase 8 — Azure deployment and hackathon demonstration

- **Objective:** Deploy the approved platform securely to Azure and prepare a repeatable demonstration.
- **Scope:** Hosting, managed identity/secrets, database, network controls, observability, cost limits, deployment workflow, demo scenarios and operational notes.
- **Deliverables:** Reviewed deployment configuration, deploy/run guide, smoke validation, rollback/cleanup plan, demo script.
- **Exclusions:** Unapproved public launch or production guarantees beyond agreed requirements.
- **Acceptance:** Deployment is reproducible and access-controlled; secrets are external; health, logs, costs, and failure behavior are observable; demo clearly identifies synthetic data; rollback/cleanup is documented and verified.
