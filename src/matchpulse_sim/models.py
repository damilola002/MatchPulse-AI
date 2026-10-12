"""Immutable configuration and match fixture models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MINUTE_MS = 60_000
MAX_STOPPAGE_MS = 10 * MINUTE_MS


class Scenario(StrEnum):
    BALANCED = "balanced"
    LATE_COMEBACK = "late_comeback"
    SUSTAINED_PRESSURE = "sustained_pressure"
    LOW_EVENT = "low_event_defensive"


class Period(StrEnum):
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


SCENARIO_MIN_PERIOD_DURATION_MS: dict[Scenario, tuple[int, int]] = {
    # Minimum total period-clock duration (regulation + stoppage) needed to
    # contain every scripted attack in each scenario. Boundary lifecycle events
    # occur at the configured duration and may share the final event timestamp.
    Scenario.BALANCED: (41 * MINUTE_MS, 43 * MINUTE_MS),
    Scenario.LATE_COMEBACK: (39 * MINUTE_MS, 44 * MINUTE_MS),
    Scenario.SUSTAINED_PRESSURE: (38 * MINUTE_MS, 23 * MINUTE_MS),
    Scenario.LOW_EVENT: (41 * MINUTE_MS, 20 * MINUTE_MS),
}


@dataclass(frozen=True, slots=True)
class PlayerFixture:
    player_id: str
    name: str

    def __post_init__(self) -> None:
        _validate_identifier(self.player_id, "player_id")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("player name must be a non-empty string")


@dataclass(frozen=True, slots=True)
class TeamFixture:
    team_id: str
    name: str
    players: tuple[PlayerFixture, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.team_id, "team_id")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("team name must be a non-empty string")
        if not isinstance(self.players, tuple) or not self.players:
            raise ValueError("players must be a non-empty tuple")
        player_ids = [player.player_id for player in self.players]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("player IDs must be unique within a team")


@dataclass(frozen=True, slots=True)
class MatchConfig:
    seed: int
    match_id: str
    teams: tuple[TeamFixture, TeamFixture]
    scenario: Scenario = Scenario.BALANCED
    first_half_regulation_ms: int = 45 * MINUTE_MS
    first_half_stoppage_ms: int = 2 * MINUTE_MS
    second_half_regulation_ms: int = 45 * MINUTE_MS
    second_half_stoppage_ms: int = 3 * MINUTE_MS

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not 0 <= self.seed <= (1 << 64) - 1:
            raise ValueError("seed must be between 0 and 2^64-1")
        _validate_identifier(self.match_id, "match_id")
        if not isinstance(self.teams, tuple) or len(self.teams) != 2:
            raise ValueError("exactly two team fixtures are required")
        if self.teams[0].team_id == self.teams[1].team_id:
            raise ValueError("home and away team IDs must differ")
        all_player_ids = [p.player_id for team in self.teams for p in team.players]
        if len(all_player_ids) != len(set(all_player_ids)):
            raise ValueError("player IDs must be unique across both teams")
        if not isinstance(self.scenario, Scenario):
            try:
                object.__setattr__(self, "scenario", Scenario(self.scenario))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unsupported scenario: {self.scenario!r}") from exc
        for name in (
            "first_half_regulation_ms",
            "second_half_regulation_ms",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("first_half_stoppage_ms", "second_half_stoppage_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_STOPPAGE_MS:
                raise ValueError(f"{name} must be an integer between 0 and 10 minutes")
        minimum_first, minimum_second = SCENARIO_MIN_PERIOD_DURATION_MS[self.scenario]
        for label, actual, minimum in (
            ("first_half", self.first_half_duration_ms, minimum_first),
            ("second_half", self.second_half_duration_ms, minimum_second),
        ):
            if actual < minimum:
                raise ValueError(
                    f"scenario '{self.scenario.value}' requires {label} duration "
                    f"(regulation plus stoppage) >= {minimum} ms to include its latest "
                    f"scripted event; got {actual} ms"
                )

    @property
    def home(self) -> TeamFixture:
        return self.teams[0]

    @property
    def away(self) -> TeamFixture:
        return self.teams[1]

    @property
    def first_half_duration_ms(self) -> int:
        return self.first_half_regulation_ms + self.first_half_stoppage_ms

    @property
    def second_half_duration_ms(self) -> int:
        return self.second_half_regulation_ms + self.second_half_stoppage_ms

    def canonical_config(self) -> dict[str, object]:
        return {
            "first_half_regulation_ms": self.first_half_regulation_ms,
            "first_half_stoppage_ms": self.first_half_stoppage_ms,
            "match_id": self.match_id,
            "scenario": self.scenario.value,
            "second_half_regulation_ms": self.second_half_regulation_ms,
            "second_half_stoppage_ms": self.second_half_stoppage_ms,
            "seed": self.seed,
            "teams": [
                {
                    "name": team.name,
                    "players": [
                        {"name": player.name, "player_id": player.player_id}
                        for player in team.players
                    ],
                    "team_id": team.team_id,
                }
                for team in self.teams
            ],
        }


def default_fixtures() -> tuple[TeamFixture, TeamFixture]:
    """Return fictional, deterministic fixtures; no real club/player data."""
    home = TeamFixture(
        "harbor-united",
        "Harbor United",
        tuple(PlayerFixture(f"harbor-{i:02}", name) for i, name in enumerate(
            ("Ari Vale", "Noah Reed", "Mika Stone", "Ira Cole", "Sam Rowan", "Levi North"), 1
        )),
    )
    away = TeamFixture(
        "cedar-athletic",
        "Cedar Athletic",
        tuple(PlayerFixture(f"cedar-{i:02}", name) for i, name in enumerate(
            ("Remy Ash", "Tavi Brook", "Eli Moss", "Jules Hart", "Rory Vale", "Asha Lake"), 1
        )),
    )
    return home, away


def _validate_identifier(value: object, field: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must match {IDENTIFIER.pattern}")
