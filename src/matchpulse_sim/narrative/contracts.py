"""Versioned, bounded Phase 4 narrative contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from ..api.schemas import InsightWindow, PressureActivityFacts, ScoreChangeFacts, ShotActivityFacts


class NarrativeAsOf(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sequence: StrictInt = Field(ge=0)
    event_id: StrictStr | None = Field(max_length=64)
    match_elapsed_ms: StrictInt | None = Field(ge=0)


class ApprovedClaimV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_id: StrictStr = Field(pattern=r"^claim:v1:[0-9a-f]{64}$")
    claim_kind: Literal["score_change", "shot_activity", "pressure_activity"]
    match_id: StrictStr = Field(min_length=1, max_length=64)
    simulation_run_id: StrictStr = Field(min_length=1, max_length=32)
    synthetic: Literal[True]
    as_of: NarrativeAsOf
    insight_id: StrictStr = Field(pattern=r"^insight:v1:[0-9a-f]{64}$")
    rule_id: Literal["score_change", "shot_activity", "pressure_activity"]
    rule_version: StrictStr
    trigger_event_id: StrictStr = Field(min_length=1, max_length=64)
    trigger_sequence: StrictInt = Field(ge=1)
    team_id: StrictStr
    team_role: Literal["home", "away"]
    period: Literal["first_half", "second_half"]
    match_elapsed_ms: StrictInt = Field(ge=0)
    period_elapsed_ms: StrictInt = Field(ge=0)
    observed_facts: ScoreChangeFacts | ShotActivityFacts | PressureActivityFacts
    window: InsightWindow | None
    evidence_event_ids: list[StrictStr] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_claim_shape(self) -> "ApprovedClaimV1":
        if self.rule_id != self.claim_kind:
            raise ValueError("claim kind must match its Phase 3 rule")
        if len(set(self.evidence_event_ids)) != len(self.evidence_event_ids):
            raise ValueError("claim evidence IDs must be unique")
        sequences: list[int] = []
        for event_id in self.evidence_event_ids:
            prefix = f"{self.simulation_run_id}:"
            if not event_id.startswith(prefix) or not event_id[len(prefix):].isdigit():
                raise ValueError("evidence event IDs must belong to the claim's simulation run")
            sequence = int(event_id[len(prefix):])
            if sequence < 1 or sequence > self.as_of.sequence or event_id != f"{self.simulation_run_id}:{sequence}":
                raise ValueError("evidence event IDs must be within the finalized snapshot")
            sequences.append(sequence)
        if sequences != sorted(sequences):
            raise ValueError("evidence event IDs must be in sequence order")
        if self.trigger_sequence > self.as_of.sequence or self.trigger_event_id != f"{self.simulation_run_id}:{self.trigger_sequence}":
            raise ValueError("claim trigger must be within its finalized snapshot")
        if self.trigger_event_id not in self.evidence_event_ids:
            raise ValueError("claim trigger event must be included in its evidence")
        if self.claim_kind == "score_change":
            if self.window is not None or not isinstance(self.observed_facts, ScoreChangeFacts):
                raise ValueError("score change claims require score facts and no activity window")
            if self.evidence_event_ids != [self.trigger_event_id]:
                raise ValueError("score change evidence must be exactly its goal event")
        elif self.claim_kind == "shot_activity":
            if self.window is None or not isinstance(self.observed_facts, ShotActivityFacts):
                raise ValueError("shot activity claims require a window and shot count")
            if self.observed_facts.qualifying_shot_count != len(self.evidence_event_ids):
                raise ValueError("shot activity count must match its exact evidence set")
        elif self.claim_kind == "pressure_activity":
            if self.window is None or not isinstance(self.observed_facts, PressureActivityFacts):
                raise ValueError("pressure activity claims require a window and pressure count")
            if self.observed_facts.qualifying_pressure_event_count != len(self.evidence_event_ids):
                raise ValueError("pressure activity count must match its exact evidence set")
        if self.window is not None:
            if (
                self.window.start_match_elapsed_ms > self.match_elapsed_ms
                or self.window.end_match_elapsed_ms != self.match_elapsed_ms
            ):
                raise ValueError("activity window must end at the claim trigger clock")
        return self


class NarrativeRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    narrative_kind: Literal["match_insight_explanation"]
    language: Literal["en"]
    match_id: StrictStr = Field(min_length=1, max_length=64)
    simulation_run_id: StrictStr = Field(min_length=1, max_length=32)
    synthetic: Literal[True]
    as_of: NarrativeAsOf
    claims: list[ApprovedClaimV1] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_claim_scope(self) -> "NarrativeRequestV1":
        if self.as_of.sequence == 0 or self.as_of.event_id != f"{self.simulation_run_id}:{self.as_of.sequence}" or self.as_of.match_elapsed_ms is None:
            raise ValueError("narrative requests require a valid positive finalized watermark")
        if any(
            claim.match_id != self.match_id
            or claim.simulation_run_id != self.simulation_run_id
            or claim.as_of != self.as_of
            for claim in self.claims
        ):
            raise ValueError("all claims must match the narrative snapshot identity")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("narrative claim IDs must be unique")
        return self


class NarrativeGenerationRequest(BaseModel):
    """Small browser request; claim content is always resolved server-side."""

    model_config = ConfigDict(extra="forbid", strict=True)

    simulation_run_id: StrictStr = Field(min_length=1, max_length=32)
    as_of: NarrativeAsOf
    insight_ids: list[StrictStr] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_selection(self) -> "NarrativeGenerationRequest":
        if any(not item for item in self.insight_ids) or len(set(self.insight_ids)) != len(self.insight_ids):
            raise ValueError("insight IDs must be non-empty and unique")
        return self


class ProviderBlockV1(BaseModel):
    """Provider may order claims and select only exact application-owned wording."""

    model_config = ConfigDict(extra="forbid", strict=True)

    claim_id: StrictStr
    text: StrictStr = Field(min_length=1, max_length=500)


class ProviderSelectionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    blocks: list[ProviderBlockV1] = Field(min_length=1, max_length=20)


class NarrativeBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_ids: list[StrictStr] = Field(min_length=1, max_length=1)
    insight_ids: list[StrictStr] = Field(min_length=1, max_length=1)
    evidence_event_ids: list[StrictStr] = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=500)


class NarrativeResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    narrative_id: StrictStr = Field(pattern=r"^narrative:v1:[0-9a-f]{64}$")
    narrative_kind: Literal["match_insight_explanation"]
    language: Literal["en"]
    match_id: StrictStr
    simulation_run_id: StrictStr
    synthetic: Literal[True]
    as_of: NarrativeAsOf
    narrative_contract_version: Literal["1.0.0"]
    provider: StrictStr = Field(min_length=1, max_length=64)
    model: StrictStr = Field(min_length=1, max_length=128)
    prompt_version: Literal["narrative-prompt-v1"]
    blocks: list[NarrativeBlockV1] = Field(min_length=1, max_length=20)
