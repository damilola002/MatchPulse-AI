"""Deterministic, finalized-event match intelligence (Phase 3)."""

from .engine import (
    METRIC_DEFINITION_VERSION,
    RULE_VERSIONS,
    calculate_intelligence,
)

__all__ = ["METRIC_DEFINITION_VERSION", "RULE_VERSIONS", "calculate_intelligence"]
