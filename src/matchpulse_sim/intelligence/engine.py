"""Pure calculations for Phase 3 metrics and explainable insights."""

from __future__ import annotations

from collections import deque
from decimal import Decimal, ROUND_HALF_EVEN
from bisect import bisect_left
from hashlib import sha256
from typing import Any

from ..replay import MatchState, ReplayError, replay_prefix_with_history
from ..serialization import canonical_json

SCHEMA_VERSION = 1
METRIC_DEFINITION_VERSION = "1.0.0"
RULE_VERSIONS = {
    "score_change": "1.0.0",
    "shot_activity": "1.0.0",
    "pressure_activity": "1.0.0",
}
ACTIVITY_WINDOW_MS = 600_000
SHOT_THRESHOLD = 3
PRESSURE_THRESHOLD = 4
SHOT_OUTCOMES = ("goal", "saved", "blocked", "off_target", "woodwork")


def _count_metric(value: int, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "numerator": value, "denominator": 1}


def _ratio_metric(goals: int, shots: int) -> dict[str, Any]:
    value: str | None
    if shots == 0:
        value = None
    else:
        value = format(
            (Decimal(goals) / Decimal(shots)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN),
            ".4f",
        )
    return {
        "value": value,
        "unit": "goals_per_shot",
        "numerator": goals,
        "denominator": shots,
    }


def _event_sort_key(insight: dict[str, Any]) -> tuple[int, str, str, str]:
    return (
        insight["trigger_sequence"],
        insight["rule_id"],
        insight["team_id"] or "",
        insight["insight_id"],
    )


def _insight_id(
    *,
    match_id: str,
    run_id: str,
    rule_id: str,
    team_id: str | None,
    period: str,
    trigger_event_id: str,
    evidence_event_ids: list[str],
) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "match_id": match_id,
        "simulation_run_id": run_id,
        "rule_id": rule_id,
        "rule_version": RULE_VERSIONS[rule_id],
        "team_id": team_id,
        "period": period,
        "trigger_event_id": trigger_event_id,
        "evidence_event_ids": evidence_event_ids,
    }
    return "insight:v1:" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()


def _make_insight(
    *,
    match_id: str,
    run_id: str,
    rule_id: str,
    team_id: str | None,
    event: dict[str, Any],
    window_start: int | None,
    evidence: list[dict[str, Any]],
    observed_facts: dict[str, Any],
    threshold: dict[str, Any] | None,
) -> dict[str, Any]:
    event_clock = event["clock"]
    evidence_ids = [item["event_id"] for item in evidence]
    period = event_clock["period"]
    return {
        "schema_version": SCHEMA_VERSION,
        "insight_id": _insight_id(
            match_id=match_id,
            run_id=run_id,
            rule_id=rule_id,
            team_id=team_id,
            period=period,
            trigger_event_id=event["event_id"],
            evidence_event_ids=evidence_ids,
        ),
        "match_id": match_id,
        "simulation_run_id": run_id,
        "synthetic": True,
        "rule_id": rule_id,
        "rule_version": RULE_VERSIONS[rule_id],
        "team_id": team_id,
        "period": period,
        "clock": {
            "match_elapsed_ms": event_clock["match_elapsed_ms"],
            "period_elapsed_ms": event_clock["period_elapsed_ms"],
        },
        "trigger_event_id": event["event_id"],
        "trigger_sequence": event["sequence"],
        "window": (
            {
                "start_match_elapsed_ms": window_start,
                "end_match_elapsed_ms": event_clock["match_elapsed_ms"],
                "inclusive": True,
            }
            if window_start is not None
            else None
        ),
        "observed_facts": observed_facts,
        "threshold": threshold,
        "evidence_event_ids": evidence_ids,
    }


def _score_change_insights(
    events: list[dict[str, Any]],
    stable_history: tuple[tuple[int, MatchState], ...],
    *,
    match_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    history_by_sequence = dict(stable_history)
    stable_sequences = [sequence for sequence, _ in stable_history]
    insights: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if event["type"] != "goal":
            continue
        goal_sequence = event["sequence"]
        # The Phase 1 reducer requires a goal restart immediately after the goal;
        # only its stable state closes the score transition for public reporting.
        if index + 1 >= len(events):
            raise ReplayError("finalized goal has no finalized goal-restart transition")
        closing_event = events[index + 1]
        if (
            closing_event["type"] != "possession_change"
            or closing_event["data"]["reason"] != "goal_restart"
            or closing_event["data"]["cause_event_id"] != event["event_id"]
        ):
            raise ReplayError("finalized goal is missing its required goal-restart transition")
        before_index = bisect_left(stable_sequences, goal_sequence) - 1
        after = history_by_sequence.get(closing_event["sequence"])
        if before_index < 0 or after is None:
            raise ReplayError("replay history is missing the finalized score transition")
        before = history_by_sequence[stable_sequences[before_index]]
        team_id = event["team_id"]
        before_score = {"home": before.home_score, "away": before.away_score}
        after_score = {"home": after.home_score, "away": after.away_score}
        if team_id == before.home_team_id:
            valid_change = after_score == {"home": before.home_score + 1, "away": before.away_score}
        else:
            valid_change = after_score == {"home": before.home_score, "away": before.away_score + 1}
        if not valid_change:
            raise ReplayError("replay history does not contain the expected one-goal score change")
        insights.append(
            _make_insight(
                match_id=match_id,
                run_id=run_id,
                rule_id="score_change",
                team_id=team_id,
                event=event,
                window_start=None,
                evidence=[event],
                observed_facts={"score_before": before_score, "score_after": after_score},
                threshold=None,
            )
        )
    return insights


def _activity_insights(
    events: list[dict[str, Any]],
    *,
    match_id: str,
    run_id: str,
    home_team_id: str,
    away_team_id: str,
) -> list[dict[str, Any]]:
    thresholds = {
        "shot_activity": ("shot", SHOT_THRESHOLD, "shots", "qualifying_shot_count"),
        "pressure_activity": ("pressure", PRESSURE_THRESHOLD, "events", "qualifying_pressure_event_count"),
    }
    period_start = {"first_half": 0}
    current_period: str | None = None
    last_clock = -1
    queues: dict[tuple[str, str], deque[dict[str, Any]]] = {}
    active: dict[tuple[str, str], bool] = {}
    insights: list[dict[str, Any]] = []

    for event in events:
        clock = event["clock"]
        period = clock["period"]
        match_clock = clock["match_elapsed_ms"]
        if period != current_period:
            if period == "second_half":
                period_start["second_half"] = match_clock
            current_period = period
            queues.clear()
            active.clear()
            last_clock = -1

        clock_advanced = match_clock > last_clock
        if clock_advanced:
            for rule_id in thresholds:
                for team_id in (home_team_id, away_team_id):
                    key = (rule_id, team_id)
                    queue = queues.setdefault(key, deque())
                    while queue and queue[0]["clock"]["match_elapsed_ms"] < match_clock - ACTIVITY_WINDOW_MS:
                        queue.popleft()
                    if active.get(key, False) and len(queue) < thresholds[rule_id][1]:
                        active[key] = False

        last_clock = max(last_clock, match_clock)
        event_type = event["type"]
        if event_type not in ("shot", "pressure") or event.get("team_id") is None:
            continue
        rule_id = "shot_activity" if event_type == "shot" else "pressure_activity"
        _, threshold, unit, count_key = thresholds[rule_id]
        team_id = event["team_id"]
        key = (rule_id, team_id)
        queue = queues.setdefault(key, deque())
        # Match-start period setup can leave no queue entry for the event's team;
        # filter again at the candidate time before inserting it.
        while queue and queue[0]["clock"]["match_elapsed_ms"] < match_clock - ACTIVITY_WINDOW_MS:
            queue.popleft()
        queue.append(event)
        if not active.get(key, False) and len(queue) >= threshold:
            insights.append(
                _make_insight(
                    match_id=match_id,
                    run_id=run_id,
                    rule_id=rule_id,
                    team_id=team_id,
                    event=event,
                    window_start=max(period_start[period], match_clock - ACTIVITY_WINDOW_MS),
                    evidence=list(queue),
                    observed_facts={count_key: len(queue)},
                    threshold={"operator": ">=", "value": threshold, "unit": unit},
                )
            )
            active[key] = True
    return insights


def _metrics(
    events: list[dict[str, Any]], *, home_team_id: str, away_team_id: str
) -> list[dict[str, Any]]:
    teams = {home_team_id: "home", away_team_id: "away"}
    goals = {team_id: 0 for team_id in teams}
    shots = {team_id: 0 for team_id in teams}
    pressure = {team_id: 0 for team_id in teams}
    outcomes = {team_id: {name: 0 for name in SHOT_OUTCOMES} for team_id in teams}
    for event in events:
        event_type = event["type"]
        team_id = event.get("team_id")
        if event_type == "goal" and team_id in goals:
            goals[team_id] += 1
        elif event_type == "shot" and team_id in shots:
            shots[team_id] += 1
            outcomes[team_id][event["outcome"]] += 1
        elif event_type == "pressure" and team_id in pressure:
            pressure[team_id] += 1
    result = []
    for team_id in (home_team_id, away_team_id):
        result.append(
            {
                "team_id": team_id,
                "role": teams[team_id],
                "metrics": {
                    "goals": _count_metric(goals[team_id], "goals"),
                    "shots": _count_metric(shots[team_id], "shots"),
                    "shot_outcomes": {
                        outcome: _count_metric(outcomes[team_id][outcome], "shots")
                        for outcome in SHOT_OUTCOMES
                    },
                    "logged_pressure_events": _count_metric(pressure[team_id], "events"),
                    "goals_per_shot": _ratio_metric(goals[team_id], shots[team_id]),
                },
            }
        )
    return result


def calculate_intelligence(
    events: list[dict[str, Any]],
    *,
    match_id: str,
    simulation_run_id: str,
    home_team_id: str,
    away_team_id: str,
    as_of_sequence: int,
    as_of_event_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate and calculate one finalized prefix without side effects."""
    if as_of_sequence == 0:
        if events or as_of_event_id is not None:
            raise ReplayError("empty finalized prefix must have no events or event ID")
        as_of = {"sequence": 0, "event_id": None, "match_elapsed_ms": None}
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "match_id": match_id,
                "simulation_run_id": simulation_run_id,
                "synthetic": True,
                "metric_definition_version": METRIC_DEFINITION_VERSION,
                "as_of": as_of,
                "teams": _metrics([], home_team_id=home_team_id, away_team_id=away_team_id),
            },
            [],
        )
    if len(events) != as_of_sequence or events[-1]["event_id"] != as_of_event_id:
        raise ReplayError("event prefix does not match its finalized watermark")
    progress, stable_history = replay_prefix_with_history(events)
    if (
        progress.finalized_sequence != as_of_sequence
        or progress.accepted_sequence != as_of_sequence
        or progress.pending_transition is not None
        or progress.state.match_id != match_id
        or progress.state.simulation_run_id != simulation_run_id
        or progress.state.home_team_id != home_team_id
        or progress.state.away_team_id != away_team_id
    ):
        raise ReplayError("event prefix failed finalized match identity or replay checks")
    as_of = {
        "sequence": as_of_sequence,
        "event_id": as_of_event_id,
        "match_elapsed_ms": events[-1]["clock"]["match_elapsed_ms"],
    }
    for event in events:
        if not event["provenance"]["synthetic"]:
            raise ReplayError("intelligence inputs must be labeled synthetic")
    insights = _score_change_insights(
        events, stable_history, match_id=match_id, run_id=simulation_run_id
    )
    insights.extend(
        _activity_insights(
            events,
            match_id=match_id,
            run_id=simulation_run_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )
    )
    insights.sort(key=_event_sort_key)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "match_id": match_id,
        "simulation_run_id": simulation_run_id,
        "synthetic": True,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "as_of": as_of,
        "teams": _metrics(events, home_team_id=home_team_id, away_team_id=away_team_id),
    }
    return snapshot, insights
