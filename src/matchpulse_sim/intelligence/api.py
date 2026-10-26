"""Read-only API orchestration for finalized Phase 3 intelligence."""

from __future__ import annotations

import os
from hashlib import sha256
from typing import Any

from sqlalchemy import LargeBinary, Text, cast, func, select
from sqlalchemy.orm import Session

from ..api.errors import ApiProblem, MatchNotFound
from ..api.models import MatchEventRecord, MatchRecord
from ..replay import ReplayError
from ..serialization import canonical_json
from .cursors import InvalidCursor, configured_cursor_key, decode_cursor, encode_cursor
from .engine import (
    METRIC_DEFINITION_VERSION,
    RULE_VERSIONS,
    calculate_intelligence,
)

MAX_INTELLIGENCE_EVENTS = 10_000
MAX_INTELLIGENCE_INPUT_BYTES = 16 * 1024 * 1024
MAX_INTELLIGENCE_PAGE_BYTES = 1024 * 1024
MAX_INTELLIGENCE_PAGE_ITEMS = 100


def _cursor_failure(code: str, status: int, message: str) -> ApiProblem:
    return ApiProblem(status, code, message)


def _event_payload_size_expression(session: Session) -> Any:
    payload_text = cast(MatchEventRecord.payload, Text)
    if session.get_bind().dialect.name == "postgresql":
        return func.octet_length(payload_text)
    return func.length(cast(MatchEventRecord.payload, LargeBinary))


def _validate_row(row: MatchEventRecord, payload: Any, sequence: int, match: MatchRecord) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiProblem(500, "event_log_mismatch", "stored event payload is not a JSON object")
    clock = payload.get("clock")
    try:
        digest = sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ApiProblem(500, "event_log_mismatch", "stored event payload cannot be serialized safely") from exc
    if (
        row.sequence != sequence
        or row.match_id != match.match_id
        or row.simulation_run_id != match.simulation_run_id
        or payload.get("event_id") != row.event_id
        or payload.get("match_id") != row.match_id
        or payload.get("simulation_run_id") != row.simulation_run_id
        or payload.get("sequence") != row.sequence
        or payload.get("schema_version") != row.schema_version
        or payload.get("type") != row.event_type
        or not isinstance(clock, dict)
        or clock.get("match_elapsed_ms") != row.match_elapsed_ms
        or clock.get("period_elapsed_ms") != row.period_elapsed_ms
        or clock.get("period") != row.period
        or row.canonical_sha256 != digest
    ):
        raise ApiProblem(500, "event_log_mismatch", "stored event columns do not match the validated event payload")
    return payload


def read_finalized_prefix(
    session: Session, match: MatchRecord, sequence: int, event_id: str | None
) -> list[dict[str, Any]]:
    if sequence == 0:
        if event_id is not None:
            raise ApiProblem(500, "event_log_mismatch", "empty finalized watermark has an event ID")
        return []
    size_expression = _event_payload_size_expression(session)
    count, stored_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(size_expression), 0)).where(
            MatchEventRecord.match_id == match.match_id,
            MatchEventRecord.simulation_run_id == match.simulation_run_id,
            MatchEventRecord.sequence <= sequence,
        )
    ).one()
    if count != sequence:
        raise ApiProblem(500, "event_log_mismatch", "finalized event prefix is incomplete")
    if count > MAX_INTELLIGENCE_EVENTS or stored_bytes > MAX_INTELLIGENCE_INPUT_BYTES:
        raise ApiProblem(
            413,
            "intelligence_input_limit",
            "finalized event prefix exceeds the intelligence calculation limit",
            {"max_events": MAX_INTELLIGENCE_EVENTS, "max_bytes": MAX_INTELLIGENCE_INPUT_BYTES},
        )
    rows = list(
        session.scalars(
            select(MatchEventRecord)
            .where(
                MatchEventRecord.match_id == match.match_id,
                MatchEventRecord.simulation_run_id == match.simulation_run_id,
                MatchEventRecord.sequence <= sequence,
            )
            .order_by(MatchEventRecord.sequence)
        )
    )
    if len(rows) != sequence:
        raise ApiProblem(500, "event_log_mismatch", "finalized event prefix changed while being read")
    events: list[dict[str, Any]] = []
    canonical_bytes = 0
    for expected, row in enumerate(rows, start=1):
        payload = _validate_row(row, row.payload, expected, match)
        try:
            canonical_bytes += len(canonical_json(payload).encode("utf-8"))
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise ApiProblem(500, "event_log_mismatch", "stored event payload cannot be serialized safely") from exc
        if canonical_bytes > MAX_INTELLIGENCE_INPUT_BYTES:
            raise ApiProblem(
                413,
                "intelligence_input_limit",
                "finalized event prefix exceeds the intelligence calculation limit",
                {"max_events": MAX_INTELLIGENCE_EVENTS, "max_bytes": MAX_INTELLIGENCE_INPUT_BYTES},
            )
        events.append(payload)
    if rows[-1].event_id != event_id:
        raise ApiProblem(500, "event_log_mismatch", "finalized watermark does not match the stored event")
    return events


def _position(insight: dict[str, Any]) -> list[Any]:
    return [
        insight["trigger_sequence"],
        insight["rule_id"],
        insight["team_id"] or "",
        insight["insight_id"],
    ]


def _position_key(value: list[Any] | None) -> tuple[int, str, str, str] | None:
    if value is None:
        return None
    return (value[0], value[1], value[2], value[3])


def _make_cursor(
    *,
    key: bytes,
    match: MatchRecord,
    sequence: int,
    event_id: str | None,
    limit: int,
    last_insight: dict[str, Any],
) -> str:
    return encode_cursor(
        {
            "cursor_schema_version": 1,
            "match_id": match.match_id,
            "simulation_run_id": match.simulation_run_id,
            "metric_definition_version": METRIC_DEFINITION_VERSION,
            "rule_versions": RULE_VERSIONS,
            "as_of_sequence": sequence,
            "as_of_event_id": event_id,
            "limit": limit,
            "after_position": _position(last_insight),
        },
        key,
    )


def get_intelligence_page(
    session: Session,
    match_id: str,
    *,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    """Calculate one bounded, snapshot-pinned page inside the caller's read transaction."""
    match = session.get(MatchRecord, match_id)
    if match is None:
        raise MatchNotFound(match_id)
    try:
        key = configured_cursor_key(os.environ.get("MATCHPULSE_INTELLIGENCE_CURSOR_KEY"))
    except ValueError as exc:
        raise _cursor_failure(
            "intelligence_cursor_configuration",
            503,
            "intelligence pagination is not configured safely",
        ) from exc

    decoded: dict[str, Any] | None = None
    if cursor is not None:
        try:
            decoded = decode_cursor(cursor, key)
        except InvalidCursor as exc:
            raise _cursor_failure("invalid_intelligence_cursor", 400, "intelligence cursor is invalid") from exc
        if limit is not None and limit != decoded["limit"]:
            raise _cursor_failure("invalid_intelligence_cursor", 400, "intelligence cursor page size cannot be changed")
        limit = decoded["limit"]
        if (
            decoded["match_id"] != match.match_id
            or decoded["simulation_run_id"] != match.simulation_run_id
            or decoded["metric_definition_version"] != METRIC_DEFINITION_VERSION
            or decoded["rule_versions"] != RULE_VERSIONS
        ):
            raise _cursor_failure("intelligence_cursor_conflict", 409, "intelligence cursor does not match this snapshot contract")
        sequence = decoded["as_of_sequence"]
        event_id = decoded["as_of_event_id"]
        after_position = decoded["after_position"]
        if sequence > match.finalized_sequence:
            raise _cursor_failure("intelligence_cursor_conflict", 409, "intelligence cursor watermark is not finalized")
    else:
        limit = 100 if limit is None else limit
        sequence = match.finalized_sequence
        event_id = match.finalized_event_id
        after_position = None

    if not 1 <= limit <= MAX_INTELLIGENCE_PAGE_ITEMS:
        raise ApiProblem(422, "invalid_page_limit", "intelligence page limit must be between 1 and 100")
    if sequence == 0:
        if event_id is not None:
            raise ApiProblem(500, "event_log_mismatch", "empty finalized watermark has an event ID")
    else:
        marker = session.scalar(
            select(MatchEventRecord.event_id).where(
                MatchEventRecord.match_id == match.match_id,
                MatchEventRecord.simulation_run_id == match.simulation_run_id,
                MatchEventRecord.sequence == sequence,
            )
        )
        if marker != event_id:
            if decoded is not None:
                raise _cursor_failure("intelligence_cursor_conflict", 409, "intelligence cursor watermark is invalid")
            raise ApiProblem(500, "event_log_mismatch", "finalized watermark does not match the stored event")

    events = read_finalized_prefix(session, match, sequence, event_id)
    try:
        snapshot, insights = calculate_intelligence(
            events,
            match_id=match.match_id,
            simulation_run_id=match.simulation_run_id,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            as_of_sequence=sequence,
            as_of_event_id=event_id,
        )
    except ReplayError as exc:
        raise ApiProblem(500, "event_log_mismatch", "stored finalized events failed replay verification") from exc

    if decoded is not None:
        position = _position_key(after_position)
        known_positions = {tuple(_position(item)) for item in insights}
        if position is None or position not in known_positions:
            raise _cursor_failure("intelligence_cursor_conflict", 409, "intelligence cursor position is invalid")
    else:
        position = None
    page_candidates = [
        item for item in insights
        if position is None or tuple(_position(item)) > position
    ]
    if decoded is not None and not page_candidates:
        raise _cursor_failure("intelligence_cursor_conflict", 409, "intelligence cursor has no remaining page")
    wrapper = {
        "match_id": match.match_id,
        "simulation_run_id": match.simulation_run_id,
        "synthetic": True,
        "as_of": snapshot["as_of"],
        "metric_snapshot": snapshot,
        "insights": [],
        "next_cursor": None,
    }
    page: list[dict[str, Any]] = []
    for insight in page_candidates[:limit]:
        candidate_page = [*page, insight]
        more = len(candidate_page) < len(page_candidates)
        next_cursor = (
            _make_cursor(
                key=key,
                match=match,
                sequence=sequence,
                event_id=event_id,
                limit=limit,
                last_insight=candidate_page[-1],
            )
            if more
            else None
        )
        candidate = {**wrapper, "insights": candidate_page, "next_cursor": next_cursor}
        if len(canonical_json(candidate).encode("utf-8")) > MAX_INTELLIGENCE_PAGE_BYTES:
            if not page:
                raise ApiProblem(
                    413,
                    "insight_exceeds_page_budget",
                    "the next insight exceeds the intelligence response byte budget",
                    {"max_response_bytes": MAX_INTELLIGENCE_PAGE_BYTES},
                )
            break
        page.append(insight)
    more = len(page) < len(page_candidates)
    next_cursor = (
        _make_cursor(
            key=key,
            match=match,
            sequence=sequence,
            event_id=event_id,
            limit=limit,
            last_insight=page[-1],
        )
        if more and page
        else None
    )
    response = {**wrapper, "insights": page, "next_cursor": next_cursor}
    if len(canonical_json(response).encode("utf-8")) > MAX_INTELLIGENCE_PAGE_BYTES:
        raise ApiProblem(413, "intelligence_response_too_large", "intelligence response exceeds the 1 MiB page budget")
    return response
