from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib

import pytest

from matchpulse_sim import serialization
from matchpulse_sim.cli import main as cli_main
from matchpulse_sim.generator import GENERATOR_VERSION, generate_events
from matchpulse_sim.models import (
    MatchConfig,
    Period,
    SCENARIO_MIN_PERIOD_DURATION_MS,
    SCENARIO_SCHEDULES,
    Scenario,
    TeamFixture,
    PlayerFixture,
    default_fixtures,
)
from matchpulse_sim.replay import ReplayError, replay_events
from matchpulse_sim.serialization import read_event_input_file, read_json, read_jsonl, write_json, write_jsonl
from matchpulse_sim.validation import EventValidationError, event_schema, validate_event


def _renumber(events):
    result = deepcopy(events)
    old_ids = [event["event_id"] for event in result]
    run_id = result[0]["simulation_run_id"]
    assigned_ids = [f"{run_id}:{index}" for index in range(1, len(result) + 1)]
    reference_mapping = {}
    for old_id, new_id in zip(old_ids, assigned_ids):
        reference_mapping.setdefault(old_id, new_id)
    for index, event in enumerate(result, start=1):
        event["sequence"] = index
        event["event_id"] = assigned_ids[index - 1]
        event["causal_event_ids"] = [reference_mapping.get(x, x) for x in event["causal_event_ids"]]
        data = event["data"]
        for key in ("cause_event_id", "source_shot_event_id"):
            if data.get(key) in reference_mapping:
                data[key] = reference_mapping[data[key]]
    return result


def test_same_seed_and_configuration_produce_identical_canonical_bytes(config_factory):
    config = config_factory()
    first = write_jsonl(generate_events(config)).encode("utf-8")
    second = write_jsonl(generate_events(config)).encode("utf-8")
    assert first == second
    assert GENERATOR_VERSION == "1.0.0"


def test_generator_v1_golden_canonical_jsonl_digest():
    config = MatchConfig(
        seed=17,
        match_id="golden-balanced-17",
        teams=default_fixtures(),
        scenario=Scenario.BALANCED,
    )
    canonical_bytes = write_jsonl(generate_events(config)).encode("utf-8")
    assert GENERATOR_VERSION == "1.0.0"
    assert hashlib.sha256(canonical_bytes).hexdigest() == "71567e757f54037ef84bc58ef35ab65af4f04c1d77ac3b54c24c388f94df7bce"


def test_scenario_minimums_are_derived_from_immutable_generation_schedule():
    for scenario, attacks in SCENARIO_SCHEDULES.items():
        expected = tuple(
            max((attack.minute for attack in attacks if attack.period is period), default=0) * 60_000
            for period in (Period.FIRST_HALF, Period.SECOND_HALF)
        )
        assert SCENARIO_MIN_PERIOD_DURATION_MS[scenario] == expected
    with pytest.raises(TypeError):
        SCENARIO_SCHEDULES[Scenario.BALANCED] = ()
    with pytest.raises(TypeError):
        SCENARIO_MIN_PERIOD_DURATION_MS[Scenario.BALANCED] = (0, 0)


def test_different_seeds_produce_different_valid_sequences(config_factory):
    outputs = {write_jsonl(generate_events(config_factory(seed=seed))) for seed in range(8)}
    assert len(outputs) > 1
    for seed in range(8):
        assert replay_events(generate_events(config_factory(seed=seed))).status == "ended"


def test_ids_are_stable_unique_and_match_sequence(config_factory):
    events = generate_events(config_factory())
    assert len({event["event_id"] for event in events}) == len(events)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    run_id = events[0]["simulation_run_id"]
    assert all(event["event_id"] == f"{run_id}:{event['sequence']}" for event in events)
    assert all(event["simulation_run_id"] == run_id for event in events)


def test_all_taxonomy_types_are_generated(config_factory):
    observed = {
        event["type"]
        for scenario in Scenario
        for event in generate_events(config_factory(scenario=scenario))
    }
    assert observed == {
        "match_start", "pass", "shot", "goal", "tackle", "ball_recovery",
        "possession_change", "pressure", "foul", "half_time", "second_half_start", "full_time",
    }


def test_scenario_score_and_distribution_constraints(config_factory):
    balanced = generate_events(config_factory(Scenario.BALANCED))
    balanced_state = replay_events(balanced)
    assert balanced_state.home_score == balanced_state.away_score == 1
    assert abs(balanced_state.home_shots - balanced_state.away_shots) <= 2

    comeback = generate_events(config_factory(Scenario.LATE_COMEBACK))
    comeback_state = replay_events(comeback)
    assert (comeback_state.home_score, comeback_state.away_score) == (2, 3)
    late_away_goals = [e for e in comeback if e["type"] == "goal" and e["team_id"] == comeback_state.away_team_id]
    assert [e["clock"]["period_elapsed_ms"] // 60_000 for e in late_away_goals[-2:]] == [39, 44]

    pressure = generate_events(config_factory(Scenario.SUSTAINED_PRESSURE))
    pressure_state = replay_events(pressure)
    assert pressure_state.home_shots >= pressure_state.away_shots * 2

    low = generate_events(config_factory(Scenario.LOW_EVENT))
    low_state = replay_events(low)
    assert low_state.home_score == low_state.away_score == 0
    assert low_state.home_shots + low_state.away_shots <= 3


def test_fixture_output_is_explicitly_synthetic(config_factory):
    for event in generate_events(config_factory()):
        assert event["provenance"]["synthetic"] is True
        assert event["provenance"]["generator"] == "matchpulse-sim"


def test_schema_rejects_unsupported_version_and_unknown_fields(config_factory):
    event = deepcopy(generate_events(config_factory())[1])
    event["schema_version"] = 2
    with pytest.raises(EventValidationError, match="unsupported schema version"):
        validate_event(event)
    event = deepcopy(generate_events(config_factory())[1])
    event["unapproved_field"] = True
    with pytest.raises(EventValidationError):
        validate_event(event)
    assert event_schema()["$schema"].endswith("2020-12/schema")


def test_schema_rejects_unknown_type_specific_fields(config_factory):
    event = next(e for e in generate_events(config_factory()) if e["type"] == "pass")
    malformed = deepcopy(event)
    malformed["data"]["mystery"] = 1
    with pytest.raises(EventValidationError):
        validate_event(malformed)


def test_schema_rejects_stoppage_time_above_supported_limit(config_factory):
    event = deepcopy(generate_events(config_factory())[0])
    event["data"]["first_half_stoppage_ms"] = 10 * 60_000 + 1
    with pytest.raises(EventValidationError):
        validate_event(event)


def test_location_bounds_are_enforced(config_factory):
    event = next(e for e in generate_events(config_factory()) if e["location"] is not None)
    malformed = deepcopy(event)
    malformed["location"]["x"] = 101
    with pytest.raises(EventValidationError):
        validate_event(malformed)
    shot = deepcopy(next(e for e in generate_events(config_factory()) if e["type"] == "shot"))
    shot["data"]["target_location"]["y"] = -1
    with pytest.raises(EventValidationError):
        validate_event(shot)
    assert all(
        0 <= coordinate <= 100
        for item in generate_events(config_factory())
        for location_key in ("location",)
        if item[location_key] is not None
        for coordinate in item[location_key].values()
    )


def test_attacking_direction_and_period_clock_conventions(config_factory):
    events = generate_events(config_factory())
    start = events[0]["data"]
    halftime = next(e for e in events if e["type"] == "half_time")
    assert halftime["clock"]["period"] == "first_half"
    assert halftime["clock"]["period_elapsed_ms"] == (
        start["first_half_regulation_ms"] + start["first_half_stoppage_ms"]
    )
    assert halftime["clock"]["period_elapsed_ms"] > start["first_half_regulation_ms"]
    shots = [e for e in events if e["type"] == "shot"]
    home_id = start["home_team"]["team_id"]
    away_id = start["away_team"]["team_id"]
    for shot in shots:
        period = shot["clock"]["period"]
        x = shot["location"]["x"]
        if (shot["team_id"] == home_id and period == "first_half") or (
            shot["team_id"] == away_id and period == "second_half"
        ):
            assert x >= 82
        else:
            assert x <= 18
    second_start = next(e for e in events if e["type"] == "second_half_start")
    first_duration = start["first_half_regulation_ms"] + start["first_half_stoppage_ms"]
    assert second_start["clock"]["period_elapsed_ms"] == 0
    assert second_start["clock"]["match_elapsed_ms"] == first_duration


def test_clock_is_non_decreasing_and_sequences_are_contiguous(config_factory):
    events = generate_events(config_factory())
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    elapsed = [e["clock"]["match_elapsed_ms"] for e in events]
    assert elapsed == sorted(elapsed)
    assert any(a == b for a, b in zip(elapsed, elapsed[1:]))
    malformed = deepcopy(events)
    malformed[4]["clock"]["match_elapsed_ms"] = 0
    with pytest.raises(ReplayError, match="non-decreasing"):
        replay_events(malformed)


def test_goal_linkage_and_only_goal_events_increment_score(config_factory):
    events = generate_events(config_factory(Scenario.BALANCED))
    shots = {e["event_id"]: e for e in events if e["type"] == "shot"}
    goals = [e for e in events if e["type"] == "goal"]
    assert all(shots[g["data"]["source_shot_event_id"]]["outcome"] == "goal" for g in goals)
    assert len({g["data"]["source_shot_event_id"] for g in goals}) == len(goals)
    state = replay_events(events)
    assert state.home_score + state.away_score == len(goals)
    assert state.home_shots + state.away_shots == sum(e["type"] == "shot" for e in events)

    malformed = [deepcopy(e) for e in events if e["type"] != "goal"]
    # Keep the following transition attributable to the shot so replay reaches
    # the specific missing-goal invariant before considering dangling causes.
    removed_goal_ids = {e["event_id"] for e in events if e["type"] == "goal"}
    goal_shots = {e["event_id"]: e["data"]["source_shot_event_id"] for e in events if e["type"] == "goal"}
    for event in malformed:
        if event["type"] == "possession_change" and event["data"]["cause_event_id"] in removed_goal_ids:
            source_id = goal_shots[event["data"]["cause_event_id"]]
            event["data"]["cause_event_id"] = source_id
            event["causal_event_ids"] = [source_id]
    with pytest.raises(ReplayError, match="followed immediately by its goal"):
        replay_events(_renumber(malformed))

    goal_index = next(i for i, e in enumerate(events) if e["type"] == "goal")
    goal_restart_index = next(
        i for i in range(goal_index + 1, len(events))
        if events[i]["type"] == "possession_change"
        and events[i]["data"]["reason"] == "goal_restart"
    )
    duplicated = events[: goal_restart_index + 1] + [deepcopy(events[goal_index])] + events[goal_restart_index + 1 :]
    malformed_duplicate = _renumber(duplicated)
    assert [event["sequence"] for event in malformed_duplicate] == list(range(1, len(malformed_duplicate) + 1))
    assert len({event["event_id"] for event in malformed_duplicate}) == len(malformed_duplicate)
    assert all(event["event_id"] == f"{event['simulation_run_id']}:{event['sequence']}" for event in malformed_duplicate)
    with pytest.raises(ReplayError, match="goal must correspond to exactly one immediately preceding goal-outcome shot"):
        replay_events(malformed_duplicate)


def test_possession_changes_are_the_only_state_transitions(config_factory):
    events = generate_events(config_factory())
    transitions = [e for e in events if e["type"] == "possession_change"]
    assert transitions
    malformed = deepcopy(events)
    transition = next(e for e in malformed if e["type"] == "possession_change" and e["data"]["from_team_id"] is not None)
    transition["data"]["from_team_id"] = "unrelated-team"
    with pytest.raises(ReplayError, match="required transition"):
        replay_events(malformed)


def test_roster_membership_is_enforced(config_factory):
    events = deepcopy(generate_events(config_factory()))
    passed = next(e for e in events if e["type"] == "pass")
    passed["data"]["receiver_player_id"] = "not-a-match-player"
    with pytest.raises(ReplayError, match="receiver"):
        replay_events(events)


def test_lifecycle_and_possession_boundaries(config_factory):
    events = generate_events(config_factory())
    types = [e["type"] for e in events]
    assert types[0] == "match_start"
    assert types[-1] == "full_time"
    half_index = types.index("half_time")
    second_index = types.index("second_half_start")
    assert half_index < second_index < len(types) - 1
    assert events[half_index - 1]["type"] == "possession_change"
    assert events[half_index - 1]["data"]["to_team_id"] is None
    assert events[second_index + 1]["type"] == "possession_change"
    assert events[second_index + 1]["data"]["from_team_id"] is None
    assert events[-2]["type"] == "possession_change"
    assert events[-2]["data"]["to_team_id"] is None
    state = replay_events(events)
    assert state.status == "ended"
    assert state.period == "second_half"
    assert state.current_possession is None
    post_full_time = deepcopy(events[-1])
    post_full_time["sequence"] = len(events) + 1
    post_full_time["event_id"] = f"{post_full_time['simulation_run_id']}:{len(events) + 1}"
    with pytest.raises(ReplayError, match="after full_time"):
        replay_events(events + [post_full_time])


def test_json_and_jsonl_round_trips_are_canonical(config_factory):
    events = generate_events(config_factory())
    json_text = write_json(events)
    jsonl_text = write_jsonl(events)
    assert read_json(json_text) == events
    assert read_jsonl(jsonl_text) == events
    assert write_json(read_json(json_text)) == json_text
    assert write_jsonl(read_jsonl(jsonl_text)) == jsonl_text
    assert jsonl_text.endswith("\n")
    assert read_json(json_text)[0]["schema_version"] == 1
    with pytest.raises(EventValidationError, match="blank"):
        read_jsonl(jsonl_text + "\n")


@pytest.mark.parametrize("format_name", ["json", "jsonl"])
def test_text_and_file_input_limits_at_and_above_boundary(config_factory, monkeypatch, tmp_path, capsys, format_name):
    events = generate_events(config_factory())
    text = write_json(events) if format_name == "json" else write_jsonl(events)
    raw = text.encode("utf-8")
    exact_limit = len(raw)
    reader = read_json if format_name == "json" else read_jsonl

    monkeypatch.setattr(serialization, "MAX_EVENT_INPUT_BYTES", exact_limit)
    assert reader(text) == events
    input_path = tmp_path / f"match.{format_name}"
    input_path.write_bytes(raw)
    assert read_event_input_file(input_path) == text
    assert cli_main(["replay", str(input_path)]) == 0
    assert '"status":"ended"' in capsys.readouterr().out

    monkeypatch.setattr(serialization, "MAX_EVENT_INPUT_BYTES", exact_limit - 1)
    with pytest.raises(EventValidationError, match="maximum input size"):
        reader(text)
    with pytest.raises(EventValidationError, match="maximum input size"):
        read_event_input_file(input_path)
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["replay", str(input_path)])
    assert exc_info.value.code == 2
    assert "maximum input size" in capsys.readouterr().err


def test_invalid_configuration_is_rejected():
    teams = default_fixtures()
    with pytest.raises(ValueError, match="seed"):
        MatchConfig(seed=True, match_id="m1", teams=teams)
    with pytest.raises(ValueError, match="unsupported scenario"):
        MatchConfig(seed=1, match_id="m1", teams=teams, scenario="unknown")
    with pytest.raises(ValueError, match="stoppage"):
        MatchConfig(seed=1, match_id="m1", teams=teams, first_half_stoppage_ms=-1)
    duplicated_player = PlayerFixture("shared-player", "Fictional Player")
    home = TeamFixture("home", "Home Fiction", (duplicated_player,))
    away = TeamFixture("away", "Away Fiction", (duplicated_player,))
    with pytest.raises(ValueError, match="unique across both teams"):
        MatchConfig(seed=1, match_id="m1", teams=(home, away))


@pytest.mark.parametrize(
    "scenario,first_minute,second_minute",
    [
        (Scenario.BALANCED, 41, 43),
        (Scenario.LATE_COMEBACK, 39, 44),
        (Scenario.SUSTAINED_PRESSURE, 38, 23),
        (Scenario.LOW_EVENT, 41, 20),
    ],
)
def test_scenario_duration_boundaries(config_factory, scenario, first_minute, second_minute):
    teams = default_fixtures()
    boundary = MatchConfig(
        seed=17,
        match_id="duration-boundary",
        teams=teams,
        scenario=scenario,
        first_half_regulation_ms=first_minute * 60_000,
        first_half_stoppage_ms=0,
        second_half_regulation_ms=second_minute * 60_000,
        second_half_stoppage_ms=0,
    )
    assert replay_events(generate_events(boundary)).status == "ended"

    with pytest.raises(ValueError, match=rf"scenario '{scenario.value}'.*first_half duration"):
        MatchConfig(
            seed=17,
            match_id="below-first-boundary",
            teams=teams,
            scenario=scenario,
            first_half_regulation_ms=first_minute * 60_000 - 1,
            first_half_stoppage_ms=0,
            second_half_regulation_ms=second_minute * 60_000,
            second_half_stoppage_ms=0,
        )
    with pytest.raises(ValueError, match=rf"scenario '{scenario.value}'.*second_half duration"):
        MatchConfig(
            seed=17,
            match_id="below-second-boundary",
            teams=teams,
            scenario=scenario,
            first_half_regulation_ms=first_minute * 60_000,
            first_half_stoppage_ms=0,
            second_half_regulation_ms=second_minute * 60_000 - 1,
            second_half_stoppage_ms=0,
        )


def test_duration_boundary_can_be_met_by_permitted_stoppage(config_factory):
    config = config_factory(Scenario.LATE_COMEBACK)
    minimum = 44 * 60_000
    stoppage_config = MatchConfig(
        seed=config.seed,
        match_id=config.match_id,
        teams=config.teams,
        scenario=config.scenario,
        first_half_regulation_ms=29 * 60_000,
        first_half_stoppage_ms=10 * 60_000,
        second_half_regulation_ms=34 * 60_000,
        second_half_stoppage_ms=10 * 60_000,
    )
    assert stoppage_config.first_half_duration_ms == 39 * 60_000
    assert stoppage_config.second_half_duration_ms == minimum
    assert replay_events(generate_events(stoppage_config)).status == "ended"


def test_previously_accepted_one_minute_half_is_rejected(config_factory):
    config = config_factory()
    with pytest.raises(ValueError, match="scenario 'balanced'.*first_half duration"):
        MatchConfig(
            seed=config.seed,
            match_id=config.match_id,
            teams=config.teams,
            scenario=Scenario.BALANCED,
            first_half_regulation_ms=60_000,
            first_half_stoppage_ms=0,
        )


def test_malformed_first_event_provenance_is_a_replay_error(config_factory):
    events = deepcopy(generate_events(config_factory()))
    events[0]["provenance"] = None
    with pytest.raises(ReplayError, match="event 1: provenance"):
        replay_events(events)


def test_replay_is_deterministic(config_factory):
    events = generate_events(config_factory(Scenario.LATE_COMEBACK, seed=88))
    assert replay_events(events) == replay_events(events)
