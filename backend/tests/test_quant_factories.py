"""Tests for the quant-lane synthetic-data factories + fixtures.

Verifies the factories are deterministic and produce well-formed data, and
that the registered conftest fixtures expose them. Hermetic; numpy/pandas only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from tests import quant_factories as qf


class TestMakeReturns:
    def test_length_and_determinism(self):
        a = qf.make_returns(300, seed=1)
        b = qf.make_returns(300, seed=1)
        assert len(a) == 300
        assert a == b

    def test_seed_independence(self):
        assert qf.make_returns(300, seed=1) != qf.make_returns(300, seed=2)

    def test_target_sharpe_roughly_hit(self):
        rets = np.asarray(qf.make_returns(5000, annual_sharpe=1.0, annual_vol=0.15, seed=3))
        rf_daily = 0.05 / 252
        realized = (rets.mean() - rf_daily) / rets.std(ddof=1) * np.sqrt(252)
        assert 0.6 < realized < 1.4  # finite-sample tolerance

    def test_skew_changes_distribution(self):
        sym = qf.make_returns(2000, seed=4, skew=0.0)
        skewed = qf.make_returns(2000, seed=4, skew=1.5)
        assert sym != skewed


class TestMakePricePanel:
    def test_shape_and_columns(self):
        close, vol = qf.make_price_panel(["SPY", "AGG", "GLD"], n=250, seed=5)
        assert list(close.columns) == ["SPY", "AGG", "GLD"]
        assert list(vol.columns) == ["SPY", "AGG", "GLD"]
        assert len(close) == 250 == len(vol)
        assert isinstance(close.index, pd.DatetimeIndex)

    def test_prices_positive(self):
        close, _ = qf.make_price_panel(n=200, seed=6)
        assert (close.to_numpy() > 0).all()

    def test_correlation_injection(self):
        close, _ = qf.make_price_panel(["A", "B"], n=2000, seed=7, correlation=0.9)
        rets = close.pct_change().dropna()
        corr = rets["A"].corr(rets["B"])
        assert corr > 0.5  # high injected correlation shows up

    def test_default_symbols(self):
        close, _ = qf.make_price_panel(n=100, seed=8)
        assert list(close.columns) == ["SPY", "AGG", "GLD", "QQQ"]


class TestMakeReturnsMatrix:
    def test_count_and_keys(self):
        m = qf.make_returns_matrix(n_strategies=5, n=300, seed=9)
        assert len(m) == 5
        assert set(m.keys()) == {f"strat_{i}" for i in range(5)}
        assert all(len(v) == 300 for v in m.values())

    def test_custom_sharpes(self):
        m = qf.make_returns_matrix(n_strategies=2, n=300, seed=10, sharpes=[0.0, 2.0])
        assert len(m) == 2


class TestRegimeShiftReturns:
    def test_lengths_match(self):
        market, strat = qf.make_regime_shift_returns(n=400, seed=11)
        assert len(market) == 400 == len(strat)

    def test_second_half_more_volatile(self):
        market, _ = qf.make_regime_shift_returns(n=600, seed=12)
        first = np.std(market[:300])
        second = np.std(market[300:])
        assert second > first  # stressed regime in the back half


class TestFixturesRegistered:
    def test_synthetic_returns_fixture(self, synthetic_returns):
        rets = synthetic_returns(200, annual_sharpe=1.0, seed=1)
        assert len(rets) == 200

    def test_price_panel_fixture(self, price_panel):
        close, vol = price_panel(["X", "Y"], n=120, seed=2)
        assert close.shape == (120, 2)

    def test_returns_matrix_fixture(self, returns_matrix):
        m = returns_matrix(n_strategies=4, n=150)
        assert len(m) == 4

    def test_regime_shift_fixture(self, regime_shift_returns):
        market, strat = regime_shift_returns(n=200)
        assert len(market) == len(strat) == 200
