from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StartMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_event: dict[str, Any]


class EventBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict[str, Any]] = Field(min_length=1)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class MatchStateResponse(BaseModel):
    match_id: str
    simulation_run_id: str
    scenario_id: str
    synthetic: bool
    status: str
    period: str | None
    clock: dict[str, int]
    score: dict[str, int]
    current_possession_team_id: str | None
    shots: dict[str, int]
    last_accepted_sequence: int
    last_accepted_event_id: str
    last_accepted_match_elapsed_ms: int
    last_finalized_sequence: int
    last_finalized_event_id: str | None
    state_version: int
    transition_pending: bool


class StartMatchResponse(BaseModel):
    state: MatchStateResponse
    duplicate: bool


class IngestResponse(BaseModel):
    match_id: str
    simulation_run_id: str
    accepted_count: int
    duplicate_count: int
    first_new_sequence: int | None
    last_accepted_sequence: int
    last_event_id: str
    last_finalized_sequence: int
    state_version: int
    state: MatchStateResponse


class EventPageResponse(BaseModel):
    match_id: str
    simulation_run_id: str
    events: list[dict[str, Any]]
    last_accepted_sequence: int
    last_finalized_sequence: int
    next_after_sequence: int
