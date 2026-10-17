from __future__ import annotations

from hashlib import sha256
from typing import Any

from sqlalchemy import LargeBinary, Text, cast, func, select
from sqlalchemy.orm import Session

from ..replay import MatchState, ReplayError, ReplayProgress, replay_prefix
from ..serialization import canonical_json
from ..validation import EventValidationError, validate_event
from .errors import ApiProblem, MatchNotFound
from .models import MatchEventRecord, MatchRecord

MAX_BATCH_EVENTS = 100
MAX_EVENT_PAGE_BYTES = 1024 * 1024
MAX_STORED_EVENT_PROBE_BYTES = 4 * MAX_EVENT_PAGE_BYTES


def payload_digest(event: dict[str, Any]) -> str:
    return sha256(canonical_json(event).encode("utf-8")).hexdigest()


def _schema_validate(event: dict[str, Any]) -> None:
    try:
        validate_event(event)
    except EventValidationError as exc:
        raise ApiProblem(422, "invalid_event", str(exc)) from exc


def _event_row(event: dict[str, Any]) -> MatchEventRecord:
    clock = event["clock"]
    return MatchEventRecord(
        event_id=event["event_id"],
        match_id=event["match_id"],
        simulation_run_id=event["simulation_run_id"],
        sequence=event["sequence"],
        schema_version=event["schema_version"],
        event_type=event["type"],
        match_elapsed_ms=clock["match_elapsed_ms"],
        period_elapsed_ms=clock["period_elapsed_ms"],
        period=clock["period"],
        canonical_sha256=payload_digest(event),
        payload=event,
    )


def _write_projection(match: MatchRecord, progress: ReplayProgress) -> None:
    state = progress.state
    match.status = state.status
    match.period = state.period
    match.match_elapsed_ms = state.last_match_elapsed_ms
    match.period_elapsed_ms = progress.finalized_period_elapsed_ms
    match.home_score = state.home_score
    match.away_score = state.away_score
    match.current_possession = state.current_possession
    match.home_shots = state.home_shots
    match.away_shots = state.away_shots
    match.finalized_sequence = progress.finalized_sequence
    match.finalized_event_id = (
        f"{match.simulation_run_id}:{progress.finalized_sequence}"
        if progress.finalized_sequence
        else None
    )
    match.pending_checkpoint = progress.pending_transition


def _state_dict(match: MatchRecord) -> dict[str, Any]:
    return {
        "match_id": match.match_id,
        "simulation_run_id": match.simulation_run_id,
        "scenario_id": match.scenario_id,
        "synthetic": True,
        "status": match.status,
        "period": match.period,
        "clock": {
            "match_elapsed_ms": match.match_elapsed_ms,
            "period_elapsed_ms": match.period_elapsed_ms,
        },
        "score": {"home": match.home_score, "away": match.away_score},
        "current_possession_team_id": match.current_possession,
        "shots": {"home": match.home_shots, "away": match.away_shots},
        "last_accepted_sequence": match.accepted_sequence,
        "last_accepted_event_id": match.accepted_event_id,
        "last_accepted_match_elapsed_ms": match.accepted_match_elapsed_ms,
        "last_finalized_sequence": match.finalized_sequence,
        "last_finalized_event_id": match.finalized_event_id,
        "state_version": match.state_version,
        "transition_pending": match.accepted_sequence > match.finalized_sequence,
    }


def start_match(session: Session, event: dict[str, Any]) -> tuple[MatchRecord, bool]:
    _schema_validate(event)
    if event["type"] != "match_start" or event["sequence"] != 1:
        raise ApiProblem(422, "invalid_match_start", "start_event must be match_start at sequence 1")
    match_id = event["match_id"]
    run_id = event["simulation_run_id"]
    existing = session.scalar(select(MatchRecord).where(MatchRecord.match_id == match_id).with_for_update())
    if existing is not None:
        row = session.scalar(select(MatchEventRecord).where(MatchEventRecord.event_id == event["event_id"]))
        if (
            existing.simulation_run_id == run_id
            and row is not None
            and row.canonical_sha256 == payload_digest(event)
        ):
            return existing, True
        raise ApiProblem(409, "match_identity_conflict", "match_id is already associated with another start event")

    try:
        progress = replay_prefix([event])
    except ReplayError as exc:
        raise ApiProblem(422, "invalid_match_start", str(exc)) from exc
    data = event["data"]
    state = progress.state
    match = MatchRecord(
        match_id=match_id,
        simulation_run_id=run_id,
        scenario_id=event["provenance"]["scenario_id"],
        seed=event["provenance"]["seed"],
        generator_version=event["provenance"]["generator_version"],
        schema_version=event["schema_version"],
        home_team_id=data["home_team"]["team_id"],
        away_team_id=data["away_team"]["team_id"],
        status=state.status,
        period=state.period,
        match_elapsed_ms=state.last_match_elapsed_ms,
        period_elapsed_ms=0,
        home_score=state.home_score,
        away_score=state.away_score,
        current_possession=state.current_possession,
        home_shots=state.home_shots,
        away_shots=state.away_shots,
        accepted_sequence=1,
        accepted_event_id=event["event_id"],
        accepted_match_elapsed_ms=event["clock"]["match_elapsed_ms"],
        finalized_sequence=progress.finalized_sequence,
        finalized_event_id=None,
        state_version=1,
        pending_checkpoint=progress.pending_transition,
    )
    session.add(match)
    session.flush()
    session.add(_event_row(event))
    session.flush()
    return match, False


def ingest_events(
    session: Session,
    match_id: str,
    events: list[dict[str, Any]],
) -> tuple[MatchRecord, int, int]:
    if not events:
        raise ApiProblem(422, "empty_batch", "events must contain at least one event")
    if len(events) > MAX_BATCH_EVENTS:
        raise ApiProblem(413, "batch_too_large", "a batch may contain at most 100 events")
    for event in events:
        _schema_validate(event)
        if event["match_id"] != match_id:
            raise ApiProblem(409, "match_identity_conflict", "event match_id does not match the request path")

    match = session.scalar(select(MatchRecord).where(MatchRecord.match_id == match_id).with_for_update())
    if match is None:
        raise MatchNotFound(match_id)

    accepted_at_start = match.accepted_sequence
    previous_in_request: int | None = None
    new_events: list[dict[str, Any]] = []
    duplicate_count = 0
    saw_new = False
    seen_request_ids: set[str] = set()
    for event in events:
        sequence = event["sequence"]
        if saw_new and sequence <= accepted_at_start:
            raise ApiProblem(409, "duplicate_after_new_event", "duplicate events must precede new events in a batch")
        if previous_in_request is not None and sequence != previous_in_request + 1:
            raise ApiProblem(409, "batch_order_conflict", "batch event sequences must be contiguous and ordered")
        previous_in_request = sequence
        if event["simulation_run_id"] != match.simulation_run_id:
            raise ApiProblem(409, "match_identity_conflict", "match_id is already associated with another simulation run")
        if event["event_id"] in seen_request_ids:
            raise ApiProblem(409, "duplicate_batch_event", "an event may appear only once in a batch")
        seen_request_ids.add(event["event_id"])

        if sequence <= accepted_at_start:
            row = session.scalar(
                select(MatchEventRecord).where(
                    MatchEventRecord.match_id == match_id,
                    MatchEventRecord.sequence == sequence,
                )
            )
            if row is None or row.event_id != event["event_id"] or row.canonical_sha256 != payload_digest(event):
                raise ApiProblem(409, "event_conflict", "event identity conflicts with the accepted event log")
            duplicate_count += 1
            continue
        expected = accepted_at_start + len(new_events) + 1
        if sequence != expected:
            raise ApiProblem(
                409,
                "sequence_gap",
                f"expected sequence {expected}",
                {"expected_sequence": expected},
            )
        saw_new = True
        new_events.append(event)

    if not new_events:
        return match, 0, duplicate_count

    stored_events = list(
        session.scalars(
            select(MatchEventRecord.payload)
            .where(MatchEventRecord.match_id == match_id)
            .order_by(MatchEventRecord.sequence)
        )
    )
    try:
        progress = replay_prefix([*stored_events, *new_events])
    except ReplayError as exc:
        raise ApiProblem(409, "invalid_transition", str(exc)) from exc

    for event in new_events:
        session.add(_event_row(event))
    match.accepted_sequence = progress.accepted_sequence
    match.accepted_event_id = progress.accepted_event_id
    match.accepted_match_elapsed_ms = progress.accepted_match_elapsed_ms
    match.state_version += 1
    _write_projection(match, progress)
    session.flush()
    return match, len(new_events), duplicate_count


def get_match(session: Session, match_id: str) -> MatchRecord:
    match = session.get(MatchRecord, match_id)
    if match is None:
        raise MatchNotFound(match_id)
    return match


def get_state(session: Session, match_id: str) -> dict[str, Any]:
    return _state_dict(get_match(session, match_id))


def get_event_page(session: Session, match_id: str, after_sequence: int, limit: int) -> dict[str, Any]:
    if not 1 <= limit <= MAX_BATCH_EVENTS:
        raise ApiProblem(422, "invalid_page_limit", "event page limit must be between 1 and 100")
    match = get_match(session, match_id)
    payload_text = cast(MatchEventRecord.payload, Text)
    if session.get_bind().dialect.name == "postgresql":
        payload_size = func.octet_length(payload_text)
    else:
        payload_size = func.length(cast(MatchEventRecord.payload, LargeBinary))
    events: list[dict[str, Any]] = []
    cursor = after_sequence
    response: dict[str, Any] = {
        "match_id": match_id,
        "simulation_run_id": match.simulation_run_id,
        "events": events,
        "last_accepted_sequence": match.accepted_sequence,
        "last_finalized_sequence": match.finalized_sequence,
    }
    for _ in range(limit):
        candidate_row = session.execute(
            select(MatchEventRecord.sequence, payload_size)
            .where(MatchEventRecord.match_id == match_id, MatchEventRecord.sequence > cursor)
            .order_by(MatchEventRecord.sequence)
            .limit(1)
        ).first()
        if candidate_row is None:
            break
        sequence, stored_bytes = candidate_row
        if stored_bytes > MAX_STORED_EVENT_PROBE_BYTES:
            raise ApiProblem(
                413,
                "event_exceeds_page_budget",
                "stored event is too large to retrieve safely in an event page",
                {"sequence": sequence, "after_sequence": cursor, "max_response_bytes": MAX_EVENT_PAGE_BYTES},
            )
        event = session.scalar(
            select(MatchEventRecord.payload).where(
                MatchEventRecord.match_id == match_id,
                MatchEventRecord.sequence == sequence,
            )
        )
        if not isinstance(event, dict):
            raise ApiProblem(500, "event_log_mismatch", "stored event payload is not a JSON object")
        candidate = {**response, "events": [*events, event], "next_after_sequence": sequence}
        if len(canonical_json(candidate).encode("utf-8")) > MAX_EVENT_PAGE_BYTES:
            if not events:
                raise ApiProblem(
                    413,
                    "event_exceeds_page_budget",
                    "the next event exceeds the event-page byte budget; cursor was not advanced",
                    {"sequence": sequence, "after_sequence": cursor, "max_response_bytes": MAX_EVENT_PAGE_BYTES},
                )
            break
        events.append(event)
        cursor = sequence
    response["next_after_sequence"] = cursor
    return response


def replay_stored_events(session: Session, match_id: str) -> MatchState:
    match = get_match(session, match_id)
    records = list(
        session.scalars(
            select(MatchEventRecord)
            .where(MatchEventRecord.match_id == match_id)
            .order_by(MatchEventRecord.sequence)
        )
    )
    events: list[dict[str, Any]] = []
    for record in records:
        payload = record.payload
        if not isinstance(payload, dict):
            raise ApiProblem(500, "event_log_mismatch", "stored event payload is not a JSON object")
        clock = payload.get("clock")
        if (
            payload.get("event_id") != record.event_id
            or payload.get("match_id") != record.match_id
            or payload.get("simulation_run_id") != record.simulation_run_id
            or payload.get("sequence") != record.sequence
            or payload.get("type") != record.event_type
            or payload.get("schema_version") != record.schema_version
            or not isinstance(clock, dict)
            or clock.get("match_elapsed_ms") != record.match_elapsed_ms
            or clock.get("period_elapsed_ms") != record.period_elapsed_ms
            or clock.get("period") != record.period
            or record.canonical_sha256 != payload_digest(payload)
        ):
            raise ApiProblem(500, "event_log_mismatch", "stored event columns do not match the validated event payload")
        events.append(payload)
    progress = replay_prefix(events)
    if (
        progress.state.match_id != match.match_id
        or progress.state.simulation_run_id != match.simulation_run_id
        or progress.accepted_sequence != match.accepted_sequence
        or progress.finalized_sequence != match.finalized_sequence
        or match.finalized_event_id != (
            f"{match.simulation_run_id}:{progress.finalized_sequence}"
            if progress.finalized_sequence
            else None
        )
        or progress.finalized_period_elapsed_ms != match.period_elapsed_ms
        or progress.accepted_event_id != match.accepted_event_id
        or progress.accepted_match_elapsed_ms != match.accepted_match_elapsed_ms
        or progress.state.status != match.status
        or progress.state.period != match.period
        or progress.state.last_match_elapsed_ms != match.match_elapsed_ms
        or progress.state.home_score != match.home_score
        or progress.state.away_score != match.away_score
        or progress.state.current_possession != match.current_possession
        or progress.state.home_shots != match.home_shots
        or progress.state.away_shots != match.away_shots
        or progress.pending_transition != match.pending_checkpoint
    ):
        raise ApiProblem(500, "projection_mismatch", "stored match projection failed replay verification")
    return progress.state
