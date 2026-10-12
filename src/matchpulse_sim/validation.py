"""JSON Schema and stream-shape validation."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json
from typing import Any, Iterable

from jsonschema import Draft202012Validator

SCHEMA_VERSION = 1


class EventValidationError(ValueError):
    """Raised for unsupported, malformed, or internally inconsistent events."""


@lru_cache(maxsize=1)
def event_schema() -> dict[str, Any]:
    resource = files("matchpulse_sim").joinpath("schemas/match-event.v1.schema.json")
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(event_schema())


def validate_event(event: dict[str, Any], schema_version: int = SCHEMA_VERSION) -> None:
    if schema_version != SCHEMA_VERSION:
        raise EventValidationError(f"unsupported schema version: {schema_version}")
    if not isinstance(event, dict):
        raise EventValidationError("event must be a JSON object")
    actual_version = event.get("schema_version")
    if actual_version != SCHEMA_VERSION:
        raise EventValidationError(f"unsupported schema version: {actual_version!r}")
    errors = sorted(_validator().iter_errors(event), key=lambda err: (list(map(str, err.absolute_path)), err.message))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise EventValidationError(f"{path}: {error.message}")
    expected_id = f"{event['simulation_run_id']}:{event['sequence']}"
    if event["event_id"] != expected_id:
        raise EventValidationError("event_id must be derived from simulation_run_id and sequence")
    if event["type"] == "possession_change":
        data = event["data"]
        if data["from_team_id"] == data["to_team_id"]:
            raise EventValidationError("possession change must change the controlling team")
        if event["team_id"] != data["to_team_id"]:
            raise EventValidationError("team_id must equal possession_change.to_team_id")
    if event["type"] == "pass" and event["outcome"] == "completed" and event["data"]["receiver_player_id"] is None:
        raise EventValidationError("completed passes require receiver_player_id")


def validate_event_stream(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(events)
    if not result:
        raise EventValidationError("event stream must not be empty")
    for event in result:
        validate_event(event)
    return result
