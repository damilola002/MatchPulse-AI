# Preliminary data contracts — design only

These contracts are proposals for planning, not implemented schemas or approved database models. They must be reviewed and explicitly approved before implementation. API contracts will be exposed through FastAPI OpenAPI. Synthetic event contracts will use versioned JSON Schema. No SQL tables, migrations, endpoints, schemas, or application code are created in Phase 0.

## Planned entities

| Entity | Preliminary purpose and key relationships |
|---|---|
| `Team` | Stable team identity and display metadata; referenced by a match as home or away team. |
| `Player` | Stable player identity, team/roster association, and display metadata; referenced by relevant events. Roster timing/transfer handling needs definition. |
| `Match` | Stable match identity, participating teams, scheduled/context metadata, and lifecycle/status. Synthetic fixtures must not masquerade as official matches. |
| `MatchEvent` | Immutable validated event with stable event ID, match ID, event time, deterministic sequence/order, type, schema version, payload, and simulation provenance. |
| `MatchState` | Rebuildable current match projection with last applied event position and projection version/time. |
| `Insight` | Deterministically identified rule result, rule/version, match/time context, explanation, and source event/evidence references. |
| `Narrative` | Audience/language-specific generated text or structured content linked to evidence/insights, validation status, and provider/model metadata as appropriate. |
| `SimulationRun` | Generator version, seed/config fingerprint, synthetic provenance, start/completion state, and generated match/event range for reproducibility. |

## Preliminary event requirements

- **Stable event IDs:** Unique and stable across retries and replay, ideally derived from simulation run identity plus deterministic event position or assigned reproducibly by the generator. Collision behavior must be defined.
- **Match identifiers and timestamps:** Every event identifies its match and carries a normalized event timestamp. Keep event time distinct from ingestion/processing time. Define clock precision, period-relative time, and stoppage-time representation before implementation.
- **Event types and payload validation:** Enumerate supported event types and define type-specific payload schemas, required/optional fields, numeric bounds, units, and unknown-field policy. Reject invalid payloads; do not silently reinterpret them.
- **Deterministic ordering and replay:** Use an explicit stable match-local sequence or ordering key. Define tie-breaking when timestamps match. Replaying the same accepted event log must reproduce the same state and derived outputs.
- **Idempotent processing:** Re-delivery of an event ID with identical content must not apply it twice. Same ID with conflicting content must be rejected and surfaced.
- **Schema versioning:** Every event includes a schema version. Version support, compatibility rules, migration/translation policy, and rejection behavior are explicit. JSON Schema versions are immutable artifacts.
- **Insight-to-evidence traceability:** Every insight records its rule/version and the event IDs or evidence set that caused it, including relevant window boundaries. Evidence must be retrievable and stable.
- **Narrative grounding:** Narratives reference their input insight/evidence identifiers and audience/language. Validate claims or structured claims against supplied evidence; do not accept model output as new match fact. Store provider/model and validation outcome under an approved retention policy.
- **Synthetic provenance:** Synthetic match data carries an unambiguous synthetic marker and simulation run reference at appropriate record and API boundaries. Preserve labeling in exports and all user-facing outputs.

## SSE delivery requirements

SSE updates should have a stable, monotonically ordered delivery identifier scoped to the stream/match, use SSE `id` for client resume, and include an event type plus versioned data. Clients reconnect with `Last-Event-ID`; the server replays subsequent retained messages when possible. Retention expiry, unknown IDs, stream reset/snapshot recovery, duplicate handling, and authorization behavior need approval before Phase 5. Delivery IDs and domain event IDs are related but distinct concepts.

## Open contract decisions

Approve event taxonomy and payloads, identity construction, sequence/tie-break rules, timestamp model, schema compatibility policy, evidence representation, narrative metadata retention, SSE replay window and reset protocol, and API compatibility strategy before dependent implementation begins.
