from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import Request

from matchpulse_sim.api.app import MAX_LAST_EVENT_ID_LENGTH, MAX_SSE_CONNECTIONS, create_app
from matchpulse_sim.api.models import Base, MatchEventRecord
from matchpulse_sim.api.errors import ApiProblem
from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures
from matchpulse_sim.api.service import MAX_EVENT_PAGE_BYTES, ingest_events, replay_stored_events, start_match


@pytest.fixture
def api_client(tmp_path):
    database_path = tmp_path / "api-test.sqlite"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    app = create_app(engine)
    with TestClient(app) as client:
        yield client
    Base.metadata.drop_all(engine)
    engine.dispose()


def _stream():
    return generate_events(MatchConfig(seed=17, match_id="api-test-match", teams=default_fixtures(), scenario=Scenario.BALANCED))


def _start(client, events):
    response = client.post("/api/matches", json={"start_event": events[0]})
    assert response.status_code == 201
    return response.json()


def test_start_retry_batch_idempotency_mixed_suffix_and_version(api_client):
    events = _stream()
    first = _start(api_client, events)
    assert first["state"]["last_finalized_sequence"] == 0
    assert api_client.post("/api/matches", json={"start_event": events[0]}).status_code == 200
    batch = events[1:4]
    result = api_client.post(f"/api/matches/{events[0]['match_id']}/events", json={"events": batch}).json()
    assert result["accepted_count"] == 3
    before_version = result["state_version"]
    retry = api_client.post(f"/api/matches/{events[0]['match_id']}/events", json={"events": batch}).json()
    assert retry["duplicate_count"] == 3
    assert retry["accepted_count"] == 0
    assert retry["state_version"] == before_version
    mixed = api_client.post(f"/api/matches/{events[0]['match_id']}/events", json={"events": events[2:6]}).json()
    assert mixed["duplicate_count"] == 2
    assert mixed["accepted_count"] == 2
    assert mixed["state_version"] == before_version + 1


def test_conflicting_duplicate_gap_and_invalid_transition_leave_state_unchanged(api_client):
    events = _stream()
    _start(api_client, events)
    match_id = events[0]["match_id"]
    accepted = api_client.post(f"/api/matches/{match_id}/events", json={"events": events[1:4]}).json()
    version = accepted["state_version"]

    conflict = deepcopy(events[1])
    conflict["provenance"]["seed"] += 1
    response = api_client.post(f"/api/matches/{match_id}/events", json={"events": [conflict]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_conflict"

    gap = api_client.post(f"/api/matches/{match_id}/events", json={"events": [events[6]]})
    assert gap.status_code == 409
    assert gap.json()["error"]["code"] == "sequence_gap"

    next_event = deepcopy(events[4])
    invalid = deepcopy(events[5])
    invalid["team_id"] = "unknown-team"
    response = api_client.post(f"/api/matches/{match_id}/events", json={"events": [next_event, invalid]})
    assert response.status_code == 409
    after = api_client.get(f"/api/matches/{match_id}/state").json()
    assert after["last_accepted_sequence"] == 4
    assert after["state_version"] == version


def test_duplicate_after_new_is_rejected(api_client):
    events = _stream()
    _start(api_client, events)
    match_id = events[0]["match_id"]
    api_client.post(f"/api/matches/{match_id}/events", json={"events": events[1:3]}).raise_for_status()
    response = api_client.post(f"/api/matches/{match_id}/events", json={"events": [events[3], events[1]]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_after_new_event"
    assert api_client.get(f"/api/matches/{match_id}/state").json()["last_accepted_sequence"] == 3


def test_body_limit_mismatch_scope_and_sse_replay_reconnect(api_client):
    events = _stream()
    padded = json.dumps({"start_event": events[0]}, separators=(",", ":")).encode("utf-8")
    exact_limit_body = padded + b" " * (1024 * 1024 - len(padded))
    exact = api_client.post("/api/matches", content=exact_limit_body, headers={"Content-Type": "application/json"})
    assert exact.status_code == 201
    too_large = api_client.post("/api/matches", content=b" " * (1024 * 1024 + 1), headers={"Content-Type": "application/json"})
    assert too_large.status_code == 413
    match_id = events[0]["match_id"]
    assert api_client.post("/api/matches", json={"start_event": events[0]}).status_code == 200
    wrong_scope = deepcopy(events[1])
    wrong_scope["match_id"] = "other-match"
    response = api_client.post(f"/api/matches/{match_id}/events", json={"events": [wrong_scope]})
    assert response.status_code == 409
    for offset in range(1, len(events), 100):
        api_client.post(f"/api/matches/{match_id}/events", json={"events": events[offset:offset + 100]}).raise_for_status()

    full = api_client.get(f"/api/matches/{match_id}/stream")
    assert full.status_code == 200
    assert f"id: {events[-1]['event_id']}" in full.text
    cursor = events[4]["event_id"]
    resumed = api_client.get(f"/api/matches/{match_id}/stream", headers={"Last-Event-ID": cursor})
    assert resumed.status_code == 200
    resumed_event_ids = [
        line[4:] for line in resumed.text.splitlines() if line.startswith("id: ")
    ]
    assert cursor not in resumed_event_ids
    assert events[49]["event_id"] in resumed_event_ids
    assert resumed_event_ids == [event["event_id"] for event in events[5:]]
    assert "full_time" in resumed.text
    second_subscriber = api_client.get(f"/api/matches/{match_id}/stream")
    assert second_subscriber.text == full.text
    engine = api_client.app.state.engine
    with TestClient(create_app(engine)) as recovered_client:
        recovered = recovered_client.get(f"/api/matches/{match_id}/state")
        assert recovered.status_code == 200
        assert recovered.json()["last_accepted_sequence"] == len(events)


def test_sse_capacity_is_bounded(api_client):
    events = _stream()
    _start(api_client, events)
    api_client.app.state.active_sse = MAX_SSE_CONNECTIONS
    response = api_client.get(f"/api/matches/{events[0]['match_id']}/stream")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "stream_capacity"


def test_sse_disconnect_releases_connection_slot(api_client):
    events = _stream()
    _start(api_client, events)
    app = api_client.app
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/matches/{match_id}/stream")

    async def disconnect_receive():
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http", "method": "GET", "path": f"/api/matches/{events[0]['match_id']}/stream",
            "headers": [], "query_string": b"", "app": app,
        },
        receive=disconnect_receive,
    )
    response = asyncio.run(endpoint(events[0]["match_id"], request))
    assert app.state.active_sse == 1

    async def consume_disconnect():
        return [chunk async for chunk in response.body_iterator]

    assert asyncio.run(consume_disconnect()) == []
    assert app.state.active_sse == 0


def test_slow_sse_consumer_receives_bounded_page_then_can_close(api_client):
    events = _stream()
    match_id = events[0]["match_id"]
    _start(api_client, events)
    for offset in range(1, len(events), 100):
        api_client.post(f"/api/matches/{match_id}/events", json={"events": events[offset:offset + 100]}).raise_for_status()
    app = api_client.app
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/matches/{match_id}/stream")

    async def request_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {"type": "http", "method": "GET", "path": f"/api/matches/{match_id}/stream", "headers": [], "query_string": b"", "app": app},
        receive=request_receive,
    )

    async def read_one_then_disconnect():
        response = await endpoint(match_id, request)
        chunk = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return chunk

    chunk = asyncio.run(read_one_then_disconnect())
    assert chunk.count("data:") == 1
    assert app.state.active_sse == 0


def test_too_many_events_and_invalid_cursor_are_controlled(api_client):
    events = _stream()
    _start(api_client, events)
    response = api_client.post(f"/api/matches/{events[0]['match_id']}/events", json={"events": [events[1]] * 101})
    assert response.status_code == 413
    stream = api_client.get(f"/api/matches/{events[0]['match_id']}/stream", headers={"Last-Event-ID": "not-a-cursor"})
    assert stream.status_code == 400


def test_semantically_invalid_start_has_controlled_error(api_client):
    start = deepcopy(_stream()[0])
    start["data"]["away_team"]["team_id"] = start["data"]["home_team"]["team_id"]
    response = api_client.post("/api/matches", json={"start_event": start})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_match_start"


def test_unknown_match_and_database_errors_have_safe_http_responses(api_client, monkeypatch):
    missing = api_client.get("/api/matches/unknown-match/state")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "match_not_found"

    import matchpulse_sim.api.app as app_module

    secret_marker = "must-not-appear-in-response"
    monkeypatch.setattr(app_module, "get_state", lambda *_: (_ for _ in ()).throw(SQLAlchemyError(secret_marker)))
    failed = api_client.get("/api/matches/unknown-match/state")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "database_error"
    assert secret_marker not in failed.text


def test_event_pages_are_byte_bounded_and_cursor_advances_without_skips(api_client):
    events = _stream()
    _start(api_client, events)
    match_id = events[0]["match_id"]
    for offset in range(1, len(events), 100):
        api_client.post(f"/api/matches/{match_id}/events", json={"events": events[offset:offset + 100]}).raise_for_status()

    page = api_client.get(f"/api/matches/{match_id}/events?after_sequence=0&limit=5")
    assert page.status_code == 200
    assert len(page.content) <= MAX_EVENT_PAGE_BYTES
    assert [event["sequence"] for event in page.json()["events"]] == [1, 2, 3, 4, 5]
    assert page.json()["next_after_sequence"] == 5
    next_page = api_client.get(f"/api/matches/{match_id}/events?after_sequence=5&limit=5")
    assert next_page.status_code == 200
    assert next_page.json()["events"][0]["sequence"] == 6


def test_near_limit_event_page_fits_and_advances(api_client):
    events = _stream()
    events[0]["data"]["home_team"]["name"] = "A" * (MAX_EVENT_PAGE_BYTES - 4096)
    with Session(api_client.app.state.engine) as session, session.begin():
        start_match(session, events[0])
    response = api_client.get(f"/api/matches/{events[0]['match_id']}/events?limit=100")
    assert response.status_code == 200
    assert len(response.content) <= MAX_EVENT_PAGE_BYTES
    assert response.json()["events"][0]["sequence"] == 1
    assert response.json()["next_after_sequence"] >= 1


def test_single_oversized_stored_event_returns_explicit_blocking_cursor(api_client):
    events = _stream()
    events[0]["data"]["home_team"]["name"] = "A" * (MAX_EVENT_PAGE_BYTES + 4096)
    with Session(api_client.app.state.engine) as session, session.begin():
        start_match(session, events[0])
    response = api_client.get(f"/api/matches/{events[0]['match_id']}/events?after_sequence=0")
    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "event_exceeds_page_budget"
    assert body["details"]["sequence"] == 1
    assert body["details"]["after_sequence"] == 0


def test_sse_cursor_rejects_oversized_and_out_of_range_suffixes(api_client):
    events = _stream()
    _start(api_client, events)
    match_id = events[0]["match_id"]
    for cursor in ("a" * (MAX_LAST_EVENT_ID_LENGTH + 1), f"{'a' * 32}:9999999999999999999", f"{'a' * 32}:1x"):
        response = api_client.get(
            f"/api/matches/{match_id}/stream",
            headers={"Last-Event-ID": cursor},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_event_cursor"


def test_sse_stream_preserves_complete_event_sequence(api_client):
    events = _stream()
    _start(api_client, events)
    match_id = events[0]["match_id"]
    for offset in range(1, len(events), 100):
        api_client.post(f"/api/matches/{match_id}/events", json={"events": events[offset:offset + 100]}).raise_for_status()
    response = api_client.get(f"/api/matches/{match_id}/stream")
    event_ids = [line[4:] for line in response.text.splitlines() if line.startswith("id: ")]
    assert response.status_code == 200
    assert event_ids == [event["event_id"] for event in events]


def test_sse_history_to_live_transition_is_contiguous(api_client, monkeypatch):
    import matchpulse_sim.api.app as app_module

    events = _stream()
    match_id = events[0]["match_id"]
    _start(api_client, events)
    with Session(api_client.app.state.engine) as session, session.begin():
        ingest_events(session, match_id, events[1:4])
    app = api_client.app
    monkeypatch.setattr(app_module, "SSE_POLL_SECONDS", 0.001)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/matches/{match_id}/stream")

    async def request_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {"type": "http", "method": "GET", "path": f"/api/matches/{match_id}/stream", "headers": [], "query_string": b"", "app": app},
        receive=request_receive,
    )

    async def run_stream():
        response = await endpoint(match_id, request)
        event_ids = []

        async def consume():
            async for chunk in response.body_iterator:
                if chunk.startswith("id: "):
                    event_ids.append(chunk.split("\n", 1)[0][4:])

        consumer = asyncio.create_task(consume())
        async def wait_for_event(event_id):
            async def wait():
                while event_id not in event_ids:
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(wait(), timeout=3)

        # The connection starts with finalized history, then follows newly committed events.
        await wait_for_event(events[0]["event_id"])
        with Session(app.state.engine) as session, session.begin():
            ingest_events(session, match_id, events[4:16])
        await wait_for_event(events[14]["event_id"])
        # Sequence 16 is a goal-outcome shot; it remains unpublished until its goal arrives.
        assert events[15]["event_id"] not in event_ids
        with Session(app.state.engine) as session, session.begin():
            for offset in range(16, len(events), 100):
                ingest_events(session, match_id, events[offset:offset + 100])
        await asyncio.wait_for(consumer, timeout=5)
        return event_ids

    assert asyncio.run(run_stream()) == [event["event_id"] for event in events]
    assert app.state.active_sse == 0


def test_sse_heartbeat_is_emitted_and_connection_released(api_client, monkeypatch):
    import matchpulse_sim.api.app as app_module

    events = _stream()
    _start(api_client, events)
    app = api_client.app
    monkeypatch.setattr(app_module, "SSE_HEARTBEAT_SECONDS", 0.0)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/matches/{match_id}/stream")

    async def request_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {"type": "http", "method": "GET", "path": f"/api/matches/{events[0]['match_id']}/stream", "headers": [], "query_string": b"", "app": app},
        receive=request_receive,
    )

    async def consume_one():
        response = await endpoint(events[0]["match_id"], request)
        chunk = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return chunk

    assert asyncio.run(consume_one()) == ": heartbeat\n\n"
    assert app.state.active_sse == 0


def test_stored_log_column_mismatch_is_rejected(api_client):
    events = _stream()
    _start(api_client, events)
    with Session(api_client.app.state.engine) as session, session.begin():
        record = session.query(MatchEventRecord).filter_by(sequence=1).one()
        record.event_type = "wrong-type"
    with Session(api_client.app.state.engine) as session:
        with pytest.raises(ApiProblem, match="stored event columns do not match"):
            replay_stored_events(session, events[0]["match_id"])
