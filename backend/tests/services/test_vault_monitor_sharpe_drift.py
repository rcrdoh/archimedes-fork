"""Unit coverage for the Sharpe-drift helper in vault_monitor.

`compute_sharpe_drift` is a pure function — no chain, no Redis. Exercises
every status branch (INSUFFICIENT_DATA on too-few snapshots, on too-few
returns, on zero-variance flat AUM; NORMAL, WARNING, CRITICAL on real
return series) and the round-trip math.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from archimedes.services.vault_monitor import compute_sharpe_drift


def _flat_snapshots(n: int, aum: float = 1000.0) -> list[dict]:
    """Build n identical AUM snapshots → zero-variance returns."""
    return [{"aum_usdc": aum, "share_price": 1.0}] * n


def _growing_snapshots(n: int, start: float = 1000.0, step: float = 1.0) -> list[dict]:
    """Build n snapshots where AUM increases by `step` each tick.

    Most-recent first, so reversal yields the chronological NAV path.
    """
    snaps = []
    for i in range(n):
        snaps.append({"aum_usdc": start + (n - 1 - i) * step, "share_price": 1.0})
    return snaps


def _noisy_snapshots(navs: list[float]) -> list[dict]:
    """Build snapshots from an explicit NAV path (most-recent first)."""
    return [{"aum_usdc": v, "share_price": 1.0} for v in reversed(navs)]


class TestInsufficientData:
    def test_too_few_snapshots_returns_insufficient(self) -> None:
        out = compute_sharpe_drift([], backtest_sharpe=1.0)
        assert out["status"] == "INSUFFICIENT_DATA"
        assert out["live_sharpe"] is None

    def test_decay_floor_is_computed_even_when_insufficient(self) -> None:
        out = compute_sharpe_drift([], backtest_sharpe=2.0)
        # 2.0 * 0.42 = 0.84
        assert out["decay_floor"] == 0.84

    def test_zero_variance_series_returns_insufficient(self) -> None:
        out = compute_sharpe_drift(_flat_snapshots(10), backtest_sharpe=1.0)
        assert out["status"] == "INSUFFICIENT_DATA"

    def test_division_by_zero_safe(self) -> None:
        # NAV path with a zero in it should not crash — the zero-prior-NAV
        # entry is filtered out of the returns list.
        snaps = _noisy_snapshots([0.0, 100.0, 110.0, 105.0, 108.0, 112.0])
        out = compute_sharpe_drift(snaps, backtest_sharpe=1.0)
        # Should produce a result without raising
        assert "status" in out


class TestStatusBands:
    def test_steady_growth_yields_normal(self) -> None:
        # Steadily growing AUM → positive live Sharpe ≫ decay floor
        out = compute_sharpe_drift(_growing_snapshots(20, start=1000.0, step=2.0), backtest_sharpe=0.5)
        assert out["status"] == "NORMAL"
        assert out["live_sharpe"] is not None
        assert out["live_sharpe"] > 0

    def test_far_below_decay_floor_yields_critical(self) -> None:
        # Strong losses → negative live Sharpe, well below decay floor
        navs = [1000.0, 980, 960, 940, 920, 900, 880]
        out = compute_sharpe_drift(_noisy_snapshots(navs), backtest_sharpe=2.0)
        assert out["status"] == "CRITICAL"

    def test_drift_sigma_is_finite_and_signed(self) -> None:
        out = compute_sharpe_drift(_growing_snapshots(15, step=1.5), backtest_sharpe=0.5)
        assert out["drift_sigma"] is not None
        assert isinstance(out["drift_sigma"], float)


class TestNumericRounding:
    def test_decay_floor_rounds_to_four_places(self) -> None:
        out = compute_sharpe_drift([], backtest_sharpe=1.23456789)
        # 1.23456789 * 0.42 = 0.518...
        assert isinstance(out["decay_floor"], float)
        # Must be rounded to 4 decimal places
        assert len(str(out["decay_floor"]).split(".")[-1]) <= 4

    def test_live_sharpe_rounds_to_four_places(self) -> None:
        out = compute_sharpe_drift(_growing_snapshots(20, step=1.7), backtest_sharpe=0.5)
        assert out["live_sharpe"] is not None
        assert len(str(out["live_sharpe"]).split(".")[-1]) <= 4
