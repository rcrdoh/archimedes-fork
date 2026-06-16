"""Unit coverage for the regime data models — focused on EnsembleConsensus (#659).

EnsembleConsensus is the endogenous strategy-ensemble consensus derived from
`flat_pct`. It is deliberately NOT a `Regime`: it measures how decisive the
strategy ensemble is, not what the market is doing. These tests pin the bucket
thresholds, the validation, and the distinctness from `Regime`.
"""

from __future__ import annotations

import pytest
from archimedes.models.regime import (
    ConsensusLabel,
    EnsembleConsensus,
    Regime,
)


class TestConsensusLabel:
    def test_is_not_the_regime_enum(self) -> None:
        # Same string values by convention, but distinct types/semantics.
        assert ConsensusLabel is not Regime
        assert ConsensusLabel.RISK_ON.value == "risk_on"
        assert not isinstance(ConsensusLabel.RISK_ON, Regime)


class TestEnsembleConsensusBuckets:
    @pytest.mark.parametrize(
        ("flat_pct", "expected"),
        [
            (0.0, ConsensusLabel.RISK_ON),
            (0.30, ConsensusLabel.RISK_ON),  # boundary: not > 0.3
            (0.301, ConsensusLabel.TRANSITION),
            (0.50, ConsensusLabel.TRANSITION),
            (0.60, ConsensusLabel.TRANSITION),  # boundary: not > 0.6
            (0.601, ConsensusLabel.RISK_OFF),
            (1.0, ConsensusLabel.RISK_OFF),
        ],
    )
    def test_label_for_thresholds(self, flat_pct: float, expected: ConsensusLabel) -> None:
        assert EnsembleConsensus.label_for(flat_pct) is expected

    def test_from_signal_counts(self) -> None:
        c = EnsembleConsensus.from_signal_counts(flat_count=3, total_count=4)
        assert c.flat_pct == 0.75
        assert c.signal_count == 4
        assert c.label is ConsensusLabel.RISK_OFF

    def test_from_signal_counts_zero_total_is_risk_on(self) -> None:
        # No signals → flat_pct defaults to 0.0 → RISK_ON (fully directional prior).
        c = EnsembleConsensus.from_signal_counts(flat_count=0, total_count=0)
        assert c.flat_pct == 0.0
        assert c.signal_count == 0
        assert c.label is ConsensusLabel.RISK_ON

    def test_is_frozen(self) -> None:
        c = EnsembleConsensus.from_signal_counts(flat_count=1, total_count=2)
        with pytest.raises((AttributeError, TypeError)):
            c.flat_pct = 0.9  # type: ignore[misc]


class TestEnsembleConsensusValidation:
    def test_rejects_out_of_range_flat_pct(self) -> None:
        with pytest.raises(ValueError, match="flat_pct"):
            EnsembleConsensus(flat_pct=1.5, signal_count=3, label=ConsensusLabel.RISK_OFF)

    def test_rejects_negative_signal_count(self) -> None:
        with pytest.raises(ValueError, match="signal_count"):
            EnsembleConsensus(flat_pct=0.5, signal_count=-1, label=ConsensusLabel.TRANSITION)
