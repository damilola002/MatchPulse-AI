"""Seeded scenario generator for entirely fictional synthetic matches."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from .models import MatchConfig, Period, Scenario
from .random_source import SeededRandom
from .serialization import canonical_json
from .validation import validate_event

GENERATOR_VERSION = "1.0.0"
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Attack:
    period: Period
    minute: int
    team_slot: int
    shot_outcome: str
    goal: bool = False
    foul: bool = False
    recovery: bool = False


_SCENARIOS: dict[Scenario, tuple[Attack, ...]] = {
    Scenario.BALANCED: (
        Attack(Period.FIRST_HALF, 4, 0, "saved"),
        Attack(Period.FIRST_HALF, 12, 1, "off_target"),
        Attack(Period.FIRST_HALF, 20, 0, "goal", goal=True),
        Attack(Period.FIRST_HALF, 31, 1, "blocked", foul=True, recovery=True),
        Attack(Period.FIRST_HALF, 41, 0, "woodwork"),
        Attack(Period.SECOND_HALF, 5, 1, "saved"),
        Attack(Period.SECOND_HALF, 15, 0, "off_target"),
        Attack(Period.SECOND_HALF, 25, 1, "goal", goal=True),
        Attack(Period.SECOND_HALF, 35, 0, "saved", recovery=True),
        Attack(Period.SECOND_HALF, 43, 1, "blocked"),
    ),
    Scenario.LATE_COMEBACK: (
        Attack(Period.FIRST_HALF, 8, 0, "goal", goal=True),
        Attack(Period.FIRST_HALF, 22, 1, "goal", goal=True),
        Attack(Period.FIRST_HALF, 39, 0, "off_target", foul=True),
        Attack(Period.SECOND_HALF, 9, 0, "saved"),
        Attack(Period.SECOND_HALF, 20, 1, "off_target"),
        Attack(Period.SECOND_HALF, 29, 0, "goal", goal=True),
        Attack(Period.SECOND_HALF, 39, 1, "goal", goal=True),
        Attack(Period.SECOND_HALF, 44, 1, "goal", goal=True),
    ),
    Scenario.SUSTAINED_PRESSURE: (
        Attack(Period.FIRST_HALF, 8, 1, "saved"),
        Attack(Period.FIRST_HALF, 25, 0, "goal", goal=True),
        Attack(Period.FIRST_HALF, 28, 0, "saved"),
        Attack(Period.FIRST_HALF, 31, 0, "blocked"),
        Attack(Period.FIRST_HALF, 34, 0, "saved", recovery=True),
        Attack(Period.FIRST_HALF, 38, 0, "off_target"),
        Attack(Period.SECOND_HALF, 8, 0, "saved"),
        Attack(Period.SECOND_HALF, 11, 0, "saved"),
        Attack(Period.SECOND_HALF, 14, 1, "off_target"),
        Attack(Period.SECOND_HALF, 16, 0, "blocked"),
        Attack(Period.SECOND_HALF, 19, 0, "off_target"),
        Attack(Period.SECOND_HALF, 23, 1, "saved"),
    ),
    Scenario.LOW_EVENT: (
        Attack(Period.FIRST_HALF, 27, 0, "off_target", foul=True),
        Attack(Period.FIRST_HALF, 41, 1, "saved"),
        Attack(Period.SECOND_HALF, 20, 0, "blocked", recovery=True),
    ),
}


def simulation_run_id(config: MatchConfig) -> str:
    material = f"{GENERATOR_VERSION}\n{canonical_json(config.canonical_config())}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class _Builder:
    def __init__(self, config: MatchConfig) -> None:
        self.config = config
        self.run_id = simulation_run_id(config)
        self.rng = SeededRandom(config.seed)
        self.events: list[dict[str, Any]] = []

    def emit(
        self,
        event_type: str,
        period: Period,
        period_elapsed_ms: int,
        *,
        team_id: str | None = None,
        player_id: str | None = None,
        location: dict[str, int] | None = None,
        outcome: str | None = None,
        causal_event_ids: tuple[str, ...] = (),
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        offset = self.config.first_half_duration_ms if period is Period.SECOND_HALF else 0
        sequence = len(self.events) + 1
        event = {
            "event_id": f"{self.run_id}:{sequence}",
            "schema_version": SCHEMA_VERSION,
            "match_id": self.config.match_id,
            "simulation_run_id": self.run_id,
            "sequence": sequence,
            "clock": {
                "match_elapsed_ms": offset + period_elapsed_ms,
                "period": period.value,
                "period_elapsed_ms": period_elapsed_ms,
            },
            "type": event_type,
            "team_id": team_id,
            "player_id": player_id,
            "location": location,
            "outcome": outcome,
            "causal_event_ids": list(causal_event_ids),
            "data": data or {},
            "provenance": {
                "synthetic": True,
                "generator": "matchpulse-sim",
                "generator_version": GENERATOR_VERSION,
                "scenario_id": self.config.scenario.value,
                "seed": self.config.seed,
            },
        }
        validate_event(event)
        self.events.append(event)
        return event

    def location(self, team_slot: int, period: Period, progress: int | None = None) -> dict[str, int]:
        along_attack = 20 + self.rng.randbelow(76) if progress is None else progress
        team_attacks_increasing_x = (team_slot == 0 and period is Period.FIRST_HALF) or (
            team_slot == 1 and period is Period.SECOND_HALF
        )
        x = along_attack if team_attacks_increasing_x else 100 - along_attack
        return {"x": x, "y": self.rng.randbelow(101)}

    def player(self, team_slot: int, *, exclude: str | None = None) -> Any:
        players = tuple(p for p in self.config.teams[team_slot].players if p.player_id != exclude)
        if not players:
            players = self.config.teams[team_slot].players
        return players[self.rng.randbelow(len(players))]

    def change_possession(
        self,
        period: Period,
        at_ms: int,
        from_team_id: str | None,
        to_team_id: str | None,
        reason: str,
        cause: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cause_id = cause["event_id"] if cause else None
        if to_team_id is None:
            outcome = "dead_ball"
        elif reason == "goal_restart":
            outcome = "restart"
        else:
            outcome = "gained_control"
        return self.emit(
            "possession_change", period, at_ms,
            team_id=to_team_id,
            outcome=outcome,
            causal_event_ids=(cause_id,) if cause_id else (),
            data={
                "from_team_id": from_team_id,
                "to_team_id": to_team_id,
                "reason": reason,
                "cause_event_id": cause_id,
            },
        )


def generate_events(config: MatchConfig) -> list[dict[str, Any]]:
    """Generate a deterministic, self-describing synthetic match event stream."""
    events = _generate_chronological(config)
    from .replay import replay_events

    replay_events(events)
    return events


def _generate_chronological(config: MatchConfig) -> list[dict[str, Any]]:
    """Emit halves in order; separated to keep boundary transitions explicit."""
    # The public builder above creates the deterministic identity source only;
    # this fresh builder emits the actual chronological stream.
    builder = _Builder(config)
    home, away = config.teams
    start = builder.emit(
        "match_start", Period.FIRST_HALF, 0, outcome="started",
        data={
            "home_team": _team_data(home), "away_team": _team_data(away),
            "kickoff_team_id": home.team_id,
            "first_half_regulation_ms": config.first_half_regulation_ms,
            "first_half_stoppage_ms": config.first_half_stoppage_ms,
            "second_half_regulation_ms": config.second_half_regulation_ms,
            "second_half_stoppage_ms": config.second_half_stoppage_ms,
        },
    )
    current = home.team_id
    builder.change_possession(Period.FIRST_HALF, 0, None, current, "kickoff", start)
    for attack in _SCENARIOS[config.scenario]:
        if attack.period is Period.SECOND_HALF:
            break
        current = _emit_attack(builder, config, attack, current)
    if current is not None:
        builder.change_possession(Period.FIRST_HALF, config.first_half_duration_ms, current, None, "period_boundary", None)
    builder.emit("half_time", Period.FIRST_HALF, config.first_half_duration_ms, outcome="half_time")
    second_start = builder.emit("second_half_start", Period.SECOND_HALF, 0, outcome="started")
    current = away.team_id
    builder.change_possession(Period.SECOND_HALF, 0, None, current, "kickoff", second_start)
    for attack in _SCENARIOS[config.scenario]:
        if attack.period is Period.SECOND_HALF:
            current = _emit_attack(builder, config, attack, current)
    if current is not None:
        builder.change_possession(Period.SECOND_HALF, config.second_half_duration_ms, current, None, "period_boundary", None)
    builder.emit("full_time", Period.SECOND_HALF, config.second_half_duration_ms, outcome="full_time")
    return builder.events


def _emit_attack(builder: _Builder, config: MatchConfig, attack: Attack, current: str | None) -> str:
    team = config.teams[attack.team_slot]
    opponent = config.teams[1 - attack.team_slot]
    at_ms = attack.minute * 60_000
    if current != team.team_id:
        tackler = builder.player(attack.team_slot)
        opponent_player = builder.player(1 - attack.team_slot)
        tackle = builder.emit(
            "tackle", attack.period, at_ms,
            team_id=team.team_id, player_id=tackler.player_id,
            location=builder.location(attack.team_slot, attack.period),
            outcome="won", data={"opponent_player_id": opponent_player.player_id},
        )
        builder.change_possession(attack.period, at_ms, current, team.team_id, "tackle", tackle)
        current = team.team_id

    passer = builder.player(attack.team_slot)
    last_pass: dict[str, Any] | None = None
    for _ in range(1 + builder.rng.randbelow(2)):
        receiver = builder.player(attack.team_slot, exclude=passer.player_id)
        last_pass = builder.emit(
            "pass", attack.period, at_ms,
            team_id=team.team_id, player_id=passer.player_id,
            location=builder.location(attack.team_slot, attack.period),
            outcome="completed",
            data={
                "receiver_player_id": receiver.player_id,
                "end_location": builder.location(attack.team_slot, attack.period),
            },
        )
        passer = receiver

    defender = builder.player(1 - attack.team_slot)
    pressure = builder.emit(
        "pressure", attack.period, at_ms,
        team_id=opponent.team_id, player_id=defender.player_id,
        location=builder.location(1 - attack.team_slot, attack.period),
        outcome="applied",
        causal_event_ids=(last_pass["event_id"],) if last_pass else (),
        data={"target_player_id": passer.player_id},
    )
    if attack.foul:
        fouler = builder.player(1 - attack.team_slot)
        builder.emit(
            "foul", attack.period, at_ms,
            team_id=opponent.team_id, player_id=fouler.player_id,
            location=builder.location(1 - attack.team_slot, attack.period),
            outcome="whistled",
            data={"fouled_team_id": team.team_id, "fouled_player_id": passer.player_id, "awarded_team_id": team.team_id},
        )

    shot = builder.emit(
        "shot", attack.period, at_ms,
        team_id=team.team_id, player_id=passer.player_id,
        location=builder.location(attack.team_slot, attack.period, 82 + builder.rng.randbelow(19)),
        outcome=attack.shot_outcome,
        causal_event_ids=(last_pass["event_id"], pressure["event_id"]),
        data={
            "shot_subtype": ("open_play", "header", "volley")[builder.rng.randbelow(3)],
            "target_location": builder.location(attack.team_slot, attack.period, 100),
            "rebound_available": attack.recovery,
        },
    )
    if attack.goal:
        goal = builder.emit(
            "goal", attack.period, at_ms,
            team_id=team.team_id, player_id=passer.player_id, outcome="scored",
            causal_event_ids=(shot["event_id"],),
            data={"source_shot_event_id": shot["event_id"], "scoring_team_id": team.team_id, "scorer_player_id": passer.player_id},
        )
        builder.change_possession(attack.period, at_ms, team.team_id, opponent.team_id, "goal_restart", goal)
        return opponent.team_id
    if attack.recovery:
        builder.change_possession(attack.period, at_ms, team.team_id, None, "shot", shot)
        recovery_player = builder.player(1 - attack.team_slot)
        recovery = builder.emit(
            "ball_recovery", attack.period, at_ms,
            team_id=opponent.team_id, player_id=recovery_player.player_id,
            location=builder.location(1 - attack.team_slot, attack.period),
            outcome="controlled", causal_event_ids=(shot["event_id"],),
            data={"recovery_kind": "loose_ball"},
        )
        builder.change_possession(attack.period, at_ms, None, opponent.team_id, "recovery", recovery)
    else:
        builder.change_possession(attack.period, at_ms, team.team_id, opponent.team_id, "shot", shot)
    return opponent.team_id


def _team_data(team: Any) -> dict[str, Any]:
    return {
        "team_id": team.team_id,
        "name": team.name,
        "players": [{"player_id": player.player_id, "name": player.name} for player in team.players],
    }
