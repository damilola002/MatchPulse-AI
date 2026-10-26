from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from matchpulse_sim.api.app import create_app
from matchpulse_sim.api.models import Base
from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures
from matchpulse_sim.narrative.errors import NarrativeError
from matchpulse_sim.narrative.service import NarrativeService


@pytest.fixture
def narrative_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATCHPULSE_INTELLIGENCE_CURSOR_KEY", base64.urlsafe_b64encode(b"narrative-api-cursor-key-material-32bytes").rstrip(b"=").decode())
    monkeypatch.delenv("MATCHPULSE_DEMO_MODE", raising=False)
    monkeypatch.delenv("MATCHPULSE_NARRATIVE_PROVIDER", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'narrative-api.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        events = generate_events(
            MatchConfig(seed=17, match_id="narrative-api-match", teams=default_fixtures(), scenario=Scenario.BALANCED)
        )
        assert client.post("/api/matches", json={"start_event": events[0]}).status_code == 201
        for offset in range(1, len(events), 100):
            assert client.post(f"/api/matches/{events[0]['match_id']}/events", json={"events": events[offset : offset + 100]}).status_code == 200
        yield client, events
    Base.metadata.drop_all(engine)
    engine.dispose()


def _request_for(client, match_id: str) -> dict:
    intelligence = client.get(f"/api/matches/{match_id}/intelligence").json()
    return {
        "simulation_run_id": intelligence["simulation_run_id"],
        "as_of": intelligence["as_of"],
        "insight_ids": [intelligence["insights"][0]["insight_id"]],
    }


def test_narrative_api_is_disabled_by_default(narrative_client, monkeypatch):
    client, events = narrative_client
    response = client.post(f"/api/matches/{events[0]['match_id']}/narratives", json=_request_for(client, events[0]["match_id"]))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "narrative_demo_disabled"


def test_narrative_api_uses_fake_provider_and_returns_exact_grounding(narrative_client, monkeypatch):
    client, events = narrative_client
    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "true")
    request = _request_for(client, events[0]["match_id"])
    response = client.post(f"/api/matches/{events[0]['match_id']}/narratives", json=request)
    assert response.status_code == 200
    result = response.json()
    assert result["provider"] == "deterministic-fake"
    assert result["synthetic"] is True
    assert result["as_of"] == request["as_of"]
    assert len(result["blocks"]) == len(request["insight_ids"])
    assert result["blocks"][0]["insight_ids"] == request["insight_ids"]
    assert all(event_id in {event["event_id"] for event in events} for event_id in result["blocks"][0]["evidence_event_ids"])
    assert client.get(f"/api/matches/{events[0]['match_id']}/narratives").status_code == 405


def test_narrative_api_rejects_stale_snapshot_run_mismatch_and_unknown_fields(narrative_client, monkeypatch):
    client, events = narrative_client
    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "true")
    match_id = events[0]["match_id"]
    request = _request_for(client, match_id)
    stale = {**request, "as_of": {**request["as_of"], "sequence": request["as_of"]["sequence"] - 1}}
    response = client.post(f"/api/matches/{match_id}/narratives", json=stale)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_snapshot"
    wrong_run = {**request, "simulation_run_id": "0" * 32}
    response = client.post(f"/api/matches/{match_id}/narratives", json=wrong_run)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "narrative_match_conflict"
    invalid = {**request, "claims": [{"unsupported": "client-supplied facts"}]}
    assert client.post(f"/api/matches/{match_id}/narratives", json=invalid).status_code == 422


def test_narrative_api_rejects_oversized_body_before_parsing(narrative_client):
    client, events = narrative_client
    response = client.post(
        f"/api/matches/{events[0]['match_id']}/narratives",
        content=b" " * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_narrative_api_returns_safe_provider_failure(narrative_client, monkeypatch):
    client, events = narrative_client
    monkeypatch.setenv("MATCHPULSE_DEMO_MODE", "true")

    class FailingProvider:
        provider_name = "test-failure"
        model_name = "test"

        async def generate(self, prompt):
            raise NarrativeError("provider_unavailable", "safe provider message with no secrets")

    client.app.state.narrative_services["fake"] = NarrativeService(FailingProvider())
    response = client.post(
        f"/api/matches/{events[0]['match_id']}/narratives",
        json=_request_for(client, events[0]["match_id"]),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert "fake-key" not in response.text
