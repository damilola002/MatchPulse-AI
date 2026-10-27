from __future__ import annotations

import time
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from matchpulse_sim.api.app import create_app
from matchpulse_sim.api.models import Base
from matchpulse_sim.api.service import get_state, ingest_events


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "true")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'demo-test.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    app = create_app(engine)
    with TestClient(app, base_url="http://127.0.0.1:8001", client=("127.0.0.1", 51234)) as client:
        yield client, engine, app
    Base.metadata.drop_all(engine)
    engine.dispose()


def _payload(**overrides):
    return {
        "request_id": str(uuid4()),
        "scenario": "balanced",
        "seed": 17,
        "speed": 20,
        **overrides,
    }


def _wait_for_status(client, request_id, terminal):
    for _ in range(100):
        response = client.get(f"/api/demo/playbacks/{request_id}")
        assert response.status_code == 200
        if response.json()["status"] in terminal:
            return response.json()
        time.sleep(0.01)
    pytest.fail("demo playback did not reach a terminal status")


def test_create_demo_playback_uses_existing_generator_ingestion_and_full_time(demo_client, monkeypatch):
    client, engine, app = demo_client
    import matchpulse_sim.api.app as app_module

    captured = {}

    def complete_playback(events, *, base_url, speed, resume, target_duration_seconds):
        captured.update(base_url=base_url, speed=speed, resume=resume, target_duration_seconds=target_duration_seconds, events=events)
        match_id = events[0]["match_id"]
        for offset in range(1, len(events), 100):
            with Session(engine) as session, session.begin():
                ingest_events(session, match_id, events[offset : offset + 100])
        with Session(engine) as session:
            return get_state(session, match_id)

    monkeypatch.setattr(app_module, "play_events", complete_playback)
    body = _payload(scenario="low_event_defensive", seed=23, speed=5, fast_demo=True)
    response = client.post("/api/demo/playbacks", json=body)
    assert response.status_code == 202
    started = response.json()
    assert started["status"] == "starting"
    assert started["duplicate"] is False
    assert started["match_id"].startswith("demo-")

    completed = _wait_for_status(client, body["request_id"], {"completed", "failed"})
    assert completed["status"] == "completed"
    assert captured["base_url"] == "http://127.0.0.1:8001"
    assert captured["speed"] == 5
    assert captured["resume"] is True
    assert captured["target_duration_seconds"] == 40.0
    assert captured["events"][0]["provenance"]["scenario_id"] == "low_event_defensive"
    assert len(captured["events"]) > 1

    state = client.get(f"/api/matches/{started['match_id']}/state").json()
    assert state["status"] == "ended"
    assert state["last_finalized_sequence"] == len(captured["events"])
    stream = client.get(f"/api/matches/{started['match_id']}/stream")
    event_ids = [line[4:] for line in stream.text.splitlines() if line.startswith("id: ")]
    assert event_ids == [event["event_id"] for event in captured["events"]]


def test_demo_playback_validates_scenario_seed_speed_and_demo_gate(demo_client, monkeypatch):
    client, _, _ = demo_client
    import matchpulse_sim.api.app as app_module

    monkeypatch.setattr(app_module, "play_events", lambda *_args, **_kwargs: None)
    maximum_seed = _payload(seed=(1 << 63) - 1)
    assert client.post("/api/demo/playbacks", json=maximum_seed).status_code == 202
    for invalid in (
        _payload(scenario="unknown"),
        _payload(seed=-1),
        _payload(seed=1 << 63),
        _payload(seed=True),
        _payload(speed=0),
        _payload(speed=3),
    ):
        assert client.post("/api/demo/playbacks", json=invalid).status_code == 422

    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "false")
    assert client.post("/api/demo/playbacks", json=_payload()).status_code == 404
    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "true")


def test_demo_fast_mode_is_part_of_idempotent_request_and_uses_bounded_duration(demo_client, monkeypatch):
    client, _, _ = demo_client
    import matchpulse_sim.api.app as app_module

    captured = []
    monkeypatch.setattr(app_module, "play_events", lambda *_args, **kwargs: captured.append(kwargs))
    body = _payload(fast_demo=True)
    response = client.post("/api/demo/playbacks", json=body)
    assert response.status_code == 202
    _wait_for_status(client, body["request_id"], {"completed"})
    assert captured[0]["target_duration_seconds"] == 40.0
    assert client.post("/api/demo/playbacks", json={**body, "fast_demo": False}).status_code == 409


def test_demo_playback_is_idempotent_unique_and_rejects_conflicting_duplicate(demo_client, monkeypatch):
    client, _, _ = demo_client
    import matchpulse_sim.api.app as app_module

    calls = []

    def finish(events, **_kwargs):
        calls.append(events[0]["match_id"])

    monkeypatch.setattr(app_module, "play_events", finish)
    first = _payload()
    first_response = client.post("/api/demo/playbacks", json=first)
    assert first_response.status_code == 202
    original_match_id = first_response.json()["match_id"]
    _wait_for_status(client, first["request_id"], {"completed", "failed"})

    duplicate = client.post("/api/demo/playbacks", json=first)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["match_id"] == original_match_id
    assert len(calls) == 1

    conflict = client.post("/api/demo/playbacks", json={**first, "speed": 10})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "demo_request_conflict"

    second = _payload()
    second_response = client.post("/api/demo/playbacks", json=second)
    assert second_response.status_code == 202
    assert second_response.json()["match_id"] != original_match_id
    _wait_for_status(client, second["request_id"], {"completed", "failed"})


def test_demo_playback_rejects_concurrent_run_and_reports_safe_failure(demo_client, monkeypatch):
    client, _, _ = demo_client
    import matchpulse_sim.api.app as app_module

    entered = Event()
    release = Event()

    def hold_playback(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        raise RuntimeError("must not be exposed")

    monkeypatch.setattr(app_module, "play_events", hold_playback)
    first = _payload()
    started = client.post("/api/demo/playbacks", json=first)
    assert started.status_code == 202
    assert entered.wait(timeout=1)
    second = client.post("/api/demo/playbacks", json=_payload())
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "demo_playback_capacity"
    release.set()
    failed = _wait_for_status(client, first["request_id"], {"failed"})
    assert failed["error"] == "playback_failed"
    assert "must not be exposed" not in failed["error"]


def test_demo_playback_requires_loopback_and_caps_request_body(demo_client):
    client, _, _ = demo_client
    remote = TestClient(
        client.app,
        base_url="http://127.0.0.1:8001",
        client=("192.0.2.10", 51000),
    )
    rejected = remote.post("/api/demo/playbacks", json=_payload())
    assert rejected.status_code == 403
    unexpected_port = TestClient(
        client.app,
        base_url="http://127.0.0.1:8999",
        client=("127.0.0.1", 51000),
    )
    assert unexpected_port.post("/api/demo/playbacks", json=_payload()).status_code == 403
    missing_port = TestClient(
        client.app,
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 51000),
    )
    assert missing_port.post("/api/demo/playbacks", json=_payload()).status_code == 403
    oversized = client.post(
        "/api/demo/playbacks",
        content=b" " * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
