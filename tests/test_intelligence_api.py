from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from matchpulse_sim.api.app import create_app
from matchpulse_sim.api.models import Base
from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    database_path = tmp_path / "intelligence-api-test.sqlite"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    key = base64.urlsafe_b64encode(b"phase3-test-key-material-at-least-32-bytes").rstrip(b"=").decode("ascii")
    monkeypatch.setenv("MATCHPULSE_INTELLIGENCE_CURSOR_KEY", key)
    app = create_app(engine)
    with TestClient(app) as client:
        yield client
    Base.metadata.drop_all(engine)
    engine.dispose()


def _events(match_id="phase3-api-match", scenario=Scenario.BALANCED):
    return generate_events(
        MatchConfig(seed=17, match_id=match_id, teams=default_fixtures(), scenario=scenario)
    )


def _start(client, events):
    response = client.post("/api/matches", json={"start_event": events[0]})
    assert response.status_code == 201


def _ingest(client, events):
    match_id = events[0]["match_id"]
    first = 1 if events[0]["sequence"] == 1 else 0
    for start in range(first, len(events), 100):
        response = client.post(
            f"/api/matches/{match_id}/events",
            json={"events": events[start : start + 100]},
        )
        assert response.status_code == 200, response.text


def test_intelligence_api_metrics_and_score_change_output_are_versioned(api_client):
    events = _events()
    _start(api_client, events)
    _ingest(api_client, events)
    state_before = api_client.get(f"/api/matches/{events[0]['match_id']}/state").json()
    response = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["synthetic"] is True
    assert body["as_of"]["sequence"] == len(events)
    assert body["metric_snapshot"]["schema_version"] == 1
    assert body["metric_snapshot"]["as_of"] == body["as_of"]
    assert body["next_cursor"] is None
    state_after = api_client.get(f"/api/matches/{events[0]['match_id']}/state").json()
    assert state_after == state_before
    score_changes = [item for item in body["insights"] if item["rule_id"] == "score_change"]
    assert len(score_changes) == sum(item["type"] == "goal" for item in events)
    assert all(item["synthetic"] and item["rule_version"] == "1.0.0" for item in score_changes)
    sort_keys = [
        (item["trigger_sequence"], item["rule_id"], item["team_id"] or "", item["insight_id"])
        for item in body["insights"]
    ]
    assert sort_keys == sorted(sort_keys)


def test_empty_finalized_prefix_and_unknown_match(api_client):
    events = _events()
    _start(api_client, events)
    empty = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert empty.status_code == 200
    body = empty.json()
    assert body["as_of"] == {"sequence": 0, "event_id": None, "match_elapsed_ms": None}
    assert body["insights"] == []
    assert body["next_cursor"] is None
    assert all(team["metrics"]["goals_per_shot"]["value"] is None for team in body["metric_snapshot"]["teams"])
    missing = api_client.get("/api/matches/no-such-match/intelligence")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "match_not_found"


def test_pending_goal_outcome_shot_is_not_in_finalized_intelligence(api_client):
    events = _events()
    _start(api_client, events)
    pending_shot_index = next(
        index for index, event in enumerate(events)
        if event["type"] == "shot" and event["outcome"] == "goal"
    )
    _ingest(api_client, events[: pending_shot_index + 1])
    response = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert response.status_code == 200, response.text
    body = response.json()
    finalized = body["as_of"]["sequence"]
    assert finalized < events[pending_shot_index]["sequence"]
    expected_shots = sum(
        event["type"] == "shot" and event["team_id"] == events[pending_shot_index]["team_id"]
        for event in events[:finalized]
    )
    team_metrics = next(
        team["metrics"] for team in body["metric_snapshot"]["teams"]
        if team["team_id"] == events[pending_shot_index]["team_id"]
    )
    assert team_metrics["shots"]["value"] == expected_shots


def test_cursor_pins_snapshot_when_later_events_are_committed(api_client):
    events = _events()
    goal_indexes = [index for index, event in enumerate(events) if event["type"] == "goal"]
    prefix_end = goal_indexes[-1] + 2
    _start(api_client, events)
    _ingest(api_client, events[:prefix_end])

    first = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence?limit=1")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["as_of"]["sequence"] == prefix_end
    assert len(first_body["insights"]) == 1
    cursor = first_body["next_cursor"]
    assert isinstance(cursor, str)

    _ingest(api_client, events[prefix_end:])
    continued = api_client.get(
        f"/api/matches/{events[0]['match_id']}/intelligence",
        params={"cursor": cursor},
    )
    assert continued.status_code == 200, continued.text
    body = continued.json()
    assert body["as_of"] == first_body["as_of"]
    assert len(body["insights"]) == 1
    assert body["insights"][0]["trigger_sequence"] > first_body["insights"][0]["trigger_sequence"]
    assert body["next_cursor"] is None


def test_cursor_tampering_mismatch_and_page_size_change_are_rejected(api_client):
    events = _events()
    goal_indexes = [index for index, event in enumerate(events) if event["type"] == "goal"]
    prefix_end = goal_indexes[-1] + 2
    _start(api_client, events)
    _ingest(api_client, events[:prefix_end])
    first = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence?limit=1").json()
    cursor = first["next_cursor"]

    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    invalid = api_client.get(
        f"/api/matches/{events[0]['match_id']}/intelligence", params={"cursor": tampered}
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_intelligence_cursor"

    changed_limit = api_client.get(
        f"/api/matches/{events[0]['match_id']}/intelligence",
        params={"cursor": cursor, "limit": 2},
    )
    assert changed_limit.status_code == 400

    other = _events("different-known-match")
    _start(api_client, other)
    mismatch = api_client.get(
        f"/api/matches/{other[0]['match_id']}/intelligence", params={"cursor": cursor}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "intelligence_cursor_conflict"


def test_cursor_configuration_and_page_bounds_fail_safely(api_client, monkeypatch):
    events = _events()
    _start(api_client, events)
    monkeypatch.delenv("MATCHPULSE_INTELLIGENCE_CURSOR_KEY")
    missing_key = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert missing_key.status_code == 503
    assert missing_key.json()["error"]["code"] == "intelligence_cursor_configuration"
    monkeypatch.setenv("MATCHPULSE_INTELLIGENCE_CURSOR_KEY", "YWJj")
    malformed_key = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert malformed_key.status_code == 503
    assert malformed_key.json()["error"]["code"] == "intelligence_cursor_configuration"

    monkeypatch.setenv(
        "MATCHPULSE_INTELLIGENCE_CURSOR_KEY",
        base64.urlsafe_b64encode(b"phase3-test-key-material-at-least-32-bytes").rstrip(b"=").decode("ascii"),
    )
    invalid_limit = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence?limit=101")
    assert invalid_limit.status_code == 422

    from matchpulse_sim.intelligence import api as intelligence_api

    monkeypatch.setattr(intelligence_api, "MAX_INTELLIGENCE_EVENTS", 1)
    _ingest(api_client, events)
    oversized = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "intelligence_input_limit"
    monkeypatch.setattr(intelligence_api, "MAX_INTELLIGENCE_EVENTS", 10_000)
    monkeypatch.setattr(intelligence_api, "MAX_INTELLIGENCE_INPUT_BYTES", 1)
    oversized_bytes = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert oversized_bytes.status_code == 413
    assert oversized_bytes.json()["error"]["code"] == "intelligence_input_limit"


def test_cursor_length_and_response_byte_budget_are_bounded(api_client, monkeypatch):
    events = _events()
    _start(api_client, events)
    too_long = api_client.get(
        f"/api/matches/{events[0]['match_id']}/intelligence",
        params={"cursor": "a" * 2049},
    )
    assert too_long.status_code == 400

    from matchpulse_sim.intelligence import api as intelligence_api

    monkeypatch.setattr(intelligence_api, "MAX_INTELLIGENCE_PAGE_BYTES", 1)
    _ingest(api_client, events)
    too_large = api_client.get(f"/api/matches/{events[0]['match_id']}/intelligence")
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "insight_exceeds_page_budget"
