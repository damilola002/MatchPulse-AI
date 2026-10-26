"""Prepare approved claims from a current, finalized Phase 3 snapshot."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Sequence

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..api.errors import MatchNotFound
from ..api.models import MatchRecord
from ..api.schemas import IntelligenceInsightV1
from ..intelligence.api import read_finalized_prefix
from ..intelligence.engine import calculate_intelligence
from ..serialization import canonical_json
from .contracts import ApprovedClaimV1, NarrativeAsOf, NarrativeRequestV1
from .errors import NarrativeError
from .settings import NarrativeLimits

MAX_SELECTED_INSIGHTS = 10
MAX_APPROVED_CLAIMS = 20


def _claim_id(claim: dict[str, Any]) -> str:
    return "claim:v1:" + sha256(canonical_json(claim).encode("utf-8")).hexdigest()


def claim_identity(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_schema_version": 1,
        "match_id": claim["match_id"],
        "simulation_run_id": claim["simulation_run_id"],
        "as_of": claim["as_of"],
        "insight_id": claim["insight_id"],
        "rule_id": claim["rule_id"],
        "rule_version": claim["rule_version"],
        "trigger_event_id": claim["trigger_event_id"],
        "trigger_sequence": claim["trigger_sequence"],
        "team_id": claim["team_id"],
        "observed_facts": claim["observed_facts"],
        "window": claim["window"],
        "evidence_event_ids": claim["evidence_event_ids"],
    }


def prepare_narrative_request(
    session: Session,
    *,
    match_id: str,
    expected_as_of: NarrativeAsOf | dict[str, Any],
    insight_ids: Sequence[str],
    limits: NarrativeLimits | None = None,
) -> NarrativeRequestV1:
    """Build claims only from a caller's read-only transaction and exact current watermark."""
    limits = limits or NarrativeLimits.from_env()
    if not isinstance(insight_ids, (list, tuple)) or not insight_ids:
        raise NarrativeError("empty_insight_selection", "select at least one finalized insight")
    if len(insight_ids) > min(limits.max_selected_insights, MAX_SELECTED_INSIGHTS):
        raise NarrativeError("narrative_input_limit", "too many insights were selected")
    if any(not isinstance(value, str) or not value for value in insight_ids):
        raise NarrativeError("invalid_narrative_request", "insight identifiers must be non-empty strings")
    if len(set(insight_ids)) != len(insight_ids):
        raise NarrativeError("invalid_narrative_request", "insight identifiers must be unique")

    if not session.in_transaction():
        raise NarrativeError("read_only_transaction_required", "narrative evidence preparation requires an active read-only transaction")
    if session.get_bind().dialect.name == "postgresql":
        read_only = session.execute(text("SHOW transaction_read_only")).scalar_one()
        if str(read_only).lower() not in ("on", "true", "1"):
            raise NarrativeError("read_only_transaction_required", "narrative evidence preparation requires a read-only database transaction")

    match = session.get(MatchRecord, match_id)
    if match is None:
        raise MatchNotFound(match_id)
    events = read_finalized_prefix(session, match, match.finalized_sequence, match.finalized_event_id)
    snapshot, insights = calculate_intelligence(
        events,
        match_id=match.match_id,
        simulation_run_id=match.simulation_run_id,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        as_of_sequence=match.finalized_sequence,
        as_of_event_id=match.finalized_event_id,
    )
    try:
        expected = NarrativeAsOf.model_validate(expected_as_of)
    except ValidationError as exc:
        raise NarrativeError("invalid_narrative_request", "the requested finalized snapshot marker is invalid") from exc
    actual = NarrativeAsOf.model_validate(snapshot["as_of"])
    if expected != actual:
        raise NarrativeError("stale_snapshot", "the requested intelligence snapshot is no longer current")

    validated_insights = [IntelligenceInsightV1.model_validate(insight).model_dump(mode="json") for insight in insights]
    selected = {
        insight["insight_id"]: insight
        for insight in validated_insights
        if insight["insight_id"] in insight_ids
    }
    if len(selected) != len(insight_ids):
        raise NarrativeError("unknown_insight", "one or more selected insights are not in this finalized match snapshot")
    event_by_id = {event["event_id"]: event for event in events}
    roles = {match.home_team_id: "home", match.away_team_id: "away"}
    claims: list[ApprovedClaimV1] = []
    for insight_id in insight_ids:
        insight = selected[insight_id]
        team_id = insight["team_id"]
        role = roles.get(team_id)
        if role is None:
            raise NarrativeError("event_log_mismatch", "insight team is outside the match")
        evidence_ids = insight["evidence_event_ids"]
        evidence = [event_by_id.get(event_id) for event_id in evidence_ids]
        if any(item is None for item in evidence):
            raise NarrativeError("unfinalized_evidence", "insight evidence is not in the finalized event prefix")
        if any(
            item["match_id"] != match.match_id
            or item["simulation_run_id"] != match.simulation_run_id
            or item["sequence"] > match.finalized_sequence
            for item in evidence
        ):
            raise NarrativeError("unfinalized_evidence", "insight evidence does not match the finalized snapshot")
        claim_data = {
            "claim_kind": insight["rule_id"],
            "match_id": match.match_id,
            "simulation_run_id": match.simulation_run_id,
            "synthetic": True,
            "as_of": actual.model_dump(mode="json"),
            "insight_id": insight["insight_id"],
            "rule_id": insight["rule_id"],
            "rule_version": insight["rule_version"],
            "trigger_event_id": insight["trigger_event_id"],
            "trigger_sequence": insight["trigger_sequence"],
            "team_id": team_id,
            "team_role": role,
            "period": insight["period"],
            "match_elapsed_ms": insight["clock"]["match_elapsed_ms"],
            "period_elapsed_ms": insight["clock"]["period_elapsed_ms"],
            "observed_facts": insight["observed_facts"],
            "window": insight["window"],
            "evidence_event_ids": evidence_ids,
        }
        claim_data["claim_id"] = _claim_id(claim_identity(claim_data))
        claims.append(ApprovedClaimV1.model_validate(claim_data))

    if len(claims) > min(limits.max_approved_claims, MAX_APPROVED_CLAIMS):
        raise NarrativeError("narrative_input_limit", "too many approved claims were prepared")
    return NarrativeRequestV1(
        schema_version=1,
        narrative_kind="match_insight_explanation",
        language="en",
        match_id=match.match_id,
        simulation_run_id=match.simulation_run_id,
        synthetic=True,
        as_of=actual,
        claims=claims,
    )
