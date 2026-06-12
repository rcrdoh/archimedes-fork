"""Pytest fixtures for backend unit tests.

Uses the real LocalStrategyProvider pointed at the analytics-engine/strategies/
directory so tests exercise the actual strategy files rather than mocks.
"""

# IMPORTANT: set TESTING env var BEFORE any archimedes imports so that
# the rate limiter (api/limiter.py) reads it at module init time.
import os

os.environ["TESTING"] = "1"

from pathlib import Path

import pytest
from archimedes.services.strategy_provider import LocalStrategyProvider


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the monorepo root (two levels up from backend/)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def strategies_dir(repo_root: Path) -> Path:
    return repo_root / "analytics-engine" / "strategies"


@pytest.fixture(scope="session")
def provider(strategies_dir: Path) -> LocalStrategyProvider:
    return LocalStrategyProvider(strategies_dir)


# ─── Quant-lane synthetic-data fixtures ──────────────────────────────
# Reusable deterministic factories for rigor / optimizer / fusion / backtester
# tests. The underlying functions live in quant_factories.py and can also be
# imported directly when a test needs custom parameters.

from tests import quant_factories  # noqa: E402


@pytest.fixture
def synthetic_returns():
    """Factory fixture: build a daily return series with a target Sharpe.

    Usage:  rets = synthetic_returns(annual_sharpe=1.2, n=504, seed=7)
    """
    return quant_factories.make_returns


@pytest.fixture
def price_panel():
    """Factory fixture: build (close_panel, volume_panel) DataFrames.

    Usage:  close, vol = price_panel(["SPY", "AGG"], n=300, correlation=0.4)
    """
    return quant_factories.make_price_panel


@pytest.fixture
def returns_matrix():
    """Factory fixture: build a {strategy_id: daily returns} matrix.

    Usage:  m = returns_matrix(n_strategies=8, n=504)
    """
    return quant_factories.make_returns_matrix


@pytest.fixture
def regime_shift_returns():
    """Factory fixture: (market, strategy) returns with a mid-series vol regime shift."""
    return quant_factories.make_regime_shift_returns
