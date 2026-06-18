"""Tests for the regime/consensus-throttled PortfolioConstructor (issue #662).

Hermetic: no env, no network, no DB. These are pure sync computations.
The formula under test is implemented faithfully and its *actual* output is
asserted — constants are not tweaked to hit round numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from archimedes.models.regime import (
    ConsensusLabel,
    EnsembleConsensus,
    Regime,
    RegimeClassification,
    RegimeSignals,
)
from archimedes.services.portfolio_constructor import (
    REGIME_MULTIPLIER,
    REGIME_MULTIPLIER_NONE,
    SAFE_ASSET,
    PortfolioConstructor,
)


def _signals() -> RegimeSignals:
    """A minimal-but-valid RegimeSignals (only VIX + MA flags are required)."""
    return RegimeSignals(
        vix_level=18.0,
        vix_rate_of_change=0.0,
        sp500_above_ma50=True,
        sp500_above_ma200=True,
    )


def _regime(regime: Regime, confidence: float) -> RegimeClassification:
    return RegimeClassification(
        regime=regime,
        confidence=confidence,
        signals=_signals(),
        timestamp=datetime.now(UTC),
    )


def _consensus(flat_pct: float) -> EnsembleConsensus:
    return EnsembleConsensus(
        flat_pct=flat_pct,
        signal_count=10,
        label=EnsembleConsensus.label_for(flat_pct),
    )


@pytest.fixture
def pc() -> PortfolioConstructor:
    return PortfolioConstructor()


# ── compute_position_scale (the heart of the feature) ────────────────


def test_risk_on_full_confidence_decisive_ensemble_scale_one(pc: PortfolioConstructor) -> None:
    # RISK_ON mult=1.0, confidence=1.0 → (0.5 + 0.5*1.0)=1.0; flat_pct=0.1 → consensus 1.0.
    scale = pc.compute_position_scale(_regime(Regime.RISK_ON, 1.0), _consensus(0.1))
    assert scale == pytest.approx(1.0)


def test_crisis_high_flat_scale_small_but_positive(pc: PortfolioConstructor) -> None:
    # CRISIS mult=0.1, confidence=1.0 → 0.1; flat_pct=0.7 → consensus 0.6 → 0.06.
    scale = pc.compute_position_scale(_regime(Regime.CRISIS, 1.0), _consensus(0.7))
    assert 0.0 < scale <= 0.1
    assert scale == pytest.approx(0.06)


def test_risk_off_low_flat_no_consensus_penalty(pc: PortfolioConstructor) -> None:
    # Low flat = confident ensemble must NOT add a penalty → consensus_mult == 1.0.
    # RISK_OFF mult=0.4, confidence=1.0 → regime_mult=0.4; scale == regime_mult.
    regime = _regime(Regime.RISK_OFF, 1.0)
    scale = pc.compute_position_scale(regime, _consensus(0.1))
    regime_mult = REGIME_MULTIPLIER[Regime.RISK_OFF] * (0.5 + 0.5 * 1.0)
    assert scale == pytest.approx(regime_mult)
    assert scale == pytest.approx(0.4)


def test_regime_none_uses_conservative_default(pc: PortfolioConstructor) -> None:
    # regime None → regime_mult == REGIME_MULTIPLIER_NONE (0.7); decisive ensemble → x1.0.
    scale = pc.compute_position_scale(None, _consensus(0.1))
    assert REGIME_MULTIPLIER_NONE == pytest.approx(0.7)  # noqa: SIM300 — assert actual == expected reads naturally here
    assert scale == pytest.approx(0.7)


def test_consensus_none_no_penalty(pc: PortfolioConstructor) -> None:
    # ensemble_consensus None → consensus_mult == 1.0; RISK_ON full conf → 1.0.
    scale = pc.compute_position_scale(_regime(Regime.RISK_ON, 1.0), None)
    assert scale == pytest.approx(1.0)


def test_both_none_no_crash(pc: PortfolioConstructor) -> None:
    scale = pc.compute_position_scale(None, None)
    assert scale == pytest.approx(REGIME_MULTIPLIER_NONE)


def test_lower_confidence_gives_lower_scale(pc: PortfolioConstructor) -> None:
    # Same regime + same (no) consensus penalty; confidence 0.5 < 1.0 → lower scale.
    high = pc.compute_position_scale(_regime(Regime.RISK_ON, 1.0), None)
    low = pc.compute_position_scale(_regime(Regime.RISK_ON, 0.5), None)
    assert low < high
    # RISK_ON mult=1.0, confidence=0.5 → 0.5 + 0.5*0.5 = 0.75.
    assert low == pytest.approx(0.75)


def test_consensus_linear_interpolation_midpoint(pc: PortfolioConstructor) -> None:
    # flat_pct=0.45 is the midpoint of [0.30, 0.60] → consensus 1.0 - 0.5*0.4 = 0.8.
    # RISK_ON full confidence → regime_mult 1.0, so scale == 0.8.
    scale = pc.compute_position_scale(_regime(Regime.RISK_ON, 1.0), _consensus(0.45))
    assert scale == pytest.approx(0.8)


def test_scale_clamped_to_unit_interval(pc: PortfolioConstructor) -> None:
    # RISK_ON full confidence + decisive ensemble is the max case → must not exceed 1.0.
    scale = pc.compute_position_scale(_regime(Regime.RISK_ON, 1.0), _consensus(0.0))
    assert 0.0 <= scale <= 1.0


# ── construct() integration ──────────────────────────────────────────


def test_construct_crisis_shrinks_risk_assets_into_usdc(pc: PortfolioConstructor) -> None:
    base = {"sTSLA": 0.6, "sBTC": 0.4}
    allocs = pc.construct(
        risk_profile=None,  # type: ignore[arg-type]  # unused on the base_weights path
        strategies=[],
        backtest_results={},
        regime=_regime(Regime.CRISIS, 1.0),
        ensemble_consensus=_consensus(0.7),
        base_weights=base,
    )
    by_symbol = {a.symbol: a.weight for a in allocs}

    # Weights sum to 1.0.
    assert sum(by_symbol.values()) == pytest.approx(1.0)
    # USDC is now the dominant weight (risk assets throttled near-flat in crisis).
    assert by_symbol[SAFE_ASSET] > 0.9
    # Both risk assets shrunk vs their input weight.
    assert by_symbol["sTSLA"] < base["sTSLA"]
    assert by_symbol["sBTC"] < base["sBTC"]
    # Allocations carry empty token_address — the runner resolves addresses.
    assert all(a.token_address == "" for a in allocs)
    assert all(a.strategy_ids == [] for a in allocs)


def test_construct_risk_on_full_size_preserves_weights(pc: PortfolioConstructor) -> None:
    # scale == 1.0 → no throttle; weights pass through (with USDC entry created at 0).
    base = {"sTSLA": 0.6, "sBTC": 0.4}
    allocs = pc.construct(
        risk_profile=None,  # type: ignore[arg-type]
        strategies=[],
        backtest_results={},
        regime=_regime(Regime.RISK_ON, 1.0),
        ensemble_consensus=_consensus(0.1),
        base_weights=base,
    )
    by_symbol = {a.symbol: a.weight for a in allocs}
    assert sum(by_symbol.values()) == pytest.approx(1.0)
    assert by_symbol["sTSLA"] == pytest.approx(0.6)
    assert by_symbol["sBTC"] == pytest.approx(0.4)
    assert by_symbol[SAFE_ASSET] == pytest.approx(0.0)


def test_construct_existing_usdc_weight_preserved(pc: PortfolioConstructor) -> None:
    # An existing USDC weight is kept and accrues the freed mass.
    base = {"sTSLA": 0.5, SAFE_ASSET: 0.5}
    allocs = pc.construct(
        risk_profile=None,  # type: ignore[arg-type]
        strategies=[],
        backtest_results={},
        regime=_regime(Regime.RISK_OFF, 1.0),
        ensemble_consensus=None,
        base_weights=base,
    )
    by_symbol = {a.symbol: a.weight for a in allocs}
    assert sum(by_symbol.values()) == pytest.approx(1.0)
    # RISK_OFF full conf scale=0.4 → sTSLA 0.5*0.4=0.2, USDC 0.5+0.3=0.8.
    assert by_symbol["sTSLA"] == pytest.approx(0.2)
    assert by_symbol[SAFE_ASSET] == pytest.approx(0.8)


def test_construct_consensus_label_sanity() -> None:
    # Guard the bucket mapping the test fixtures rely on.
    assert EnsembleConsensus.label_for(0.1) == ConsensusLabel.RISK_ON
    assert EnsembleConsensus.label_for(0.45) == ConsensusLabel.TRANSITION
    assert EnsembleConsensus.label_for(0.7) == ConsensusLabel.RISK_OFF
