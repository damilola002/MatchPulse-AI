"""Integrity-protected continuation cursors for intelligence pages."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
from hashlib import sha256
from typing import Any

from ..serialization import canonical_json

MAX_CURSOR_CHARS = 2048
CURSOR_SCHEMA_VERSION = 1
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
CURSOR_FIELDS = {
    "cursor_schema_version",
    "match_id",
    "simulation_run_id",
    "metric_definition_version",
    "rule_versions",
    "as_of_sequence",
    "as_of_event_id",
    "limit",
    "after_position",
}


class InvalidCursor(ValueError):
    """A cursor is malformed, unsupported, or has an invalid signature."""


def _encode_b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_b64url(value: str) -> bytes:
    if not value or _B64URL.fullmatch(value) is None:
        raise InvalidCursor("cursor contains invalid base64url")
    try:
        padding = "=" * ((4 - len(value) % 4) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor("cursor contains invalid base64url") from exc
    if _encode_b64url(decoded) != value:
        raise InvalidCursor("cursor contains non-canonical base64url")
    return decoded


def encode_cursor(payload: dict[str, Any], key: bytes) -> str:
    if set(payload) != CURSOR_FIELDS:
        raise ValueError("cursor payload fields do not match the cursor contract")
    payload_segment = _encode_b64url(canonical_json(payload).encode("utf-8"))
    signature = hmac.new(key, payload_segment.encode("ascii"), sha256).digest()
    token = payload_segment + "." + _encode_b64url(signature)
    if len(token) > MAX_CURSOR_CHARS:
        raise ValueError("encoded cursor exceeds the supported length")
    return token


def decode_cursor(token: str, key: bytes) -> dict[str, Any]:
    if not isinstance(token, str) or len(token) > MAX_CURSOR_CHARS:
        raise InvalidCursor("cursor exceeds the supported length")
    parts = token.split(".")
    if len(parts) != 2:
        raise InvalidCursor("cursor format is invalid")
    payload_segment, signature_segment = parts
    payload_bytes = _decode_b64url(payload_segment)
    signature = _decode_b64url(signature_segment)
    expected = hmac.new(key, payload_segment.encode("ascii"), sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidCursor("cursor signature is invalid")
    try:
        payload_text = payload_bytes.decode("utf-8")
        payload = json.loads(payload_text)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidCursor("cursor payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != CURSOR_FIELDS:
        raise InvalidCursor("cursor payload fields are invalid")
    if canonical_json(payload).encode("utf-8") != payload_bytes:
        raise InvalidCursor("cursor payload is not canonical JSON")
    _validate_payload(payload)
    return payload


def _validate_payload(payload: dict[str, Any]) -> None:
    if type(payload["cursor_schema_version"]) is not int or payload["cursor_schema_version"] != CURSOR_SCHEMA_VERSION:
        raise InvalidCursor("cursor schema version is unsupported")
    for field in ("match_id", "simulation_run_id", "metric_definition_version"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise InvalidCursor("cursor identity fields are invalid")
    if type(payload["as_of_sequence"]) is not int or payload["as_of_sequence"] < 0:
        raise InvalidCursor("cursor watermark is invalid")
    event_id = payload["as_of_event_id"]
    if event_id is not None and not isinstance(event_id, str):
        raise InvalidCursor("cursor event identity is invalid")
    if (payload["as_of_sequence"] == 0) != (event_id is None):
        raise InvalidCursor("cursor watermark and event identity do not agree")
    if type(payload["limit"]) is not int or not 1 <= payload["limit"] <= 100:
        raise InvalidCursor("cursor page limit is invalid")
    versions = payload["rule_versions"]
    if not isinstance(versions, dict) or set(versions) != {"score_change", "shot_activity", "pressure_activity"}:
        raise InvalidCursor("cursor rule versions are invalid")
    if not all(isinstance(version, str) and version for version in versions.values()):
        raise InvalidCursor("cursor rule versions are invalid")
    position = payload["after_position"]
    if (
        not isinstance(position, list)
        or len(position) != 4
        or type(position[0]) is not int
        or position[0] < 1
        or not all(isinstance(value, str) for value in position[1:])
    ):
        raise InvalidCursor("cursor pagination position is invalid")


def configured_cursor_key(value: str | None) -> bytes:
    """Decode configured base64url key material without generating a fallback."""
    if not value or _B64URL.fullmatch(value) is None:
        raise ValueError("intelligence cursor key is missing or malformed")
    try:
        decoded = _decode_b64url(value)
    except InvalidCursor as exc:
        raise ValueError("intelligence cursor key is missing or malformed") from exc
    if len(decoded) < 32:
        raise ValueError("intelligence cursor key must contain at least 32 random bytes")
    return decoded
