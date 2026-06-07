"""Unit coverage for portfolio_backtester — the multi-asset weighted
backtester that fills in generated strategies' "Pending Backtest" gap.

Tests the pure functions (simulator + annualized metrics) directly. The
yfinance-fetch + DB-persist paths are exercised via a stubbed price panel
so the suite stays offline + DB-free per pytest.ini's unit profile.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from archimedes.services.portfolio_backtester import (
    ANNUALIZATION,
    DEFAULT_REBALANCE_DAYS,
    _annualized_metrics,
    _correlation_to_benchmark,
    _simulate_portfolio,
    backtest_portfolio,
)


def _flat_panel(symbols: list[str], n_bars: int, daily_drift: float = 0.0005) -> pd.DataFrame:
    """Build a deterministic two-symbol price panel with mild upward drift."""
    idx = pd.bdate_range("2018-01-02", periods=n_bars)
    data = {}
    for i, s in enumerate(symbols):
        # Distinct drifts per symbol so the simulator isn't degenerate.
        prices = 100.0 * np.cumprod(1.0 + (daily_drift + i * 0.0001) * np.ones(n_bars))
        data[s] = pd.Series(prices, index=idx)
    return pd.DataFrame(data)


class TestSimulate:
    def test_two_asset_rebalance_produces_dense_return_series(self) -> None:
        panel = _flat_panel(["SPY", "TLT"], n_bars=500)
        rets, eq = _simulate_portfolio(
            panel,
            {"SPY": 0.6, "TLT": 0.4},
            rebalance_days=21,
            initial_cash=100_000.0,
            tx_cost_bps=10,
        )
        assert len(rets) == 500
        assert len(eq) == 500
        # Equity strictly positive (no nonsense leverage / shorting)
        assert all(v > 0 for v in eq)
        # First bar uses no prior return, so |r_0| ≈ 0
        assert abs(rets[0]) < 1e-6

    def test_negative_weights_clamped_to_zero(self) -> None:
        panel = _flat_panel(["SPY", "TLT"], n_bars=120)
        # SPY has negative weight; should be treated as 0 → 100% TLT
        rets_neg, _ = _simulate_portfolio(
            panel,
            {"SPY": -0.5, "TLT": 1.0},
            rebalance_days=21,
            initial_cash=100_000.0,
            tx_cost_bps=10,
        )
        rets_pure_tlt, _ = _simulate_portfolio(
            panel,
            {"SPY": 0.0, "TLT": 1.0},
            rebalance_days=21,
            initial_cash=100_000.0,
            tx_cost_bps=10,
        )
        # Long-only enforcement: -0.5 SPY is dropped, TLT renormalizes to 1.0
        np.testing.assert_allclose(rets_neg, rets_pure_tlt, atol=1e-12)

    def test_rebalance_charges_turnover_cost(self) -> None:
        panel = _flat_panel(["SPY", "TLT"], n_bars=120, daily_drift=0.001)
        rets_with_cost, eq_with_cost = _simulate_portfolio(
            panel,
            {"SPY": 0.5, "TLT": 0.5},
            rebalance_days=21,
            initial_cash=100_000.0,
            tx_cost_bps=100,  # 1% turnover cost — exaggerated to make signal clear
        )
        rets_no_cost, eq_no_cost = _simulate_portfolio(
            panel,
            {"SPY": 0.5, "TLT": 0.5},
            rebalance_days=21,
            initial_cash=100_000.0,
            tx_cost_bps=0,
        )
        # Cost must drag terminal equity strictly below the zero-cost run.
        assert eq_with_cost[-1] < eq_no_cost[-1]

    def test_all_zero_weights_raises(self) -> None:
        panel = _flat_panel(["SPY", "TLT"], n_bars=120)
        with pytest.raises(ValueError, match="non-positive"):
            _simulate_portfolio(
                panel,
                {"SPY": 0.0, "TLT": 0.0},
                rebalance_days=21,
                initial_cash=100_000.0,
                tx_cost_bps=10,
            )


class TestAnnualizedMetrics:
    def test_constant_returns_give_zero_sharpe(self) -> None:
        # std=0 → Sharpe collapses to 0 by guard; max DD is 0
        rets = [0.0] * 300
        eq = [100_000.0] * 300
        m = _annualized_metrics(rets, eq)
        assert m["sharpe_ratio"] == 0.0
        assert m["max_drawdown"] == 0.0
        assert m["calmar_ratio"] == 0.0

    def test_drift_positive_sharpe(self) -> None:
        # Tiny but consistent positive drift → positive Sharpe + CAGR
        rng = np.random.default_rng(42)
        rets = list(rng.normal(loc=0.0005, scale=0.01, size=2520))  # ~10y daily
        eq = [100_000.0]
        for r in rets:
            eq.append(eq[-1] * (1 + r))
        m = _annualized_metrics(rets, eq[1:])
        assert m["sharpe_ratio"] > 0
        assert m["cagr"] > 0
        # CAGR / max_drawdown >= 0 (max_dd may be very small but not negative)
        assert m["max_drawdown"] >= 0

    def test_too_few_observations_returns_zeros(self) -> None:
        m = _annualized_metrics([], [])
        assert m["sharpe_ratio"] == 0.0
        assert m["cagr"] == 0.0
        m1 = _annualized_metrics([0.01], [100_000])
        assert m1["sharpe_ratio"] == 0.0


class TestCorrelation:
    def test_perfect_correlation(self) -> None:
        a = [0.01, -0.02, 0.005, 0.03]
        assert _correlation_to_benchmark(a, a) == pytest.approx(1.0, abs=1e-9)

    def test_zero_variance_returns_zero(self) -> None:
        flat = [0.0, 0.0, 0.0, 0.0]
        varying = [0.01, -0.01, 0.02, -0.02]
        assert _correlation_to_benchmark(flat, varying) == 0.0

    def test_short_series_returns_zero(self) -> None:
        assert _correlation_to_benchmark([0.01], [0.01]) == 0.0


class TestBacktestPortfolioIntegration:
    """Integration-style test that stubs the fetcher to avoid yfinance hits."""

    def test_end_to_end_with_stubbed_panel(self) -> None:
        panel = _flat_panel(["SPY", "TLT"], n_bars=2520)  # ~10y of daily bars

        with patch(
            "archimedes.services.portfolio_backtester._fetch_price_panel",
            return_value=panel,
        ):
            result, artifact = backtest_portfolio(
                strategy_id="test-strategy-1",
                weights={"SPY": 0.6, "TLT": 0.4},
                start="2016-01-04",
                end="2026-01-02",
                num_trials_for_dsr=6,
                paper_title="Test 60/40",
            )

        # Hard contract checks the strategies_routes wiring depends on
        assert result.strategy_id == "test-strategy-1"
        assert result.sharpe_ratio > 0  # mild drift → positive Sharpe
        assert result.cagr > 0
        assert result.max_drawdown >= 0
        assert result.deflated_sharpe_ratio is not None
        assert result.dsr_p_value is not None
        assert result.out_of_sample_sharpe is not None
        assert result.look_ahead_audit_passed is True
        assert result.backtest_engine == "portfolio-simulator-v1"
        assert result.backtest_code_hash  # non-empty
        assert isinstance(result.backtest_start, date)
        assert isinstance(result.backtest_end, date)
        assert result.num_trials_in_selection == 6

        # Artifact shape mirrors analytics-engine JSON so existing rigor
        # consumers (backtest_repository, mapper) stay generic.
        assert artifact["operations"] == ["SPY", "TLT"]
        assert artifact["assumptions"]["data_source"] == "yfinance"
        assert artifact["assumptions"]["rebalance_days"] == DEFAULT_REBALANCE_DAYS
        assert artifact["assumptions"]["weights"] == {"SPY": 0.6, "TLT": 0.4}
        assert len(artifact["results"]) == 1
        metrics = artifact["results"][0]["metrics"]
        assert len(metrics["daily_returns"]) == 2520
        assert len(metrics["equity_curve"]) == 2520
        assert metrics["num_bars"] == 2520

    def test_no_weights_raises(self) -> None:
        with pytest.raises(ValueError, match="No positive weights"):
            backtest_portfolio(strategy_id="x", weights={})

    def test_all_zero_weights_raises(self) -> None:
        with pytest.raises(ValueError, match="No positive weights"):
            backtest_portfolio(strategy_id="x", weights={"SPY": 0.0, "TLT": 0.0})

    def test_rigor_metrics_match_evaluator(self) -> None:
        """DSR/OOS values returned by the backtester must come from the
        canonical rigor_evaluator — same functions the curated strategies'
        rigor gate uses. This locks in the contract that generated and
        curated strategies are graded on the same scale."""
        from archimedes.services.rigor_evaluator import compute_dsr, compute_oos_sharpe

        panel = _flat_panel(["SPY"], n_bars=1500)

        with patch(
            "archimedes.services.portfolio_backtester._fetch_price_panel",
            return_value=panel,
        ):
            result, artifact = backtest_portfolio(
                strategy_id="rigor-test",
                weights={"SPY": 1.0},
                start="2018-01-02",
                end="2024-01-02",
                num_trials_for_dsr=1,
            )

        daily_rets = artifact["results"][0]["metrics"]["daily_returns"]
        expected_dsr, expected_p = compute_dsr(daily_rets, 1)
        expected_oos = compute_oos_sharpe(daily_rets)

        assert result.deflated_sharpe_ratio == pytest.approx(expected_dsr)
        assert result.dsr_p_value == pytest.approx(expected_p)
        assert result.out_of_sample_sharpe == pytest.approx(expected_oos)


class TestAnnualizationConstant:
    def test_constant_matches_trading_days(self) -> None:
        # Locked at 252 — drift here cascades into every downstream metric.
        assert ANNUALIZATION == 252
