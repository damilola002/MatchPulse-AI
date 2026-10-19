from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


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


class IntelligenceMetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: StrictInt | StrictStr | None
    unit: str
    numerator: int
    denominator: int


class IntelligenceTeamMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals: IntelligenceMetricValue
    shots: IntelligenceMetricValue
    shot_outcomes: ShotOutcomeMetrics
    logged_pressure_events: IntelligenceMetricValue
    goals_per_shot: IntelligenceMetricValue


class ShotOutcomeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: IntelligenceMetricValue
    saved: IntelligenceMetricValue
    blocked: IntelligenceMetricValue
    off_target: IntelligenceMetricValue
    woodwork: IntelligenceMetricValue


class IntelligenceTeam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str
    role: Literal["home", "away"]
    metrics: IntelligenceTeamMetrics


class IntelligenceAsOf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int
    event_id: str | None
    match_elapsed_ms: int | None


class MetricSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    match_id: str
    simulation_run_id: str
    synthetic: Literal[True]
    metric_definition_version: str
    as_of: IntelligenceAsOf
    teams: list[IntelligenceTeam]


class IntelligenceClock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_elapsed_ms: int
    period_elapsed_ms: int


class InsightWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_match_elapsed_ms: int
    end_match_elapsed_ms: int
    inclusive: Literal[True]


class InsightThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal[">="]
    value: int
    unit: str


class Score(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home: int
    away: int


class ScoreChangeFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_before: Score
    score_after: Score


class ShotActivityFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualifying_shot_count: int


class PressureActivityFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualifying_pressure_event_count: int


class IntelligenceInsightV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    insight_id: str
    match_id: str
    simulation_run_id: str
    synthetic: Literal[True]
    rule_id: Literal["score_change", "shot_activity", "pressure_activity"]
    rule_version: str
    team_id: str
    period: Literal["first_half", "second_half"]
    clock: IntelligenceClock
    trigger_event_id: str
    trigger_sequence: int
    window: InsightWindow | None
    observed_facts: ScoreChangeFacts | ShotActivityFacts | PressureActivityFacts
    threshold: InsightThreshold | None
    evidence_event_ids: list[str]


class IntelligenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    simulation_run_id: str
    synthetic: Literal[True]
    as_of: IntelligenceAsOf
    metric_snapshot: MetricSnapshotV1
    insights: list[IntelligenceInsightV1]
    next_cursor: str | None
