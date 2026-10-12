"""Canonical UTF-8 JSON and JSONL serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .validation import EventValidationError, validate_event

MAX_EVENT_INPUT_BYTES = 64 * 1024 * 1024
_SIZE_CHECK_CHARS = 64 * 1024


def _check_input_size(text: str) -> None:
    """Bound UTF-8 input size without allocating an encoded copy of the text."""
    if not isinstance(text, str):
        raise EventValidationError("event input must be text")
    limit = MAX_EVENT_INPUT_BYTES
    if len(text) > limit:
        raise EventValidationError(f"event input exceeds maximum input size of {limit} bytes (64 MiB)")
    byte_count = 0
    try:
        for offset in range(0, len(text), _SIZE_CHECK_CHARS):
            byte_count += len(text[offset : offset + _SIZE_CHECK_CHARS].encode("utf-8"))
            if byte_count > limit:
                raise EventValidationError(f"event input exceeds maximum input size of {limit} bytes (64 MiB)")
    except UnicodeEncodeError as exc:
        raise EventValidationError("event input must be valid UTF-8 text") from exc


def read_event_input_file(path: str | Path) -> str:
    """Read a local event file with a stat check and bounded read for TOCTOU safety."""
    input_path = Path(path)
    limit = MAX_EVENT_INPUT_BYTES
    if input_path.stat().st_size > limit:
        raise EventValidationError(f"event file exceeds maximum input size of {limit} bytes (64 MiB)")
    with input_path.open("rb") as source_file:
        raw = source_file.read(limit + 1)
    if len(raw) > limit:
        raise EventValidationError(f"event file exceeds maximum input size of {limit} bytes (64 MiB)")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EventValidationError("event file must be valid UTF-8") from exc
    _check_input_size(text)
    return text


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(events: Iterable[dict[str, Any]]) -> str:
    values = list(events)
    for event in values:
        validate_event(event)
    return canonical_json(values)


def write_jsonl(events: Iterable[dict[str, Any]]) -> str:
    values = list(events)
    for event in values:
        validate_event(event)
    return "".join(canonical_json(event) + "\n" for event in values)


def read_json(text: str) -> list[dict[str, Any]]:
    _check_input_size(text)
    try:
        values = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EventValidationError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(values, list):
        raise EventValidationError("JSON event export must be an array")
    for event in values:
        validate_event(event)
    return values


def read_jsonl(text: str) -> list[dict[str, Any]]:
    _check_input_size(text)
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise EventValidationError(f"JSONL line {line_number} is blank")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventValidationError(f"JSONL line {line_number}: {exc.msg}") from exc
        validate_event(event)
        events.append(event)
    if not events:
        raise EventValidationError("JSONL event stream must not be empty")
    return events
