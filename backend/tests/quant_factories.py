"""Deterministic synthetic-data factories for quant-lane tests.

Pure functions (no pytest dependency) that build reproducible return series,
price panels, and multi-strategy return matrices for hermetic testing of the
rigor evaluator, portfolio optimizer, fusion scorer, and backtester. Every
factory takes a ``seed`` so tests are fully reproducible and never touch the
network, a database, or the clock.

Import the functions directly, or use the pytest fixtures of the same role
registered in ``conftest.py`` (``synthetic_returns``, ``price_panel``,
``returns_matrix``).

Conventions match the production code:
  - daily (per-bar) simple returns, un-annualized
  - 252 trading days/year, 5% annual risk-free rate
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANNUALIZATION = 252
RF_DAILY = 0.05 / ANNUALIZATION


def make_returns(
    n: int = 504,
    *,
    annual_sharpe: float = 1.0,
    annual_vol: float = 0.15,
    seed: int = 42,
    skew: float = 0.0,
) -> list[float]:
    """Build a daily return series with an (approximate) target annualized Sharpe.

    Args:
        n: Number of bars.
        annual_sharpe: Target annualized Sharpe (excess over the 5% rf). The
            realized Sharpe will be close but not exact (finite-sample noise).
        annual_vol: Target annualized volatility.
        seed: RNG seed.
        skew: If non-zero, mixes in a skew-normal-like asymmetry by cubing a
            fraction of the shocks (rough; for tests that need non-normality).

    Returns:
        list[float] of length ``n``.
    """
    rng = np.random.default_rng(seed)
    daily_vol = annual_vol / np.sqrt(ANNUALIZATION)
    # excess daily mean implied by the target annualized Sharpe
    daily_excess_mean = (annual_sharpe / np.sqrt(ANNUALIZATION)) * daily_vol
    shocks = rng.standard_normal(n)
    if skew != 0.0:
        shocks = shocks + skew * (shocks**3 - 3 * shocks) / 6.0
        shocks = (shocks - shocks.mean()) / shocks.std()
    series = RF_DAILY + daily_excess_mean + daily_vol * shocks
    return series.tolist()


def make_price_series(
    n: int = 504,
    *,
    start_price: float = 100.0,
    annual_drift: float = 0.08,
    annual_vol: float = 0.18,
    seed: int = 42,
) -> pd.Series:
    """Geometric price path as a pandas Series with a business-day DatetimeIndex."""
    rng = np.random.default_rng(seed)
    daily_vol = annual_vol / np.sqrt(ANNUALIZATION)
    daily_drift = annual_drift / ANNUALIZATION
    shocks = rng.standard_normal(n)
    log_rets = daily_drift - 0.5 * daily_vol**2 + daily_vol * shocks
    prices = start_price * np.exp(np.cumsum(log_rets))
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.Series(prices, index=idx, name="Close")


def make_price_panel(
    symbols: list[str] | None = None,
    n: int = 504,
    *,
    seed: int = 42,
    correlation: float = 0.3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide close + volume panels for a set of symbols, partially correlated.

    Returns ``(close_panel, volume_panel)`` — both wide DataFrames indexed by a
    business-day DatetimeIndex with one column per symbol, matching the shape
    ``portfolio_backtester._simulate_portfolio`` consumes.

    Args:
        symbols: Column names. Defaults to ["SPY","AGG","GLD","QQQ"].
        n: Number of bars.
        seed: RNG seed.
        correlation: Pairwise return correlation injected via a shared common
            factor (0 = independent, 1 = identical shocks).
    """
    if symbols is None:
        symbols = ["SPY", "AGG", "GLD", "QQQ"]
    rng = np.random.default_rng(seed)
    common = rng.standard_normal(n)
    closes: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    for i, sym in enumerate(symbols):
        idio = rng.standard_normal(n)
        w = np.sqrt(np.clip(correlation, 0.0, 1.0))
        shocks = w * common + np.sqrt(1.0 - w**2) * idio
        daily_vol = (0.12 + 0.04 * i) / np.sqrt(ANNUALIZATION)
        daily_drift = (0.05 + 0.02 * i) / ANNUALIZATION
        log_rets = daily_drift - 0.5 * daily_vol**2 + daily_vol * shocks
        prices = 100.0 * np.exp(np.cumsum(log_rets))
        closes[sym] = prices.tolist()
        # volume loosely anti-correlated with |return| to look realistic
        volumes[sym] = (1_000_000 * (1.0 + 0.3 * np.abs(shocks))).tolist()
    return pd.DataFrame(closes, index=idx), pd.DataFrame(volumes, index=idx)


def make_returns_matrix(
    n_strategies: int = 6,
    n: int = 504,
    *,
    seed: int = 42,
    sharpes: list[float] | None = None,
) -> dict[str, list[float]]:
    """A {strategy_id: daily returns} matrix for PBO / fusion / correlation tests.

    Each strategy gets a distinct target Sharpe (defaults spread linearly) so
    selection and ranking logic is exercised.
    """
    if sharpes is None:
        sharpes = list(np.linspace(-0.2, 1.6, n_strategies))
    out: dict[str, list[float]] = {}
    for i in range(n_strategies):
        out[f"strat_{i}"] = make_returns(n, annual_sharpe=sharpes[i], seed=seed + i)
    return out


def make_regime_shift_returns(
    n: int = 600,
    *,
    seed: int = 42,
    calm_vol: float = 0.10,
    stressed_vol: float = 0.35,
) -> tuple[list[float], list[float]]:
    """A market series with a clear low-vol→high-vol regime shift at the midpoint.

    Returns ``(market_returns, strategy_returns)`` — the strategy is engineered
    to do well in the calm first half and poorly in the stressed second half,
    so regime-conditional metrics have a real signal to detect.
    """
    rng = np.random.default_rng(seed)
    half = n // 2
    calm = rng.normal(0.0008, calm_vol / np.sqrt(ANNUALIZATION), half)
    stressed = rng.normal(-0.0005, stressed_vol / np.sqrt(ANNUALIZATION), n - half)
    market = np.concatenate([calm, stressed])
    # strategy: positive in calm, negative in stressed
    strat_calm = rng.normal(0.0012, 0.008, half)
    strat_stressed = rng.normal(-0.0010, 0.020, n - half)
    strategy = np.concatenate([strat_calm, strat_stressed])
    return market.tolist(), strategy.tolist()
