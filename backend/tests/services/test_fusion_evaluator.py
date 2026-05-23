"""Tests for the fusion evaluator pipeline.

History note: the original test file (PR for issue #128) shipped with several
tautological assertions (``assert X is None or X is not None``) and a
``or True`` short-circuit that made the headline "DSL Faber matches seed"
contract test pass unconditionally. This file's tests have been rewritten to
actually verify the things they name — see ``test_faber_dsl_matches_seed``
docstring for the explicit framing of what is and isn't validated here
(short version: deterministic execution + structural correctness against the
in-tree synthetic data, NOT bit-identity with the analytics-engine's
real-SPY Faber backtest — that contract requires real SPY data and is a
separate piece of work).
"""

from __future__ import annotations

import pytest

from archimedes.services.strategy_dsl import FABER_2007_SPEC, validate_strategy_spec
from archimedes.services.fusion_evaluator import (
    BacktestMetrics,
    FusionEvalResult,
    RigorVerdict,
    apply_rigor_gate,
    evaluate_fusion_spec,
    run_dsl_backtest,
)


class TestFixtureFusionToLibrary:
    """End-to-end: fusion spec → backtest → library upsert (no LLM)."""

    def test_fixture_fusion_to_library(self):
        """A fixture-based fusion spec produces a library entry with real metrics."""
        result = evaluate_fusion_spec(FABER_2007_SPEC)
        assert result.success, f"evaluation failed: {result.error}"
        assert result.backtest is not None

        # Equity curve must come from the per-bar Observer analyzer (not the
        # pre-existing linear-interpolation stub which always produced
        # length=n_bars+1 of equally-spaced values — see equity-curve fix).
        assert len(result.backtest.equity_curve) > 100, (
            f"equity curve suspiciously short: {len(result.backtest.equity_curve)} points"
        )

        # Sharpe / Sortino / Max DD must be real floats (not NaN/inf).
        import math
        assert math.isfinite(result.backtest.sharpe_ratio)
        assert math.isfinite(result.backtest.sortino_ratio)
        assert math.isfinite(result.backtest.max_drawdown)
        assert math.isfinite(result.backtest.cagr)

        # Max drawdown is bounded to a sensible range (0 ≤ MaxDD ≤ 1).
        assert 0.0 <= result.backtest.max_drawdown <= 1.0

        # Rigor verdict is fully populated.
        assert result.rigor is not None
        assert isinstance(result.rigor.passing, bool)

    def test_fusion_result_has_generation_method(self):
        """The result carries enough metadata to identify it as fusion-generated."""
        result = evaluate_fusion_spec(FABER_2007_SPEC)
        assert result.success
        assert result.spec.source_arxiv_ids == ["0706.1497"]


class TestFaberDslMatchesSeed:
    """The DSL-interpreted Faber strategy reproduces deterministic results.

    **Scope of this test:** the DSL pipeline executes end-to-end and produces
    deterministic, reproducible metrics on the in-tree synthetic data path.

    **Out of scope (deferred):** bit-identity with the analytics-engine's
    hand-written Faber backtest on real 2004-2026 SPY data. That contract
    requires:
      (a) shipping a real SPY OHLCV fixture (~330 KB of CSV), AND
      (b) careful semantic alignment between the DSL's interpretation of
          ``rebalance_frequency=monthly`` / ``position_sizing=full_invested_when_in_market``
          and the analytics-engine seed strategy's specific implementation
          choices around dividend handling, transaction-cost timing, and
          end-of-bar vs next-bar execution.

    The canonical Faber Sharpe is ``0.6335`` per ``analytics-engine/
    strategies/backtest_fixtures.json`` (key ``faber_2007_sma200_timing``).
    Achieving DSL Faber within ±0.10 of that figure is tracked as a
    separate issue; this test guards the substrate.
    """

    def test_faber_dsl_runs_end_to_end_deterministically(self):
        """Two consecutive runs of the DSL Faber on the same synthetic data
        must produce identical Sharpe / CAGR / Max DD — the DSL + interpreter
        is a deterministic pipeline.
        """
        r1 = evaluate_fusion_spec(FABER_2007_SPEC)
        r2 = evaluate_fusion_spec(FABER_2007_SPEC)
        assert r1.success and r2.success

        # Per-bar equity capture means the Sharpe is computed from real
        # broker values, not from a linear interpolation — making this
        # determinism check substantively stronger than the pre-fix version.
        assert r1.backtest.sharpe_ratio == r2.backtest.sharpe_ratio
        assert r1.backtest.cagr == r2.backtest.cagr
        assert r1.backtest.max_drawdown == r2.backtest.max_drawdown
        assert r1.backtest.equity_curve == r2.backtest.equity_curve

    def test_faber_dsl_produces_structurally_correct_backtest(self):
        """The DSL Faber produces a backtest that's structurally consistent —
        the SMA-200 filter actually fires (some trades happen), the equity
        curve has the right shape (one point per bar after warmup), and the
        derived metrics are arithmetically self-consistent.
        """
        result = evaluate_fusion_spec(FABER_2007_SPEC)
        assert result.success
        bt = result.backtest

        # Equity curve has the right shape — 22 years × ~252 trading days
        # minus 200 warmup bars ≈ 5350+ bars. (The synthetic data feed
        # spans 2004-01-02 to 2026-04-30; without an SMA-200 warmup this
        # would be ~5560 daily bars.)
        assert 4000 < len(bt.equity_curve) < 7000, (
            f"equity curve length suspicious: {len(bt.equity_curve)}"
        )

        # Calmar identity check: calmar = cagr / max_dd (when max_dd > 0).
        if bt.max_drawdown > 0.001:
            expected_calmar = bt.cagr / bt.max_drawdown
            # Allow tiny float drift from the round(.., 4) calls.
            assert abs(bt.calmar_ratio - expected_calmar) < 0.001, (
                f"Calmar identity violated: {bt.calmar_ratio} vs {expected_calmar}"
            )


class TestRigorGateAppliesToDslOutput:
    """Rigor gate must run on DSL-interpreted strategies and surface honest
    rigor results — every field is either a real computed value or
    explicitly ``None`` (NOT 0.0 as a misleading placeholder).
    """

    def test_rigor_gate_applies_to_dsl_output(self):
        result = evaluate_fusion_spec(FABER_2007_SPEC)
        assert result.success
        assert result.rigor is not None

        rigor = result.rigor

        # DSR is a real computed float (positive for trending strategies,
        # could be negative for losing ones — both are valid outcomes that
        # the rigor gate's pass/fail logic responds to).
        import math
        assert rigor.dsr is not None, "DSR must be computed for DSL output"
        assert math.isfinite(rigor.dsr)
        assert rigor.dsr_p_value is not None
        assert 0.0 <= rigor.dsr_p_value <= 1.0

        # PBO for a single strategy is honestly None (not 0.0 — that was the
        # pre-fix misleading default that made every fusion strategy look
        # like it had passed the overfitting test it never ran).
        assert rigor.pbo_score is None, (
            "PBO must be None for single-strategy DSL output. Setting it to "
            "0.0 was misleading; real CSCV PBO needs a parameter-variant grid."
        )

        # OOS Sharpe is a real computed float.
        assert rigor.oos_sharpe is not None
        assert math.isfinite(rigor.oos_sharpe)

        # Look-ahead is guaranteed by DSL design (rejected at validation).
        assert rigor.look_ahead_clean is True

        # The gate produces a deterministic boolean verdict.
        assert isinstance(rigor.passing, bool)
        assert rigor.num_trials > 0


class TestInvalidSpecHandling:
    """Invalid specs must fail gracefully."""

    def test_invalid_spec_returns_error(self):
        bad_spec = {"name": "broken"}
        result = evaluate_fusion_spec(bad_spec)
        assert not result.success
        assert result.error is not None
        assert "missing required" in result.error.lower() or "invalid" in result.error.lower()

    def test_look_ahead_unsafe_returns_error(self):
        unsafe = {**FABER_2007_SPEC, "look_ahead_safe": False}
        result = evaluate_fusion_spec(unsafe)
        assert not result.success
        assert "look_ahead_safe" in result.error.lower()
