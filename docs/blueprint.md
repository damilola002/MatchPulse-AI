# Product blueprint

## Mission

Build an explainable real-time synthetic football match intelligence platform for the Microsoft × Premier League Synthetic Match Insights Engine challenge. The system generates deterministic synthetic match events, derives statistics and evidence-backed developments, creates grounded narratives with Azure-hosted AI, and presents live and recap experiences for distinct audiences. It is an independent project; generated content is not official Premier League data and must be conspicuously labeled synthetic.

## End-to-end pipeline

`Synthetic Event Generator → Ingestion → Match State → Statistics → Insight Detection → Narrative Generation → Live Delivery → Personalized Presentation`

Every arrow represents a future explicit component contract. Event identity, validation, replay, and evidence provenance must flow through the pipeline. Narrative generation may explain approved evidence but does not establish match facts. Delivery and presentation preserve synthetic-data labeling.

## Component status

| Component | Status after Phase 0 | Planned responsibility |
|---|---|---|
| Repository and architecture | Implemented in Phase 0 | Guidance, architecture, contracts design, roadmap, local DB scaffolding |
| Synthetic event generator | Planned | Reproducible event streams and simulation provenance |
| Ingestion and match state | Planned | Validate, deduplicate, order, replay, and project events |
| Statistics and insight detection | Planned | Deterministic metrics and explainable evidence-linked insights |
| Narrative generation | Planned | Provider-abstracted Azure AI narratives grounded in evidence |
| Live delivery | Planned | SSE event delivery with stable IDs and reconnect behavior |
| Personalized presentation | Planned | Dashboard and broadcast outputs tailored to audience |
| Recaps and multilingual narratives | Planned | Evidence-grounded post-match summaries and translations |
| Azure deployment | Planned | Secure deployable application and demonstration environment |

No application code, API, schema migrations, UI, model integration, or event generator is implemented in Phase 0.

## Product principles

- Deterministic simulation and explainable statistical derivation.
- Clear provenance and synthetic labeling at data and presentation boundaries.
- Evidence traceability from event through insight and narrative.
- Replaceable AI provider boundary; no direct model dependency in domain rules.
- Accessibility, timely live updates, and audience-appropriate language.
- Secure-by-default local development and least-privilege deployment.

See [architecture](architecture.md), [data contracts](data-contracts.md), and [roadmap](roadmap.md).
