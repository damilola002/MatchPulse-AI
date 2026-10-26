# Product blueprint

## Mission

Build an explainable real-time synthetic football match intelligence platform for the Microsoft × Premier League Synthetic Match Insights Engine challenge. The system generates deterministic synthetic match events, derives statistics and evidence-backed developments, creates grounded narratives with Azure-hosted AI, and presents live and recap experiences for distinct audiences. It is an independent project; generated content is not official Premier League data and must be conspicuously labeled synthetic.

## End-to-end pipeline

`Synthetic Event Generator → Ingestion → Match State → Statistics → Insight Detection → Narrative Generation → Live Delivery → Personalized Presentation`

The Phase 1 generator and pure replay reducer, Phase 2 ingestion, persistence, finalized-state replay, SSE and playback, and Phase 3 statistics and insight detection are complete, committed, and pushed. Phase 4 narrative generation and the minimum Phase 5 dashboard are implemented locally and await final review. Narratives explain only application-approved evidence and do not establish match facts. Delivery and presentation preserve synthetic-data labeling.

## Component status

| Component | Current status | Responsibility |
|---|---|---|
| Repository and architecture | Implemented in Phase 0 | Guidance, architecture, contracts design, roadmap, local DB scaffolding |
| Synthetic event generator | Implemented in Phase 1 | Deterministic fictional fixtures, seeded event streams, versioned schema, JSON/JSONL serialization |
| Pure local replay | Implemented in Phase 1 | Validate lifecycle and references; derive final score, possession, period, status, and shot counts |
| Ingestion and match state | Implemented in Phase 2 | Validate, deduplicate, order, replay, persist, and project events |
| Statistics and insight detection | Implemented in Phase 3; committed and pushed | Deterministic metrics and explainable evidence-linked insights from finalized events |
| Narrative generation | Implemented locally in Phase 4; awaiting review | Explicit local-demo POST selects approved application wording; deterministic fake provider is default |
| Live delivery | Implemented in Phase 2 and consumed locally by Phase 5 | Finalized raw-event SSE with stable IDs and reconnect behavior |
| Match dashboard | Implemented locally in Phase 5; awaiting review | Scoreboard, finalized timeline, metrics, insights/evidence, and explicit narrative action |
| Personalized presentation | Planned | Dashboard and broadcast outputs tailored to audience |
| Recaps and multilingual narratives | Planned | Evidence-grounded post-match summaries and translations |
| Azure deployment | Planned | Secure deployable application and demonstration environment |

Phase 2 implements a local API, database models/migration, network service, and persistent ingestion. No UI or model integration is implemented. The Phase 1 generator is an offline Python package and does not read real match data.

## Product principles

- Deterministic simulation and explainable statistical derivation.
- Clear provenance and synthetic labeling at data and presentation boundaries.
- Evidence traceability from event through insight and narrative.
- Replaceable AI provider boundary; no direct model dependency in domain rules.
- Accessibility, timely live updates, and audience-appropriate language.
- Secure-by-default local development and least-privilege deployment.

See [architecture](architecture.md), [data contracts](data-contracts.md), and [roadmap](roadmap.md).
