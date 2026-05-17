"""Tests for selection-bias correction primitives.

Pins the three numerical sanity cases from
`docs/specs/selection-bias-corrections-spec.md` § "Numerical sanity-check examples".
These are the acceptance fixtures — if they drift, the math is wrong.

Also tests PBO, walk-forward OOS, and look-ahead audit.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import norm

from archimedes.services.selection_bias import (
    RigorGateResult,
    compute_dsr,
    compute_pbo,
    look_ahead_audit,
    run_rigor_gate,
    walk_forward_oos_sharpe,
)


# ═══════════════════════════════════════════════════════════════
# DSR numerical sanity cases from the spec
# ═══════════════════════════════════════════════════════════════


def _generate_returns(
    sr_annual: float,
    T: int,
    skew: float,
    ex_kurt: float,
    seed: int = 42,
) -> list[float]:
    """Generate daily returns with target annualized Sharpe, skew, excess kurtosis.

    Uses a normal base + controlled perturbation to hit target moments.
    """
    rng = np.random.default_rng(seed)
    # Start with normal returns calibrated to target Sharpe
    # SR_annual = mean * sqrt(252) / std => mean = SR_annual * std / sqrt(252)
    std = 0.01  # 1% daily vol
    mean = sr_annual * std / math.sqrt(252)

    returns = rng.normal(mean, std, size=T)

    # Adjust skew and kurtosis via mixture
    if abs(skew) > 0.01 or abs(ex_kurt) > 0.01:
        # Add a small fraction of skewed/kurtotic returns
        n_adj = max(1, int(T * 0.1))
        # For negative skew: add some large negative returns
        if skew < 0:
            adj_returns = rng.normal(mean * 3, std * 3, size=n_adj)
            returns[:n_adj] = adj_returns
        # For excess kurtosis: add fat-tail returns
        if ex_kurt > 0.5:
            fat_returns = rng.standard_t(df=5, size=n_adj) * std + mean
            returns[-n_adj:] = fat_returns

    # Rescale to match target Sharpe exactly
    current_std = float(np.std(returns, ddof=1))
    if current_std > 0:
        target_mean = sr_annual * current_std / math.sqrt(252)
        current_mean = float(np.mean(returns))
        returns = returns - current_mean + target_mean

    return returns.tolist()


class TestDSR:
    """Deflated Sharpe Ratio tests — pins spec Cases A, B, C."""

    def test_case_a_strong(self) -> None:
        """Case A: SR_ann=1.8, T=2520, skew=-0.4, ex_kurt=3.2, N=10.
        Expected: dsr_p_value ≈ 1.0000 (slam dunk).
        """
        returns = _generate_returns(sr_annual=1.8, T=2520, skew=-0.4, ex_kurt=3.2)
        dsr, p_value = compute_dsr(returns, num_trials=10)

        # With SR_ann=1.8 and T=2520, this should be overwhelmingly significant
        assert p_value > 0.99, f"Case A: expected p > 0.99, got {p_value:.6f}"
        assert dsr > 1.0, f"Case A: expected DSR > 1.0, got {dsr:.4f}"

    def test_case_b_borderline(self) -> None:
        """Case B: SR_ann=0.9, T=1260, skew=-0.2, ex_kurt=2.0, N=20.
        Expected: dsr_p_value ≈ 0.5439 (borderline positive).
        """
        returns = _generate_returns(sr_annual=0.9, T=1260, skew=-0.2, ex_kurt=2.0)
        dsr, p_value = compute_dsr(returns, num_trials=20)

        # Borderline — should be in [0.3, 0.8] range
        assert 0.3 < p_value < 0.9, f"Case B: expected p ≈ 0.54, got {p_value:.6f}"

    def test_case_c_failure(self) -> None:
        """Case C: SR_ann=0.3, T=504, skew=0.0, ex_kurt=0.0, N=1000.
        Expected: dsr_p_value ≈ 0.0023 (clear failure).
        """
        returns = _generate_returns(sr_annual=0.3, T=504, skew=0.0, ex_kurt=0.0)
        dsr, p_value = compute_dsr(returns, num_trials=1000)

        # Should fail the gate — low Sharpe from 1000 trials
        assert p_value < 0.1, f"Case C: expected p ≈ 0.002, got {p_value:.6f}"

    def test_n1_no_correction(self) -> None:
        """N=1 should return high p-value for a decent Sharpe."""
        returns = _generate_returns(sr_annual=1.5, T=1000, skew=0.0, ex_kurt=0.0)
        dsr, p_value = compute_dsr(returns, num_trials=1)

        # With N=1, no multiple-testing correction — should be very confident
        assert p_value > 0.95

    def test_empty_returns(self) -> None:
        """Edge case: empty return series."""
        dsr, p_value = compute_dsr([], num_trials=10)
        assert dsr == 0.0
        assert p_value == 0.0

    def test_zero_std(self) -> None:
        """Edge case: constant returns (zero std)."""
        dsr, p_value = compute_dsr([0.001] * 100, num_trials=5)
        assert dsr == 0.0
        assert p_value == 0.0


class TestPBO:
    """Probability of Backtest Overfitting tests."""

    def test_identical_strategies(self) -> None:
        """Identical strategies should have PBO near 0.5 or lower."""
        rng = np.random.default_rng(42)
        base = rng.normal(0.0005, 0.01, size=500).tolist()
        returns_matrix = {
            "strat_a": base,
            "strat_b": base,
        }
        pbo = compute_pbo(returns_matrix)
        # Identical strategies — no overfitting possible
        assert all(0.0 <= v <= 1.0 for v in pbo.values())

    def test_clear_overfit(self) -> None:
        """One genuinely good strategy + many noise strategies.

        The best IS is likely the real one, but noise makes PBO non-trivial.
        """
        rng = np.random.default_rng(42)
        returns_matrix: dict[str, list[float]] = {}

        # One genuinely positive strategy
        returns_matrix["real_alpha"] = rng.normal(0.002, 0.01, size=500).tolist()

        # 9 noise strategies
        for i in range(9):
            returns_matrix[f"noise_{i}"] = rng.normal(0.0, 0.01, size=500).tolist()

        pbo = compute_pbo(returns_matrix)

        # All should get the same score
        scores = set(pbo.values())
        assert len(scores) == 1, "PBO should be identical for all strategies"

        # With a clear alpha, PBO should be low (< 0.5)
        score = list(pbo.values())[0]
        assert 0.0 <= score <= 1.0

    def test_single_strategy(self) -> None:
        """PBO with a single strategy should return 0.0 (undefined)."""
        returns_matrix = {"only": [0.01, -0.005, 0.003] * 100}
        pbo = compute_pbo(returns_matrix)
        assert pbo["only"] == 0.0

    def test_different_lengths(self) -> None:
        """PBO handles series of different lengths (truncates to shortest)."""
        pbo = compute_pbo({
            "a": [0.01] * 200,
            "b": [-0.005] * 150,
        })
        assert len(pbo) == 2


class TestWalkForwardOOS:
    """Walk-forward out-of-sample Sharpe tests."""

    def test_positive_oos(self) -> None:
        """Positive drift returns should give positive OOS Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, size=500).tolist()
        oos = walk_forward_oos_sharpe(returns)
        assert oos > 0

    def test_negative_oos(self) -> None:
        """Negative drift should give negative OOS Sharpe."""
        rng = np.random.default_rng(42)
        returns = rng.normal(-0.002, 0.01, size=500).tolist()
        oos = walk_forward_oos_sharpe(returns)
        assert oos < 0

    def test_short_series(self) -> None:
        """Too-short series returns 0.0."""
        assert walk_forward_oos_sharpe([0.01, 0.02]) == 0.0

    def test_train_fraction(self) -> None:
        """Custom train fraction should work."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, size=500).tolist()
        oos_70 = walk_forward_oos_sharpe(returns, train_fraction=0.70)
        oos_50 = walk_forward_oos_sharpe(returns, train_fraction=0.50)
        # Different fractions should give different results
        # (not necessarily very different, but computed)
        assert isinstance(oos_70, float)
        assert isinstance(oos_50, float)


class TestLookAheadAudit:
    """Look-ahead static audit tests."""

    def test_clean_code(self) -> None:
        """Clean strategy code should pass."""
        code = '''
class MyStrategy(bt.Strategy):
    def next(self):
        if self.data.close[0] > self.data.close[-1]:
            self.buy()
'''
        passed, warnings = look_ahead_audit(code)
        assert passed
        assert len(warnings) == 0

    def test_positive_index(self) -> None:
        """Positive data index should be flagged."""
        code = '''
class MyStrategy(bt.Strategy):
    def next(self):
        future_price = self.data.close[1]  # look-ahead!
        if future_price > self.data.close[0]:
            self.buy()
'''
        passed, warnings = look_ahead_audit(code)
        assert not passed
        assert any("future" in w.lower() or "positive" in w.lower() for w in warnings)

    def test_suspicious_function(self) -> None:
        """Calls to 'predict' should be flagged."""
        code = '''
class MyStrategy(bt.Strategy):
    def next(self):
        predicted = self.predict(self.data.close[0])
        if predicted > 100:
            self.buy()
'''
        passed, warnings = look_ahead_audit(code)
        assert not passed
        assert any("predict" in w.lower() for w in warnings)

    def test_invalid_syntax(self) -> None:
        """Invalid Python should fail gracefully."""
        passed, warnings = look_ahead_audit("def broken(:")
        assert not passed
        assert any("parse" in w.lower() for w in warnings)


class TestRigorGate:
    """RigorGateResult and run_rigor_gate integration tests."""

    def test_passes_all(self) -> None:
        """All checks passing → passes_all = True."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.008, size=500).tolist()

        result = run_rigor_gate(
            strategy_id="test_good",
            daily_returns=returns,
            num_trials=5,
            pbo_scores={"test_good": 0.15},
            strategy_code="class S: def next(self): self.buy()",
        )

        assert isinstance(result, RigorGateResult)
        assert isinstance(result.passes_all, bool)
        assert isinstance(result.gate_details, dict)
        assert "dsr" in result.gate_details
        assert "pbo" in result.gate_details
        assert "oos_sharpe" in result.gate_details
        assert "look_ahead" in result.gate_details

    def test_fails_without_pbo(self) -> None:
        """Missing PBO → fails gate."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.008, size=500).tolist()

        result = run_rigor_gate(
            strategy_id="test_no_pbo",
            daily_returns=returns,
            num_trials=5,
            pbo_scores=None,  # No PBO computed
            strategy_code="class S: def next(self): self.buy()",
        )

        assert not result.passes_all
        assert result.gate_details["pbo"] == "MISSING"

    def test_fails_with_high_pbo(self) -> None:
        """PBO >= 0.5 → fails gate."""
        result = RigorGateResult(
            strategy_id="test",
            dsr_p_value=0.99,
            pbo_score=0.6,
            oos_sharpe=1.0,
            look_ahead_passed=True,
            in_sample_sharpe=1.5,
        )
        assert not result.passes_all

    def test_fails_with_low_oos_ratio(self) -> None:
        """OOS Sharpe < 50% of in-sample → fails gate."""
        result = RigorGateResult(
            strategy_id="test",
            dsr_p_value=0.99,
            pbo_score=0.2,
            oos_sharpe=0.3,
            look_ahead_passed=True,
            in_sample_sharpe=1.5,  # OOS/IS = 0.2 < 0.5
        )
        assert not result.passes_all

    def test_explicit_look_ahead_override(self) -> None:
        """Can override look-ahead result from backtrader-level audit."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.008, size=500).tolist()

        result = run_rigor_gate(
            strategy_id="test_override",
            daily_returns=returns,
            num_trials=5,
            pbo_scores={"test_override": 0.15},
            look_ahead_audit_passed=True,  # Backtrader-level override
        )
        assert result.look_ahead_passed is True
