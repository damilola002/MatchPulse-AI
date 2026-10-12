# Data contracts — Phase 1 event contract implemented; later contracts preliminary

The synthetic event contract v1 is implemented at `src/matchpulse_sim/schemas/match-event.v1.schema.json`. The descriptions of database entities, APIs, insights, narratives, and SSE below remain preliminary design only and require approval before implementation. API contracts will be exposed through FastAPI OpenAPI. Synthetic event contracts use immutable, versioned JSON Schema. Phase 1 creates no SQL tables, migrations, endpoints, or persistent storage.

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

## Implemented event v1 contract

Every event has a stable `event_id` derived from its `simulation_run_id` and contiguous one-based `sequence`; a `schema_version` fixed at `1`; a match and simulation-run ID; integer millisecond `match_elapsed_ms` and `period_elapsed_ms`; period (`first_half` or `second_half`); event type; nullable team/player/location/outcome envelope fields; causal IDs; type-specific `data`; and explicit synthetic `provenance` including generator version, scenario, and seed. Unknown envelope and type-specific fields and unsupported versions are rejected.

Causal event references are unique IDs that replay requires to identify an earlier event in the same stream. Replay validates team and player references against the roster declared by `match_start`; the schema alone validates field shapes, not roster membership.

Clock time is cumulative playable match time, while period time resets at the second-half boundary. Stoppage time is represented by period clock overrun; there is no separate stoppage period, and v1 limits configured stoppage time to ten minutes per half. Equal timestamps are allowed, but sequence is strictly increasing and contiguous. Coordinates are integer percentages from 0–100 with `(0,0)` at top-left and y increasing downward. Teams switch attack direction after halftime; stored coordinates are never mutated for the switch.

The event taxonomy is `match_start`, `pass`, `shot`, `goal`, `tackle`, `ball_recovery`, `possession_change`, `pressure`, `foul`, `half_time`, `second_half_start`, and `full_time`. Each has a strict v1 payload and outcome schema. A goal-outcome shot must be followed by exactly one linked goal event; replay increments score only on a valid goal event. Possession state changes only when a valid `possession_change` event is processed. Replay requires kickoff transitions, clears possession before halftime/full-time, and restarts second-half possession for the away side. These are generator/reducer v1 conventions.

The generator uses fictional fixtures and labels every event synthetic. Stable identities and a versioned local PRNG policy are compatibility behavior. Canonical UTF-8 compact sorted-key JSONL is the stream format; JSON arrays are supported for import/export, preserving null fields, IDs, order, and schema versions.

## Preliminary event requirements for future ingestion

- **Idempotent processing:** Re-delivery of an event ID with identical content must not apply it twice. Same ID with conflicting content must be rejected and surfaced.
- **Persisted replay:** Future ingestion and persistence must preserve v1 deterministic ordering and reducer behavior, while defining storage/application semantics.
- **Schema versioning:** v1 rejection is implemented. Compatibility, translation, and future versions require a reviewed immutable schema artifact and explicit policy.
- **Insight-to-evidence traceability:** Every insight records its rule/version and the event IDs or evidence set that caused it, including relevant window boundaries. Evidence must be retrievable and stable.
- **Narrative grounding:** Narratives reference their input insight/evidence identifiers and audience/language. Validate claims or structured claims against supplied evidence; do not accept model output as new match fact. Store provider/model and validation outcome under an approved retention policy.
- **Synthetic provenance:** Synthetic match data carries an unambiguous synthetic marker and simulation run reference at appropriate record and API boundaries. Preserve labeling in exports and all user-facing outputs.

## SSE delivery requirements

SSE updates should have a stable, monotonically ordered delivery identifier scoped to the stream/match, use SSE `id` for client resume, and include an event type plus versioned data. Clients reconnect with `Last-Event-ID`; the server replays subsequent retained messages when possible. Retention expiry, unknown IDs, stream reset/snapshot recovery, duplicate handling, and authorization behavior need approval before Phase 5. Delivery IDs and domain event IDs are related but distinct concepts.

## PRNG compatibility policy

Generator v1 uses the explicitly implemented SplitMix64 algorithm with 64-bit unsigned wraparound. Its algorithm, draw order, and canonical JSONL bytes are compatibility behavior for byte-identical output within a generator version. Any algorithm, draw-order, or serialization change requires a generator-version change; seed, canonical configuration, and generator version determine run identity. Python `random`, global randomness, salted hashing, and wall-clock values are not used. The golden-output fixture is defined for Python 3.12 and the project supports Python 3.12+; supported interpreter updates must pass that fixed digest check before release.

## Open decisions for future contracts

The Phase 1 event taxonomy, v1 payloads, identity construction, sequence/tie-break rules, simulated clock model, coordinate convention, and v1 rejection behavior are implemented. Review any changes to those rules before changing the versioned contract. Evidence representation, narrative metadata retention, SSE replay window/reset protocol, and API compatibility strategy require approval before their dependent implementation begins.
