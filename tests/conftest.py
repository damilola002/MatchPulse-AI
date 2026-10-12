from __future__ import annotations

import pytest

from matchpulse_sim.models import MatchConfig, Scenario, default_fixtures


@pytest.fixture
def config_factory():
    def make(scenario: Scenario = Scenario.BALANCED, seed: int = 17) -> MatchConfig:
        return MatchConfig(
            seed=seed,
            match_id="test-match",
            teams=default_fixtures(),
            scenario=scenario,
        )

    return make
