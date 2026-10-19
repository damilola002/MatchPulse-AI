# Product blueprint

## Mission

Build an explainable real-time synthetic football match intelligence platform for the Microsoft × Premier League Synthetic Match Insights Engine challenge. The system generates deterministic synthetic match events, derives statistics and evidence-backed developments, creates grounded narratives with Azure-hosted AI, and presents live and recap experiences for distinct audiences. It is an independent project; generated content is not official Premier League data and must be conspicuously labeled synthetic.

## End-to-end pipeline

`Synthetic Event Generator → Ingestion → Match State → Statistics → Insight Detection → Narrative Generation → Live Delivery → Personalized Presentation`

The Phase 1 generator and pure replay reducer, and Phase 2 ingestion, persistence, finalized-state replay, SSE, and playback are implemented. Phase 3 implementation and local test verification complete; awaiting final review, commit, and push. The reported full-suite result is 82 passed, 0 failed, and 55 warnings. Narrative generation may explain approved evidence but does not establish match facts. Delivery and presentation preserve synthetic-data labeling.

## Component status

| Component | Current status | Responsibility |
|---|---|---|
| Repository and architecture | Implemented in Phase 0 | Guidance, architecture, contracts design, roadmap, local DB scaffolding |
| Synthetic event generator | Implemented in Phase 1 | Deterministic fictional fixtures, seeded event streams, versioned schema, JSON/JSONL serialization |
| Pure local replay | Implemented in Phase 1 | Validate lifecycle and references; derive final score, possession, period, status, and shot counts |
| Ingestion and match state | Implemented in Phase 2 | Validate, deduplicate, order, replay, persist, and project events |
| Statistics and insight detection | Phase 3 implementation and local test verification complete; awaiting final review, commit, and push | Deterministic metrics and explainable evidence-linked insights from finalized events |
| Narrative generation | Planned | Provider-abstracted Azure AI narratives grounded in evidence |
| Live delivery | Planned | SSE event delivery with stable IDs and reconnect behavior |
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
