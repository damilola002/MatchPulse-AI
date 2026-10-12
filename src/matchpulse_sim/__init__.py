"""Deterministic synthetic football match event generation and replay."""

from .generator import GENERATOR_VERSION, generate_events
from .models import MatchConfig, Period, Scenario, TeamFixture, PlayerFixture
from .replay import MatchState, replay_events
from .validation import validate_event, validate_event_stream

__all__ = [
    "GENERATOR_VERSION",
    "MatchConfig",
    "MatchState",
    "Period",
    "PlayerFixture",
    "Scenario",
    "TeamFixture",
    "generate_events",
    "replay_events",
    "validate_event",
    "validate_event_stream",
]
