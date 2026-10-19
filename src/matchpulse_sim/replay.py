"""Pure match-state reducer with sequence, reference, and lifecycle checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import MAX_STOPPAGE_MS, SCENARIO_MIN_PERIOD_DURATION_MS, Scenario
from .validation import EventValidationError, validate_event


class ReplayError(ValueError):
    """Raised when a schema-valid event stream violates match invariants."""


@dataclass(frozen=True, slots=True)
class MatchState:
    match_id: str
    simulation_run_id: str
    status: str
    period: str | None
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    current_possession: str | None
    home_shots: int
    away_shots: int
    last_sequence: int
    last_match_elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "simulation_run_id": self.simulation_run_id,
            "status": self.status,
            "period": self.period,
            "teams": {
                self.home_team_id: {"score": self.home_score, "shots": self.home_shots},
                self.away_team_id: {"score": self.away_score, "shots": self.away_shots},
            },
            "current_possession": self.current_possession,
            "last_sequence": self.last_sequence,
            "last_match_elapsed_ms": self.last_match_elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class ReplayProgress:
    """Stable projection plus accepted-prefix and pending-transition metadata."""

    state: MatchState
    accepted_sequence: int
    accepted_event_id: str
    accepted_match_elapsed_ms: int
    finalized_sequence: int
    finalized_period_elapsed_ms: int
    pending_transition: dict[str, Any] | None
    complete: bool


def replay_events(events: Iterable[dict[str, Any]]) -> MatchState:
    """Validate a complete event stream and return its final state."""
    progress = replay_prefix(events)
    if progress.pending_transition is not None:
        if progress.pending_transition.get("goal_event_id"):
            raise ReplayError("goal-outcome shot has no matching goal event")
        raise ReplayError("event stream ends before required possession transition")
    if not progress.complete:
        raise ReplayError("event stream must end with full_time")
    if progress.state.current_possession is not None:
        raise ReplayError("full-time state must have no current possession")
    return progress.state


def replay_prefix(events: Iterable[dict[str, Any]]) -> ReplayProgress:
    """Reduce a valid prefix; retain the last stable state if a transition is pending.

    This is the shared event-by-event state machine used by both live ingestion and
    complete replay. The input may stop after a cause event while awaiting its
    required continuation; that provisional state is represented only by metadata.
    """
    return _replay_prefix(events, stable_history=None)


def replay_prefix_with_history(
    events: Iterable[dict[str, Any]],
) -> tuple[ReplayProgress, tuple[tuple[int, MatchState], ...]]:
    """Reduce a prefix and return stable states at their finalized sequence.

    This is an additive view of the same reducer, used when consumers need
    evidence-backed transitions without implementing a second state machine.
    Pending states are never included in the history.
    """
    history: list[tuple[int, MatchState]] = []
    progress = _replay_prefix(events, stable_history=history)
    return progress, tuple(history)


def _replay_prefix(
    events: Iterable[dict[str, Any]],
    *,
    stable_history: list[tuple[int, MatchState]] | None,
) -> ReplayProgress:
    stream = list(events)
    if not stream:
        raise ReplayError("event stream must not be empty")
    try:
        validate_event(stream[0])
    except EventValidationError as exc:
        raise ReplayError(f"event 1: {exc}") from exc
    if stream[0]["type"] != "match_start":
        raise ReplayError("first event must be match_start")

    known_ids: dict[str, dict[str, Any]] = {}
    seen_goal_sources: set[str] = set()
    shot_by_id: dict[str, dict[str, Any]] = {}
    home_score = away_score = home_shots = away_shots = 0
    possession: str | None = None
    status = "scheduled"
    period: str | None = None
    pending_goal: dict[str, Any] | None = None
    pending_change: dict[str, Any] | None = None
    last_clock = -1
    first_duration = second_duration = 0
    home_team_id = away_team_id = ""
    team_players: dict[str, set[str]] = {}
    finalized_sequence = 0
    stable_state: MatchState | None = None
    match_id = stream[0].get("match_id", "")
    run_id = stream[0].get("simulation_run_id", "")
    scenario_id = stream[0]["provenance"]["scenario_id"]
    seed = stream[0]["provenance"]["seed"]

    def snapshot(sequence: int, *, state_status: str | None = None) -> MatchState:
        return MatchState(
            match_id=match_id,
            simulation_run_id=run_id,
            status=state_status or status,
            period=period,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            current_possession=possession,
            home_shots=home_shots,
            away_shots=away_shots,
            last_sequence=sequence,
            last_match_elapsed_ms=max(last_clock, 0),
        )

    def finalize_if_stable(sequence: int) -> None:
        nonlocal finalized_sequence, stable_state
        if pending_goal is None and pending_change is None:
            finalized_sequence = sequence
            stable_state = snapshot(sequence)
            if stable_history is not None:
                stable_history.append((sequence, stable_state))

    for expected_sequence, event in enumerate(stream, start=1):
        try:
            validate_event(event)
        except EventValidationError as exc:
            raise ReplayError(f"event {expected_sequence}: {exc}") from exc
        if event["sequence"] != expected_sequence:
            raise ReplayError(f"sequence must be contiguous; expected {expected_sequence}")
        if event["match_id"] != match_id or event["simulation_run_id"] != run_id:
            raise ReplayError("all events must belong to the same match and simulation run")
        provenance = event["provenance"]
        if not provenance["synthetic"]:
            raise ReplayError("all generated match events must be labeled synthetic")
        if provenance["scenario_id"] != scenario_id or provenance["seed"] != seed:
            raise ReplayError("provenance must be consistent throughout the run")
        for causal_id in event["causal_event_ids"]:
            if causal_id not in known_ids:
                raise ReplayError(f"causal event {causal_id!r} must refer to a prior event")

        clock = event["clock"]
        period_name = clock["period"]
        period_ms = clock["period_elapsed_ms"]
        elapsed = clock["match_elapsed_ms"]
        if expected_sequence > 1 and elapsed < last_clock:
            raise ReplayError("match clock must be non-decreasing")
        expected_elapsed = period_ms if period_name == "first_half" else first_duration + period_ms
        if expected_sequence == 1:
            expected_elapsed = 0
        elif first_duration and elapsed != expected_elapsed:
            raise ReplayError("match_elapsed_ms must equal period elapsed time plus prior playable period")
        if expected_sequence == 1 and (elapsed != 0 or period_ms != 0 or period_name != "first_half"):
            raise ReplayError("match_start must be at the beginning of the first half")
        if status == "ended":
            raise ReplayError("events are not allowed after full_time")
        if first_duration and period_ms > (first_duration if period_name == "first_half" else second_duration):
            raise ReplayError("event clock exceeds configured period duration")
        if period is not None and event["type"] not in ("second_half_start",) and period_name != period:
            raise ReplayError(f"event period {period_name} does not match active period {period}")

        event_type = event["type"]
        data = event["data"]
        team_id = event["team_id"]
        player_id = event["player_id"]

        if expected_sequence == 1:
            data = event["data"]
            home_team = data["home_team"]
            away_team = data["away_team"]
            home_team_id = home_team["team_id"]
            away_team_id = away_team["team_id"]
            if home_team_id == away_team_id:
                raise ReplayError("home and away team IDs must differ")
            team_players = {
                home_team_id: {p["player_id"] for p in home_team["players"]},
                away_team_id: {p["player_id"] for p in away_team["players"]},
            }
            all_players = set().union(*team_players.values())
            if len(all_players) != sum(len(players) for players in team_players.values()):
                raise ReplayError("player IDs must be unique across teams")
            if data["kickoff_team_id"] != home_team_id:
                raise ReplayError("the home team must take first-half kickoff in v1")
            stable_state = snapshot(0, state_status="scheduled")
            if stable_history is not None:
                stable_history.append((0, stable_state))
            first_duration = data["first_half_regulation_ms"] + data["first_half_stoppage_ms"]
            second_duration = data["second_half_regulation_ms"] + data["second_half_stoppage_ms"]
            if data["first_half_stoppage_ms"] > MAX_STOPPAGE_MS or data["second_half_stoppage_ms"] > MAX_STOPPAGE_MS:
                raise ReplayError("stoppage time cannot exceed 10 minutes per period")
            minimum_first, minimum_second = SCENARIO_MIN_PERIOD_DURATION_MS[Scenario(scenario_id)]
            for label, actual, minimum in (
                ("first_half", first_duration, minimum_first),
                ("second_half", second_duration, minimum_second),
            ):
                if actual < minimum:
                    raise ReplayError(
                        f"scenario '{scenario_id}' requires {label} duration >= {minimum} ms; got {actual} ms"
                    )
            status = "live"
            period = "first_half"
            pending_change = {
                "from": None, "to": home_team_id, "reason": "kickoff", "cause": event["event_id"]
            }
        else:
            if event_type == "possession_change" and pending_change is not None:
                change = data
                expected = pending_change
                if (
                    change["from_team_id"] != expected["from"]
                    or change["to_team_id"] != expected["to"]
                    or change["reason"] != expected["reason"]
                    or change["cause_event_id"] != expected["cause"]
                    or possession != expected["from"]
                ):
                    raise ReplayError("possession_change does not match the required transition")
                if event["team_id"] != expected["to"]:
                    raise ReplayError("possession_change team_id must equal to_team_id")
                expected_causes = [expected["cause"]] if expected["cause"] else []
                if event["causal_event_ids"] != expected_causes:
                    raise ReplayError("possession_change causal references do not match its cause")
                possession = expected["to"]
                pending_change = None
                known_ids[event["event_id"]] = event
                last_clock = elapsed
                finalize_if_stable(expected_sequence)
                continue

            if pending_change is not None:
                raise ReplayError("a required possession_change must immediately follow its cause")
            if pending_goal is not None and event_type != "goal":
                raise ReplayError("a goal-outcome shot must be followed immediately by its goal event")

            if event_type in {"half_time", "second_half_start", "full_time"}:
                if event_type == "half_time":
                    if status != "live" or period != "first_half" or period_ms != first_duration:
                        raise ReplayError("half_time must end the first period at its configured boundary")
                    if possession is not None:
                        raise ReplayError("possession must be cleared before half_time")
                    status = "half_time"
                elif event_type == "second_half_start":
                    if status != "half_time" or period_ms != 0 or elapsed != first_duration:
                        raise ReplayError("second_half_start must follow half_time at second-period time zero")
                    status = "live"
                    period = "second_half"
                    pending_change = {
                        "from": None, "to": away_team_id, "reason": "kickoff", "cause": event["event_id"]
                    }
                else:
                    if status != "live" or period != "second_half" or period_ms != second_duration:
                        raise ReplayError("full_time must end the second period at its configured boundary")
                    if possession is not None:
                        raise ReplayError("possession must be cleared before full_time")
                    status = "ended"
                    period = "second_half"
                known_ids[event["event_id"]] = event
                last_clock = elapsed
                finalize_if_stable(expected_sequence)
                continue

            if status != "live":
                raise ReplayError("play events are allowed only while the match is live")

            if event_type == "possession_change":
                change = data
                if change["reason"] != "period_boundary":
                    raise ReplayError("unsolicited possession_change; only its cause may authorize a transition")
                boundary = first_duration if period == "first_half" else second_duration
                if period_ms != boundary or change["from_team_id"] != possession or change["to_team_id"] is not None:
                    raise ReplayError("period-boundary possession changes must clear current possession at the boundary")
                if change["cause_event_id"] is not None or event["causal_event_ids"]:
                    raise ReplayError("period-boundary possession clear must not claim an event cause")
                possession = None
            else:
                if team_id not in team_players and event_type not in {"match_start"}:
                    raise ReplayError(f"unknown team reference: {team_id!r}")
                if player_id is not None and (team_id not in team_players or player_id not in team_players[team_id]):
                    raise ReplayError(f"player {player_id!r} does not belong to event team {team_id!r}")
                if event_type in {"pass", "shot"} and team_id != possession:
                    raise ReplayError(f"{event_type} team must have possession")
                if event_type == "pass":
                    receiver_id = data["receiver_player_id"]
                    if receiver_id is not None and receiver_id not in team_players[team_id]:
                        raise ReplayError("pass receiver must belong to the passing team")
                    if event["outcome"] in {"intercepted", "incomplete", "out_of_play"}:
                        to_team = (away_team_id if team_id == home_team_id else home_team_id) if event["outcome"] == "intercepted" else None
                        pending_change = {"from": team_id, "to": to_team, "reason": "pass", "cause": event["event_id"]}
                elif event_type == "shot":
                    shot_by_id[event["event_id"]] = event
                    if team_id == home_team_id:
                        home_shots += 1
                    else:
                        away_shots += 1
                    if event["outcome"] == "goal":
                        pending_goal = event
                    else:
                        to_team = None if data["rebound_available"] else (away_team_id if team_id == home_team_id else home_team_id)
                        pending_change = {"from": team_id, "to": to_team, "reason": "shot", "cause": event["event_id"]}
                elif event_type == "goal":
                    source_id = data["source_shot_event_id"]
                    source = shot_by_id.get(source_id)
                    if pending_goal is None or source is not pending_goal or source_id in seen_goal_sources:
                        raise ReplayError("goal must correspond to exactly one immediately preceding goal-outcome shot")
                    if event["causal_event_ids"] != [source_id]:
                        raise ReplayError("goal must cite its source shot as causal evidence")
                    if data["scoring_team_id"] != source["team_id"] or team_id != source["team_id"]:
                        raise ReplayError("goal scoring team must match source shot team in v1")
                    if data["scorer_player_id"] != source["player_id"] or player_id != source["player_id"]:
                        raise ReplayError("goal scorer must match source shot player in v1")
                    seen_goal_sources.add(source_id)
                    if team_id == home_team_id:
                        home_score += 1
                        restart_team = away_team_id
                    else:
                        away_score += 1
                        restart_team = home_team_id
                    pending_goal = None
                    pending_change = {
                        "from": team_id, "to": restart_team, "reason": "goal_restart", "cause": event["event_id"]
                    }
                elif event_type == "tackle":
                    if possession is None:
                        raise ReplayError("tackle requires an opposing team to have possession")
                    if team_id == possession:
                        raise ReplayError("tackle team must be opposing the current possessor")
                    opponent_player = data["opponent_player_id"]
                    if opponent_player is not None and opponent_player not in team_players[possession]:
                        raise ReplayError("tackle opponent player must belong to the current possessor")
                    if event["outcome"] == "won":
                        pending_change = {"from": possession, "to": team_id, "reason": "tackle", "cause": event["event_id"]}
                elif event_type == "ball_recovery":
                    if possession is not None:
                        raise ReplayError("ball_recovery requires unassigned possession")
                    pending_change = {"from": None, "to": team_id, "reason": "recovery", "cause": event["event_id"]}
                elif event_type == "pressure":
                    if team_id == possession:
                        raise ReplayError("pressure team must be out of possession in v1")
                    target = data["target_player_id"]
                    if target is not None and (possession not in team_players or target not in team_players[possession]):
                        raise ReplayError("pressure target must belong to the team in possession")
                elif event_type == "foul":
                    fouled_team = data["fouled_team_id"]
                    if fouled_team not in team_players or fouled_team == team_id:
                        raise ReplayError("foul must identify an opposing fouled team")
                    fouled_player = data["fouled_player_id"]
                    if fouled_player is not None and fouled_player not in team_players[fouled_team]:
                        raise ReplayError("fouled player must belong to fouled team")
                    awarded = data["awarded_team_id"]
                    if awarded is not None and awarded not in team_players:
                        raise ReplayError("awarded team must be a match team")
                    if awarded is not None and awarded != possession:
                        pending_change = {"from": possession, "to": awarded, "reason": "foul", "cause": event["event_id"]}

        known_ids[event["event_id"]] = event
        last_clock = elapsed

        finalize_if_stable(expected_sequence)

    if status == "ended" and pending_goal is None and pending_change is None:
        for shot in shot_by_id.values():
            if shot["outcome"] == "goal" and shot["event_id"] not in seen_goal_sources:
                raise ReplayError("every goal-outcome shot requires exactly one goal event")
    pending: dict[str, Any] | None = None
    if pending_goal is not None or pending_change is not None:
        pending = {
            "goal_event_id": pending_goal["event_id"] if pending_goal else None,
            "required_possession_change": pending_change,
        }
    if stable_state is None:
        raise ReplayError("could not establish an initial stable match projection")
    return ReplayProgress(
        state=stable_state,
        accepted_sequence=len(stream),
        accepted_event_id=stream[-1]["event_id"],
        accepted_match_elapsed_ms=stream[-1]["clock"]["match_elapsed_ms"],
        finalized_sequence=finalized_sequence,
        finalized_period_elapsed_ms=(
            stream[finalized_sequence - 1]["clock"]["period_elapsed_ms"]
            if finalized_sequence
            else 0
        ),
        pending_transition=pending,
        complete=status == "ended" and pending is None and possession is None,
    )


class IncrementalReducer:
    """Event-by-event facade over the same replay state machine.

    The current Phase 1 scenarios are small, so the initial implementation
    revalidates the accepted prefix on each append. This intentionally favors
    one source of domain rules over a second, subtly divergent reducer.
    """

    def __init__(self, accepted_prefix: Iterable[dict[str, Any]] = ()) -> None:
        self._events = list(accepted_prefix)
        self._progress = replay_prefix(self._events) if self._events else None

    @property
    def progress(self) -> ReplayProgress | None:
        return self._progress

    def accept(self, event: dict[str, Any]) -> ReplayProgress:
        candidate = [*self._events, event]
        progress = replay_prefix(candidate)
        self._events.append(event)
        self._progress = progress
        return progress
