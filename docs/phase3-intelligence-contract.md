# Phase 3 — Deterministic match intelligence contract

**Status:** Implemented, reviewed, committed, and pushed in `82b89a70ed433c65f10230df82978469d8630e96`.

This document formalizes the roadmap's Phase 3 scope: deterministic statistics and explainable, evidence-linked insights from finalized synthetic match events. Phase 3 does not generate AI prose, tailor outputs to audiences, or make claims unsupported by the event log.

## 1. Scope and authority

### Existing requirements

`docs/roadmap.md` requires deterministic metric definitions, rule-based insight detection, evidence linkage, thresholds, and domain tests. Identical state must yield identical metrics and insights; every insight must identify its rule/version and evidence; claims must be checkable; tests must cover boundaries.

Phase 1's `match-event.v1.schema.json` and `replay.py` define event shape, sequence, clock, team references, score, and synthetic provenance. Phase 2's `MatchRecord.finalized_sequence` and `finalized_event_id` identify the stable contiguous event prefix. `replay_prefix` is the only lifecycle/possession reducer. Phase 2's event log is append-only.

### Phase 3 v1 approved domain scope

Metrics:

1. Goals by team.
2. Shots by team.
3. Shot outcomes by team.
4. Logged pressure events by team.
5. Goals-per-shot ratio by team.

Insights, exactly three rules:

1. `score_change`: one insight for each finalized goal that changes the score.
2. `shot_activity`: at least three qualifying shots by one team in a rolling ten-minute match-clock window.
3. `pressure_activity`: at least four logged pressure events by one team in a rolling ten-minute match-clock window.

The shot and pressure thresholds are demonstration rules, not validated professional-football performance thresholds. These rules do not establish tactical intent, pressure intensity, momentum, or causation beyond the linked events.

## 2. Event interpretation and metric definitions

Only schema-v1 events that pass Phase 2 validation/replay are inputs. All returned values are labeled `synthetic: true` and described as synthetic event-derived measurements.

| Metric | Included events | Calculation |
|---|---|---|
| `goals` | `type == "goal"`, grouped by `team_id` | Count goal events. The schema and replay require `team_id` to agree with `data.scoring_team_id`. |
| `shots` | `type == "shot"`, grouped by `team_id` | Count shot events once each, including a shot whose `outcome == "goal"`. |
| `shot_outcomes` | `type == "shot"` | Count outcomes `goal`, `saved`, `blocked`, `off_target`, and `woodwork` by team and outcome. |
| `logged_pressure_events` | `type == "pressure"`, grouped by `team_id` | Count each logged pressure event once. Outcomes `applied`, `forced_error`, and `bypassed` may be broken out as event counts; they do not measure pressure intensity. |
| `goals_per_shot` | Goal count and shot-event count above | `goal events / shot events`. A goal-outcome shot is a shot; its linked `goal` event increments goals but is not a second shot. |

`goals_per_shot.value` is JSON `null` when the shot denominator is zero; numerator and denominator remain the exact integer goal and shot counts (including `0`, `0` for the undefined ratio). Otherwise calculate the quotient from integer counts with decimal arithmetic, quantize to four fractional places using decimal `ROUND_HALF_EVEN` (ties go to the nearest even last digit), and serialize as a JSON string with exactly four digits after the decimal point (for example, `"0.3333"`). Do not use binary floating point. Counts use JSON integers. Each metric object carries `value`, `unit`, `numerator`, and `denominator`; count metrics use event count as numerator and `1` as denominator. An outcome-count metric has the same count semantics.

These metrics do not estimate expected goals, possession percentage/duration, player location, pressure intensity, or tracking-derived performance. Event coordinates are simulator coordinates, not a tracking feed.

## 3. Clock and rolling-window semantics

Event clock values are integer milliseconds. `match_elapsed_ms` is cumulative playable match time; the second half starts at the first-half duration, including configured stoppage. `period_elapsed_ms` resets at second-half start. Stoppage remains overrun within its half; it is not a separate period.

For a candidate activity event at match clock `t`, the rolling window is:

`[max(period_start_match_elapsed_ms, t - 600_000), t]`

Both endpoints are inclusive. Thus events exactly 600,000 ms apart can be in the same window; an event at `t - 600,001` is outside. `period` is also part of the key, so no event can cross half-time. The first-half period start is match time 0; second-half period start is the `match_elapsed_ms` of `second_half_start` (the configured first-half duration). Stoppage time uses its actual match clock and remains in that half's window.

Events are processed in strict `sequence` order. Equal timestamps are valid and all remain in the inclusive window; sequence breaks ties. The clock is never converted to wall-clock time and no wall-clock buckets are used.

### Episode suppression and reset

Maintain one episode state per `(match_id, simulation_run_id, rule_id, period, team_id)`. Process every finalized event in sequence order. Whenever its match clock advances to `t`, first evict qualifying activity events with timestamps strictly less than `t - 600_000`. If the episode is active and the remaining count is now below threshold, rearm it before considering the current event. Then, if the current event qualifies, add it; if the episode is inactive and the post-add count reaches threshold, emit exactly one insight and mark the episode active. While active, suppress further alerts as long as the rolling count is at or above threshold. This ordering also applies when the event that advances time is itself qualifying: expiration and rearming happen first, so that event may start a new episode.

Rearming is evaluated on every finalized event that advances match time, including non-qualifying events, rather than only on qualifying events. This gives sparse-event streams deterministic expiry behavior. Equal-time events are processed by sequence without aging the window. If no finalized event advances the match clock, no expiry occurs; wall-clock passage has no effect. At a half transition, discard the prior period's window and episode state and begin a separate window at the second-half start. This makes expiration, threshold crossing, equal-time ordering, and repeat suppression reproducible in full replay and incremental recalculation.

For `shot_activity`, each `type == "shot"` is qualifying regardless of outcome; linked `goal` records are not counted as shots. For `pressure_activity`, each `type == "pressure"` is qualifying regardless of its valid pressure outcome. Evidence is the ordered set of qualifying event IDs in the window at the threshold crossing (three shots or four pressure events).

## 4. Finalized-only calculation

Read `MatchRecord.finalized_sequence` and `finalized_event_id` from the same match record used to identify the run and teams. Select only append-only `match_events` for that match/run where `sequence <= finalized_sequence`, ordered by `sequence`. Validate/replay this prefix with the existing Phase 2 replay semantics; Phase 3 must not introduce another lifecycle, score, or possession reducer.

An accepted event beyond the finalized watermark must not affect metric values, insight triggers, evidence IDs, or cursors. In particular, a `shot` with goal outcome is provisional until its required `goal` event and possession restart have completed the reducer's transition. Neither the shot nor goal is used by public Phase 3 intelligence until it is within the finalized prefix. Other pending possession transitions are treated the same way: exclude every event after the watermark.

Recalculate from the finalized prefix whenever a newer finalized watermark is observed. The same match/run and finalized prefix must yield structurally identical metrics and insights. Use the finalized watermark as the snapshot identity and return it with every response. Duplicate delivery cannot create extra counts because the Phase 2 log enforces stable event identity and sequence uniqueness.

## 5. Proposed versioned output contracts

These are the finalized Phase 3 v1 domain/API contracts, not yet implemented JSON Schemas. Implementation must preserve the field names and types below.

### MetricSnapshot v1

```json
{
  "schema_version": 1,
  "match_id": "synthetic-match-id",
  "simulation_run_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "synthetic": true,
  "metric_definition_version": "1.0.0",
  "as_of": {
    "sequence": 42,
    "event_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:42",
    "match_elapsed_ms": 1860000
  },
  "teams": [
    {
      "team_id": "home-team",
      "role": "home",
      "metrics": {
        "goals": {"value": 1, "unit": "goals", "numerator": 1, "denominator": 1},
        "shots": {"value": 3, "unit": "shots", "numerator": 3, "denominator": 1},
        "shot_outcomes": {
          "goal": {"value": 1, "unit": "shots", "numerator": 1, "denominator": 1},
          "saved": {"value": 1, "unit": "shots", "numerator": 1, "denominator": 1},
          "blocked": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
          "off_target": {"value": 1, "unit": "shots", "numerator": 1, "denominator": 1},
          "woodwork": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1}
        },
        "logged_pressure_events": {"value": 2, "unit": "events", "numerator": 2, "denominator": 1},
        "goals_per_shot": {
          "value": "0.3333", "unit": "goals_per_shot", "numerator": 1, "denominator": 3
        }
      }
    },
    {
      "team_id": "away-team",
      "role": "away",
      "metrics": {
        "goals": {"value": 0, "unit": "goals", "numerator": 0, "denominator": 1},
        "shots": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
        "shot_outcomes": {
          "goal": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
          "saved": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
          "blocked": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
          "off_target": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1},
          "woodwork": {"value": 0, "unit": "shots", "numerator": 0, "denominator": 1}
        },
        "logged_pressure_events": {"value": 0, "unit": "events", "numerator": 0, "denominator": 1},
        "goals_per_shot": {"value": null, "unit": "goals_per_shot", "numerator": 0, "denominator": 0}
      }
    }
  ]
}
```

The team array always lists home then away, taken from the validated `match_start` record. Outcome categories are always present with zero counts when absent. At finalized sequence zero, `as_of.event_id` and `as_of.match_elapsed_ms` are `null`; at any positive watermark they are the exact stored finalized event ID and its match clock. The API must never substitute the accepted watermark. Ratio values use the exact four-place decimal-string representation defined above.

### Insight v1

```json
{
  "schema_version": 1,
  "insight_id": "insight:v1:<sha256-hex>",
  "match_id": "synthetic-match-id",
  "simulation_run_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "synthetic": true,
  "rule_id": "shot_activity",
  "rule_version": "1.0.0",
  "team_id": "home-team",
  "period": "first_half",
  "clock": {"match_elapsed_ms": 1860000, "period_elapsed_ms": 1860000},
  "trigger_event_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:42",
  "trigger_sequence": 42,
  "window": {
    "start_match_elapsed_ms": 1260000,
    "end_match_elapsed_ms": 1860000,
    "inclusive": true
  },
  "observed_facts": {"qualifying_shot_count": 3},
  "threshold": {"operator": ">=", "value": 3, "unit": "shots"},
  "evidence_event_ids": [
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:18",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:27",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:42"
  ]
}
```

For `score_change`, `team_id` is the scoring team, clock/trigger identify the `goal` event, `window` is `null`, `observed_facts` contains structured `score_before` and `score_after`, threshold is `null`, and evidence contains exactly the goal event ID. Obtain the score transition from replay states immediately before that goal transition and after its required possession change has finalized; use `replay_prefix`, not a second score reducer. Do not emit until that closing transition is included in the finalized prefix.

For activity rules, evidence IDs are ordered by sequence and include exactly the events present at the first threshold crossing. There is no AI-generated explanation text. A UI may later render a reviewed template from the rule ID and structured facts without changing the intelligence record.

### Stable serialization and IDs

Use the existing `canonical_json` rules (UTF-8, compact JSON, recursively sorted object keys) for canonical test fixtures and hash input; list order is explicitly defined above. Avoid floating-point values in canonical contract fields; the ratio is a fixed four-place decimal string. HTTP object key order is not semantic, but arrays and values must remain deterministic.

`insight_id` identifies the underlying triggering event/episode, not the later calculation snapshot. Compute it as `insight:v1:` plus SHA-256 of canonical JSON containing schema version, match ID, run ID, rule ID/version, team ID or null, period, trigger event ID, and ordered evidence event IDs. Do not include response `as_of`, database row IDs, wall-clock time, random UUIDs, or unstable iteration order. For `score_change`, the goal event ID identifies the trigger. For activity rules, the threshold-crossing event ID plus the evidence set identifies the episode. Recalculating a later prefix preserves an existing episode's ID and facts.

## 6. Proposed read-only API

Approved path: `GET /api/matches/{match_id}/intelligence`.

The endpoint returns a wrapper with `match_id`, `simulation_run_id`, `synthetic: true`, `as_of` (finalized sequence/event ID/match time), `metric_snapshot` (MetricSnapshot v1), an ordered `insights` page, and `next_cursor` (opaque cursor or JSON `null`). The first request takes optional `limit`; continuation requests supply optional query parameter `cursor`. Use the exact snapshot watermark for both metrics and insights. Insights sort by `(trigger_sequence, rule_id, team_id-or-empty-string, insight_id)`; evidence IDs sort by event sequence.

The first request accepts optional `limit` (default 100; range 1–100) and no cursor. It captures one finalized snapshot and returns an opaque `next_cursor` when another page exists; clients continue by supplying that cursor, not by selecting a new watermark or raw offset. Every page is sorted by `(trigger_sequence, rule_id, team_id-or-empty-string, insight_id)`. A cursor pins `match_id`, `simulation_run_id`, metric-definition version, all rule versions, finalized `as_of.sequence` and exact `as_of.event_id`, the selected page limit, and the position immediately after the last returned insight (the full ordering tuple). Its snapshot does not move when later events are ingested.

The cursor format is `<payload-base64url>.<signature-base64url>`. The payload is UTF-8 canonical JSON with an explicit integer `cursor_schema_version`; the signature is HMAC-SHA-256 over the ASCII payload-base64url segment. Encode both segments as unpadded base64url. Use a dedicated `MATCHPULSE_INTELLIGENCE_CURSOR_KEY`, supplied only through untracked local/runtime configuration as base64url for at least 32 random bytes. Keep the key stable while cursors are expected to work; rotation invalidates outstanding cursors. The endpoint fails closed if the key is absent or invalid. Never log the key or decoded cursor payload. Reject cursor strings longer than 2,048 characters before decoding; require strict base64url, valid UTF-8/JSON, exact required fields with no unknown fields, supported cursor schema and rule versions, valid types/ranges, and a constant-time signature comparison. Invalid encoding, signature, structure, or page limit is `400 invalid_intelligence_cursor`. A cursor used with a different path match, run, or current rule/metric version is `409 intelligence_cursor_conflict`; unknown match remains `404`. A continuation request cannot change the page limit. The server also verifies that the cursor's as-of sequence is not beyond the current finalized watermark and, when positive, that its event ID is the immutable event at that sequence; sequence zero requires a null event ID. This prevents forged or mismatched cursors from bypassing bounds or choosing an unstable prefix.

Each page is limited to 100 insights and at most 1 MiB of compact serialized response JSON, reusing the Phase 2 event-page response budget. If the next individual insight cannot fit within the byte budget, return `413 insight_exceeds_page_budget` without advancing the cursor past it. The bounded input is at most 10,000 finalized events and at most 16 MiB of canonical event JSON for one calculation; reject larger snapshots with `413 intelligence_input_limit` before reduction. These Phase 3 limits bound CPU and memory, since the shared replay/materialization plus sorting costs `O(N + I log I)` time and `O(N + I)` memory for `N` input events and `I` insights. Chunked database reads may limit query batches but do not waive the aggregate bounds.

Metrics are for the full pinned prefix even when the insight list is paged. Later ingestion cannot change a page sequence because Phase 2 appends immutable events and commits new events and the finalized watermark atomically. On the first request, read the match/run and finalized watermark once in a read-only transaction, then read only events through that captured watermark. On continuation, use the authenticated snapshot marker and ordering position; subsequent committed events have larger sequences and remain excluded. No writer lock is required. If stored log replay fails validation, fail safely rather than returning partial intelligence.

Behavior:

- Unknown match: the existing safe `404 match_not_found` response.
- No finalized events: `200`, zero counts for both teams, null ratio where denominator is zero, empty insights, `as_of.sequence == 0`, and `as_of.event_id == null`. The match/run/team identities come from the Phase 2 match row; no accepted event is treated as finalized evidence.
- Completed match: return the final snapshot through the finalized `full_time` event; no special prose or status mutation.
- Invalid first-page query parameters: existing request-validation error shape with `422`. Invalid/tampered cursors: `400`; path/run/rule-version mismatches: `409`.
- No insights at the pinned snapshot: return `200` with an empty `insights` array and `next_cursor: null`. A finalized sequence of zero has a null event marker and zero metric counts, as specified above.
- Database unavailable: existing sanitized `503 database_unavailable`; replay/data-integrity failure: sanitized server error, without SQL details or event contents in logs.

Read the match row/watermark and its ordered event prefix in one read-only database transaction. Restrict event queries to the captured match, run, and finalized sequence. The append-only event log and transactionally updated watermark make the captured prefix stable if ingestion commits concurrently; later finalized events appear only in a new first-page snapshot. Do not lock writers for this read.

Phase 2's local API has no authentication and is loopback-only. The new route inherits that development-only boundary; it must not widen bind address or CORS policy. Do not add intelligence tables, alter existing response contracts, or send intelligence over SSE in Phase 3 v1. The event SSE remains the finalized raw-event stream.

## 7. Intended architecture and module seams

Data flow:

`Validated synthetic events → Phase 2 append-only event log → finalized watermark → deterministic metric calculation → deterministic rule evaluation → evidence-linked intelligence response`

Recommended minimal domain seams under `src/matchpulse_sim/intelligence/` (proposed only):

- `contracts.py`: immutable MetricSnapshot/Insight v1 structures and validation.
- `metrics.py`: pure event-count and ratio calculations.
- `rules.py`: pure score-change and rolling activity rule evaluation.
- `identity.py`: canonical stable insight-ID construction.
- Keep API serialization/query orchestration in the existing API layer, not the domain functions.

Reuse `validate_event`, `replay_prefix`, `canonical_json`, Phase 2 match/event models, and finalized watermarks. Do not duplicate event normalization, score/lifecycle reduction, or possession logic. Future narrative generation can consume the structured facts/evidence IDs through its own provider boundary; a frontend can render them with approved templates. Neither changes metric/rule determinism.

## 8. Test acceptance contract

Preserve every Phase 1 and Phase 2 regression. Add tests for:

- Repeated calculation and replay producing identical snapshots, ordered insights, and IDs.
- Phase 1 generator golden digest unchanged.
- Event sequence ordering, equal timestamps, and exact evidence ordering.
- Finalized-only selection, including accepted goal-outcome shots and possession transitions still pending.
- Goal event increments goals but not shots; its linked goal-outcome shot increments shots once.
- Each metric's team/outcome mapping, numerator/denominator, units, zero-shot null ratio, and empty finalized prefix.
- Each activity rule at threshold minus one, threshold, and threshold plus one.
- Inclusive left/right rolling-window boundaries, including events exactly ten minutes apart and just outside it.
- No half-time crossing; first/second-half clock reset; stoppage-time events within their period.
- Multiple equal-time events ordered by sequence.
- One alert on first crossing, suppression while the episode remains active, expiry below threshold, then a new deterministic episode.
- Score-before/after values sourced from Phase 2 replay states and delayed publication until the goal transition finalizes.
- Full replay and incremental recalculation yielding the same results for each finalized prefix.
- Read-only API contract, stable snapshot pagination during concurrent ingestion, missing match, no-finalized-events, completed match, safe database errors, and response byte/page bounds.

Representative example: three finalized home `shot` events at match times 600,000, 900,000, and 1,200,000 ms in the first half yield one `shot_activity` insight at sequence of the third shot, evidence IDs in sequence order, and an inclusive window `[600,000, 1,200,000]`. A fourth home shot at 1,300,000 ms does not emit a duplicate while the episode remains active. After enough finalized first-half clock time that fewer than three qualifying shots remain in the window, the episode resets; a later third qualifying shot can start a new insight. A goal-outcome shot contributes one shot with outcome `goal`; its linked goal contributes one goal and a `score_change` insight only when the goal transition is finalized.

## 9. Computation and phase boundary

Phase 3 computes metrics and insights on demand from finalized, append-only Phase 2 events. It introduces no intelligence persistence tables and no intelligence SSE messages. The existing Phase 2 raw-event SSE contract is unchanged. Results can be recalculated deterministically from the pinned prefix; no result cache or materialized intelligence state is part of v1.

The rule IDs and thresholds, metric list, endpoint path, finalized-only requirement, four-place decimal representation, inclusive window/episode behavior, HMAC-protected snapshot cursor, and bounded input/page budgets are implemented. Phase 3 adds no intelligence table, migration, event-schema change, or Phase 2 response change. Phase 3 is complete, committed, and pushed; Phase 4 consumes its versioned intelligence records without changing them.
