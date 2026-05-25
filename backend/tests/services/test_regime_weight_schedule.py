"""Tests for regime_weight_schedule — weight mixes sum to 1.0, tilt ordering works."""

import pytest

from archimedes.services.regime_weight_schedule import (
    apply_regime_tilt,
    regime_weight_schedule,
)


class TestRegimeWeightSchedule:
    @pytest.mark.parametrize("profile", ["fixed_income", "conservative", "moderate", "aggressive", "hyper_risky"])
    @pytest.mark.parametrize("regime", ["risk_on", "risk_off", "transition", "crisis"])
    def test_weights_sum_to_one(self, profile, regime):
        mix = regime_weight_schedule(profile, regime)
        total = mix["bull"] + mix["bear"] + mix["neutral"]
        assert abs(total - 1.0) < 1e-6, f"{profile}/{regime}: sum={total}"

    def test_moderate_risk_on_bull_heavy(self):
        mix = regime_weight_schedule("moderate", "risk_on")
        assert mix["bull"] == 0.70
        assert mix["bear"] == 0.25

    def test_moderate_risk_off_bear_heavy(self):
        mix = regime_weight_schedule("moderate", "risk_off")
        assert mix["bear"] == 0.70
        assert mix["bull"] == 0.25

    def test_aggressive_risk_on(self):
        mix = regime_weight_schedule("aggressive", "risk_on")
        assert mix["bull"] >= 0.80

    def test_conservative_crisis(self):
        mix = regime_weight_schedule("conservative", "crisis")
        assert mix["bear"] >= 0.70

    def test_unknown_profile_returns_default(self):
        mix = regime_weight_schedule("unknown_profile", "risk_on")
        assert mix["bull"] + mix["bear"] + mix["neutral"] == 1.0

    def test_unknown_regime_falls_back_to_transition(self):
        mix = regime_weight_schedule("moderate", "unknown_regime")
        expected = regime_weight_schedule("moderate", "transition")
        assert mix == expected


class TestApplyRegimeTilt:
    def test_sorts_by_dominant_regime(self):
        class FakeStrategy:
            def __init__(self, name, tag):
                self.name = name
                self.regime_tag = tag

        strategies = [
            FakeStrategy("bear1", "bear"),
            FakeStrategy("bull1", "bull"),
            FakeStrategy("neutral1", "regime_neutral"),
            FakeStrategy("bull2", "bull"),
        ]

        # risk_on/moderate → bull-heavy (0.70)
        sorted_strats, mix = apply_regime_tilt(strategies, "risk_on", "moderate")
        assert mix["bull"] > mix["bear"]
        # Bull strategies should come first
        assert sorted_strats[0].regime_tag == "bull"
        assert sorted_strats[1].regime_tag == "bull"

    def test_risk_off_puts_bear_first(self):
        class FakeStrategy:
            def __init__(self, name, tag):
                self.name = name
                self.regime_tag = tag

        strategies = [
            FakeStrategy("bull1", "bull"),
            FakeStrategy("bear1", "bear"),
        ]

        sorted_strats, mix = apply_regime_tilt(strategies, "risk_off", "moderate")
        assert mix["bear"] > mix["bull"]
        assert sorted_strats[0].regime_tag == "bear"
