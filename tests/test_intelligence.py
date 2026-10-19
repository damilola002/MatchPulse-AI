from __future__ import annotations

from copy import deepcopy

import pytest

from matchpulse_sim.generator import generate_events
from matchpulse_sim.intelligence.engine import (
    RULE_VERSIONS,
    _activity_insights,
    _ratio_metric,
    calculate_intelligence,
)
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures
from matchpulse_sim.replay import ReplayError


def _activity_event(sequence, match_ms, event_type="shot", team_id="home", period="first_half", period_ms=None):
    if period_ms is None:
        period_ms = match_ms if period == "first_half" else match_ms - 2_700_000
    return {
        "event_id": f"run:{sequence}",
        "sequence": sequence,
        "type": event_type,
        "team_id": team_id,
        "clock": {
            "match_elapsed_ms": match_ms,
            "period_elapsed_ms": period_ms,
            "period": period,
        },
    }


def _activities(events):
    return _activity_insights(
        events,
        match_id="m",
        run_id="r",
        home_team_id="home",
        away_team_id="away",
    )


def _config():
    return MatchConfig(seed=17, match_id="phase3-engine-test", teams=default_fixtures(), scenario=Scenario.BALANCED)


def _calculate(events):
    start = events[0]
    return calculate_intelligence(
        events,
        match_id=start["match_id"],
        simulation_run_id=start["simulation_run_id"],
        home_team_id=start["data"]["home_team"]["team_id"],
        away_team_id=start["data"]["away_team"]["team_id"],
        as_of_sequence=len(events),
        as_of_event_id=events[-1]["event_id"],
    )


def test_decimal_goal_shot_ratio_uses_four_places_and_half_even():
    assert _ratio_metric(0, 0) == {
        "value": None, "unit": "goals_per_shot", "numerator": 0, "denominator": 0
    }
    assert _ratio_metric(1, 32)["value"] == "0.0312"
    assert _ratio_metric(3, 32)["value"] == "0.0938"
    assert _ratio_metric(1, 3)["value"] == "0.3333"


def test_threshold_boundaries_inclusive_window_and_sequence_ties():
    events = [
        _activity_event(1, 0),
        _activity_event(2, 300_000),
        _activity_event(3, 600_000),
    ]
    insights = _activities(events)
    assert len(insights) == 1
    assert insights[0]["rule_id"] == "shot_activity"
    assert insights[0]["trigger_sequence"] == 3
    assert insights[0]["evidence_event_ids"] == ["run:1", "run:2", "run:3"]
    assert insights[0]["window"] == {
        "start_match_elapsed_ms": 0,
        "end_match_elapsed_ms": 600_000,
        "inclusive": True,
    }

    equal_time = [_activity_event(sequence, 1_000) for sequence in range(1, 4)]
    tied = _activities(equal_time)
    assert len(tied) == 1
    assert tied[0]["trigger_sequence"] == 3
    assert tied[0]["evidence_event_ids"] == ["run:1", "run:2", "run:3"]


def test_event_just_outside_window_does_not_satisfy_threshold():
    events = [
        _activity_event(1, 0),
        _activity_event(2, 300_001),
        _activity_event(3, 600_001),
    ]
    assert _activities(events) == []


def test_stoppage_time_is_evaluated_in_the_same_half_clock():
    events = [
        _activity_event(1, 2_700_000),
        _activity_event(2, 3_000_000),
        _activity_event(3, 3_300_000),
    ]
    result = _activities(events)
    assert len(result) == 1
    assert result[0]["period"] == "first_half"
    assert result[0]["window"] == {
        "start_match_elapsed_ms": 2_700_000,
        "end_match_elapsed_ms": 3_300_000,
        "inclusive": True,
    }


def test_episode_suppresses_then_rearms_on_nonqualifying_clock_advance():
    events = [
        _activity_event(1, 0),
        _activity_event(2, 100_000),
        _activity_event(3, 200_000),
        _activity_event(4, 250_000),
        _activity_event(5, 800_001, event_type="pass"),
        _activity_event(6, 900_000),
        _activity_event(7, 1_000_000),
        _activity_event(8, 1_100_000),
    ]
    insights = _activities(events)
    assert len(insights) == 2
    assert [item["trigger_sequence"] for item in insights] == [3, 8]
    assert insights[0]["insight_id"] != insights[1]["insight_id"]


def test_period_boundary_resets_activity_and_never_crosses_halves():
    events = [
        _activity_event(1, 0),
        _activity_event(2, 100_000),
        _activity_event(3, 2_700_000, "half_time"),
        _activity_event(4, 2_700_000, "second_half_start", period="second_half", period_ms=0),
        _activity_event(5, 2_700_000, "shot", period="second_half", period_ms=0),
    ]
    assert _activities(events) == []
    events.extend(
        [
            _activity_event(6, 2_800_000, period="second_half"),
            _activity_event(7, 2_900_000, period="second_half"),
        ]
    )
    result = _activities(events)
    assert len(result) == 1
    assert result[0]["period"] == "second_half"
    assert result[0]["window"]["start_match_elapsed_ms"] == 2_700_000


def test_pressure_threshold_and_rule_versions_are_stable():
    events = [_activity_event(i, i * 10, event_type="pressure") for i in range(1, 6)]
    first = _activities(events)
    second = _activities(deepcopy(events))
    assert RULE_VERSIONS == {
        "score_change": "1.0.0",
        "shot_activity": "1.0.0",
        "pressure_activity": "1.0.0",
    }
    assert len(first) == 1
    assert first == second
    assert first[0]["rule_id"] == "pressure_activity"
    assert first[0]["evidence_event_ids"] == ["run:1", "run:2", "run:3", "run:4"]


def test_metrics_score_change_and_replay_are_deterministic():
    events = generate_events(_config())
    snapshot, insights = _calculate(events)
    second_snapshot, second_insights = _calculate(deepcopy(events))
    assert snapshot == second_snapshot
    assert insights == second_insights
    assert snapshot["synthetic"] is True
    assert snapshot["as_of"]["sequence"] == len(events)
    for team in snapshot["teams"]:
        team_events = [event for event in events if event.get("team_id") == team["team_id"]]
        goals = sum(event["type"] == "goal" for event in team_events)
        shots = sum(event["type"] == "shot" for event in team_events)
        metric = team["metrics"]
        assert metric["goals"]["value"] == goals
        assert metric["shots"]["value"] == shots
        assert metric["goals_per_shot"]["numerator"] == goals
        assert metric["goals_per_shot"]["denominator"] == shots
        assert sum(outcome["value"] for outcome in metric["shot_outcomes"].values()) == shots
    score_changes = [item for item in insights if item["rule_id"] == "score_change"]
    assert len(score_changes) == sum(event["type"] == "goal" for event in events)
    for insight in score_changes:
        goal = next(event for event in events if event["event_id"] == insight["trigger_event_id"])
        assert insight["evidence_event_ids"] == [goal["event_id"]]
        assert insight["observed_facts"]["score_after"]["home"] + insight["observed_facts"]["score_after"]["away"] == (
            insight["observed_facts"]["score_before"]["home"]
            + insight["observed_facts"]["score_before"]["away"]
            + 1
        )


def test_insight_ids_survive_recalculation_of_later_finalized_prefix():
    events = generate_events(_config())
    goal_indexes = [index for index, event in enumerate(events) if event["type"] == "goal"]
    prefix_end = goal_indexes[-1] + 2  # include the goal restart closing the transition
    prefix = events[:prefix_end]
    early_snapshot, early = _calculate(prefix)
    full_snapshot, full = _calculate(events)
    early_ids = {item["insight_id"] for item in early}
    full_by_id = {item["insight_id"]: item for item in full}
    assert early_ids <= set(full_by_id)
    assert all(item == full_by_id[item["insight_id"]] for item in early)
    assert early_snapshot["as_of"]["sequence"] < full_snapshot["as_of"]["sequence"]


def test_empty_finalized_prefix_returns_zero_metrics_and_null_ratios():
    fixtures = default_fixtures()
    snapshot, insights = calculate_intelligence(
        [],
        match_id="empty-prefix-match",
        simulation_run_id="a" * 32,
        home_team_id=fixtures[0].team_id,
        away_team_id=fixtures[1].team_id,
        as_of_sequence=0,
        as_of_event_id=None,
    )
    assert insights == []
    assert snapshot["as_of"] == {"sequence": 0, "event_id": None, "match_elapsed_ms": None}
    assert all(team["metrics"]["goals_per_shot"]["value"] is None for team in snapshot["teams"])


def test_pending_goal_transition_cannot_be_advertised_as_finalized():
    events = generate_events(_config())
    index = next(
        i for i, event in enumerate(events)
        if event["type"] == "shot" and event["outcome"] == "goal"
    )
    pending_prefix = events[: index + 1]
    start = events[0]
    with pytest.raises(ReplayError, match="finalized"):
        calculate_intelligence(
            pending_prefix,
            match_id=start["match_id"],
            simulation_run_id=start["simulation_run_id"],
            home_team_id=start["data"]["home_team"]["team_id"],
            away_team_id=start["data"]["away_team"]["team_id"],
            as_of_sequence=len(pending_prefix),
            as_of_event_id=pending_prefix[-1]["event_id"],
        )
