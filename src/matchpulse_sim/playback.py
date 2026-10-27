"""Deterministic local event-stream feeder for the Phase 2 API."""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PlaybackError(RuntimeError):
    pass


MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_BATCH_EVENTS = 100
FAST_DEMO_MAX_BATCH_EVENTS = 10
FAST_DEMO_MAX_BATCH_SECONDS = 0.75


def _request_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _request_json(method: str, url: str, payload: dict[str, Any] | None, *, retries: int = 3) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode() if payload is not None else None
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=10) as response:
                value = json.loads(response.read())
                if not isinstance(value, dict):
                    raise PlaybackError("server returned a non-object response")
                return value
        except HTTPError as exc:
            if exc.code < 500 or attempt + 1 == retries:
                message = "request rejected by server"
                try:
                    message = json.loads(exc.read()).get("error", {}).get("message", message)
                except (ValueError, AttributeError):
                    pass
                raise PlaybackError(f"HTTP {exc.code}: {message}") from exc
            last_error = exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
        time.sleep(0.2 * (attempt + 1))
    raise PlaybackError(f"submission outcome is uncertain after retries: {last_error}")


def play_events(
    events: list[dict[str, Any]], *, base_url: str = "http://127.0.0.1:8001",
    speed: float = 1.0, resume: bool = False,
    target_duration_seconds: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Start and feed a complete validated stream; retries preserve event IDs."""
    if not math.isfinite(speed) or speed <= 0:
        raise PlaybackError("playback speed must be positive")
    if target_duration_seconds is not None and (
        not math.isfinite(target_duration_seconds)
        or not 30 <= target_duration_seconds <= 60
    ):
        raise PlaybackError("fast-demo duration must be between 30 and 60 seconds")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed_url.path not in {"", "/"}:
        raise PlaybackError("playback API URL must use HTTP on loopback")
    if not events or events[0].get("type") != "match_start":
        raise PlaybackError("input must be a complete Phase 1 event stream")
    start = events[0]
    match_id = start["match_id"]
    run_id = start["simulation_run_id"]
    state_url = f"{base_url.rstrip('/')}/api/matches/{match_id}/state"
    start_url = f"{base_url.rstrip('/')}/api/matches"
    first_unaccepted = 1
    if resume:
        state = _request_json("GET", state_url, None)
        if state.get("simulation_run_id") != run_id or state.get("match_id") != match_id:
            raise PlaybackError("server match/run identity does not match input stream")
        first_unaccepted = state.get("last_accepted_sequence", 0)
        if not isinstance(first_unaccepted, int) or not 1 <= first_unaccepted <= len(events):
            raise PlaybackError("server accepted sequence is outside the input stream")
        expected_id = events[first_unaccepted - 1]["event_id"]
        if state.get("last_accepted_event_id") != expected_id:
            raise PlaybackError("server last accepted event does not match deterministic input")
    else:
        start_payload = {"start_event": start}
        if _request_size(start_payload) > MAX_REQUEST_BODY_BYTES:
            raise PlaybackError("start event exceeds the API 1 MiB request limit")
        _request_json("POST", start_url, start_payload)

    previous_clock = events[first_unaccepted - 1]["clock"]["match_elapsed_ms"]
    total_clock = events[-1]["clock"]["match_elapsed_ms"]
    if target_duration_seconds is not None and total_clock <= 0:
        raise PlaybackError("fast-demo input must span a positive match clock")
    fast_batch = target_duration_seconds is not None
    batch_limit = FAST_DEMO_MAX_BATCH_EVENTS if fast_batch else MAX_BATCH_EVENTS
    batch_window = FAST_DEMO_MAX_BATCH_SECONDS if fast_batch else None
    batch: list[dict[str, Any]] = []
    batches: list[list[dict[str, Any]]] = []
    batch_start_offset = 0.0
    for event in events[first_unaccepted:]:
        candidate = [*batch, event]
        candidate_payload = {"events": candidate}
        event_offset = (
            event["clock"]["match_elapsed_ms"] / total_clock * target_duration_seconds
            if fast_batch else 0.0
        )
        window_elapsed = event_offset - batch_start_offset if batch else 0.0
        if batch and (
            len(candidate) > batch_limit
            or (batch_window is not None and window_elapsed > batch_window)
            or _request_size(candidate_payload) > MAX_REQUEST_BODY_BYTES
        ):
            batches.append(batch)
            batch = [event]
            batch_start_offset = event_offset
        else:
            if not batch:
                batch_start_offset = event_offset
            batch = candidate
        if _request_size({"events": batch}) > MAX_REQUEST_BODY_BYTES:
            raise PlaybackError("an event exceeds the API 1 MiB request limit")
    if batch:
        batches.append(batch)

    previous_offset = previous_clock / total_clock * target_duration_seconds if fast_batch else 0.0
    for batch in batches:
        batch_clock = batch[-1]["clock"]["match_elapsed_ms"]
        if fast_batch:
            target_offset = batch_clock / total_clock * target_duration_seconds
            delay = max(0.0, target_offset - previous_offset)
            if delay:
                sleep(delay)
            previous_offset = target_offset
        else:
            for event in batch:
                now_clock = event["clock"]["match_elapsed_ms"]
                delta = max(0, now_clock - previous_clock)
                if delta:
                    sleep(delta / 1000 / speed)
                previous_clock = now_clock
        _request_json("POST", f"{base_url.rstrip('/')}/api/matches/{match_id}/events", {"events": batch})
    return _request_json("GET", state_url, None)
