from __future__ import annotations

from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import Scenario
from matchpulse_sim.replay import IncrementalReducer, replay_events, replay_prefix


def test_incremental_prefixes_finalize_to_complete_replay(config_factory):
    for scenario in Scenario:
        events = generate_events(config_factory(scenario=scenario))
        reducer = IncrementalReducer()
        for event in events:
            progress = reducer.accept(event)
            assert progress.accepted_sequence == event["sequence"]
            assert progress.finalized_sequence <= progress.accepted_sequence
        assert progress.complete
        assert progress.state == replay_events(events)


def test_pending_goal_is_not_exposed_as_finalized(config_factory):
    events = generate_events(config_factory())
    shot_index = next(i for i, event in enumerate(events) if event["type"] == "shot" and event["outcome"] == "goal")
    progress = replay_prefix(events[:shot_index + 1])
    assert progress.pending_transition is not None
    assert progress.pending_transition["goal_event_id"] == events[shot_index]["event_id"]
    assert progress.finalized_sequence < events[shot_index]["sequence"]
    goals_before_shot = sum(event["type"] == "goal" for event in events[:shot_index])
    assert progress.state.home_score + progress.state.away_score == goals_before_shot
