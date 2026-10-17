from __future__ import annotations

from urllib.error import URLError

from matchpulse_sim.generator import generate_events
from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures
from matchpulse_sim.playback import PlaybackError, _request_json, play_events


def test_resume_checks_deterministic_server_position(monkeypatch):
    events = generate_events(MatchConfig(seed=5, match_id="playback-test", teams=default_fixtures(), scenario=Scenario.BALANCED))
    seq = 3
    calls = []
    state_reads = 0
    def fake_request(method, url, payload, *, retries=3):
        nonlocal state_reads
        calls.append((method, url, payload))
        if method == "GET" and url.endswith("/state"):
            state_reads += 1
            if state_reads == 1:
                return {"match_id": events[0]["match_id"], "simulation_run_id": events[0]["simulation_run_id"], "last_accepted_sequence": seq, "last_accepted_event_id": events[seq - 1]["event_id"]}
            return {"complete": True}
        return {"ok": True}
    monkeypatch.setattr("matchpulse_sim.playback._request_json", fake_request)
    result = play_events(events, resume=True, speed=100000, sleep=lambda _: None)
    assert result == {"complete": True}
    assert calls[1][2]["events"][0]["sequence"] == seq + 1


def test_resume_rejects_mismatched_event_identity(monkeypatch):
    events = generate_events(MatchConfig(seed=5, match_id="playback-test", teams=default_fixtures(), scenario=Scenario.BALANCED))
    monkeypatch.setattr("matchpulse_sim.playback._request_json", lambda *a, **k: {"match_id": events[0]["match_id"], "simulation_run_id": events[0]["simulation_run_id"], "last_accepted_sequence": 1, "last_accepted_event_id": "wrong"})
    try:
        play_events(events, resume=True)
    except PlaybackError as exc:
        assert "event" in str(exc)
    else:
        raise AssertionError("identity mismatch was accepted")


def test_request_retries_uncertain_network_failure(monkeypatch):
    import matchpulse_sim.playback as playback

    attempts = []
    sleeps = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        attempts.append((request, timeout))
        if len(attempts) == 1:
            raise URLError("temporary local connection failure")
        return Response()

    monkeypatch.setattr(playback, "urlopen", fake_urlopen)
    monkeypatch.setattr(playback.time, "sleep", sleeps.append)
    assert _request_json("POST", "http://127.0.0.1/test", {"ok": True}) == {"ok": True}
    assert len(attempts) == 2
    assert sleeps == [0.2]


def test_playback_paces_and_partitions_batches(monkeypatch):
    import matchpulse_sim.playback as playback

    events = generate_events(MatchConfig(seed=13, match_id="playback-batches", teams=default_fixtures(), scenario=Scenario.BALANCED))
    calls = []
    sleeps = []

    def fake_request(method, url, payload, **_kwargs):
        calls.append((method, payload))
        if method == "GET":
            return {"complete": True}
        return {"ok": True}

    monkeypatch.setattr(playback, "_request_json", fake_request)
    monkeypatch.setattr(playback, "MAX_BATCH_EVENTS", 2)
    assert play_events(events, speed=2.0, sleep=sleeps.append) == {"complete": True}
    batches = [payload["events"] for method, payload in calls if method == "POST" and "events" in payload]
    assert all(len(batch) <= 2 for batch in batches)
    assert [event["event_id"] for batch in batches for event in batch] == [event["event_id"] for event in events[1:]]
    expected = []
    previous = events[0]["clock"]["match_elapsed_ms"]
    for event in events[1:]:
        clock = event["clock"]["match_elapsed_ms"]
        delta = max(0, clock - previous)
        if delta:
            expected.append(delta / 1000 / 2.0)
        previous = clock
    assert sleeps == expected


def test_cli_playback_cancellation_returns_130(monkeypatch, capsys):
    import matchpulse_sim.cli as cli

    def cancel(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "play_events", cancel)
    assert cli.main(["play", "--seed", "17", "--speed", "10"]) == 130
    assert "playback cancelled" in capsys.readouterr().err
