"""Volatility-Managed Portfolios — Moreira & Muir 2017.

Scale exposure inversely to recent realized volatility, holding the
underlying asset always-long. The conservative end of the seed library:
no on/off binary, just a position size that contracts during turbulent
regimes and expands during calm ones.
"""

from __future__ import annotations

import math

import backtrader as bt

PAPER_ARXIV_ID: str | None = None
PAPER_TITLE = "Volatility-Managed Portfolios"
PAPER_AUTHORS: list[str] = ["Alan Moreira", "Tyler Muir"]
PAPER_VENUE = "The Journal of Finance"
PAPER_YEAR = 2017
PAPER_DOI = "10.1111/jofi.12513"
PAPER_CITATION_COUNT = 1100  # Snapshot 2026-05; verify via Semantic Scholar.

# Regime suitability: vol-managed strategies outperform in bear/high-vol regimes.
REGIME_TAG: str = "bear"

METHODOLOGY_SUMMARY = (
    "Stay long the asset; scale exposure inversely to a rolling estimate "
    "of realized volatility so the portfolio targets a fixed annualized "
    "volatility level. Reduces drawdowns and improves Sharpe versus a "
    "constant fully-invested baseline."
)

METHODOLOGY_TEXT = (
    "Moreira and Muir construct managed-volatility portfolios by scaling "
    "the position in a risky asset by c / sigma^2_{t-1}, where sigma_{t-1} "
    "is a rolling realized-volatility estimate (the paper uses one-month "
    "realized variance from daily returns) and c is a normalizing constant "
    "chosen to match the unconditional volatility of the original "
    "portfolio. The paper applies this to the market factor, FF3, FF5, "
    "momentum, and value factors over 1926-2015 and reports unconditional "
    "Sharpe improvements of roughly 50% across factors.\n\n"
    "v1 Archimedes adaptation: 22-day rolling realized volatility from "
    "daily simple returns; exposure_t = min(target_vol_annual / "
    "realized_vol_annual_t, 1.0); rebalance to target each bar. Capping "
    "at 1.0 (no leverage) preserves the spot/RWA constraint in "
    "anti-features.md. The leverage cap means we capture the downside "
    "scaling but only partially the upside boost from levering up during "
    "low-vol regimes; expect realized Sharpe to land between buy-hold and "
    "the paper's fully-leveraged version."
)

PAPER_CLAIMED_SHARPE = 0.60  # Approximate, market-factor 1926-2015 leveraged version.
PAPER_CLAIMED_CAGR = 0.09
PAPER_CLAIMED_MAX_DD = 0.30

ASSET_UNIVERSE: list[str] = ["SPY", "NIKKEI", "GOLD", "TREASURY", "OIL"]
POSITION_SIZING = "inverse_vol"
REBALANCE_FREQUENCY = "daily"
RISK_PROFILES: list[str] = ["conservative", "moderate"]

CURATOR_WALLET: str | None = None
CURATOR_NOTE = (
    "Conservative sleeve. Always-on long exposure with vol-targeting "
    "produces a smoother equity curve that fits the conservative risk "
    "profile's USYC-heavy bias. Useful regime-agnostic counterweight to "
    "the binary on/off Faber filter."
)
EXTRACTION_LLM: str | None = None

STATUS = "live"

# Real backtest metrics — synced from backtest_fixtures.json (2004-01-02 → 2026-04-30, SPY).
# Leverage-capped (≤1.0×) version. Paper's claimed Sharpe is 0.60 (leveraged, multi-asset);
# our single-asset cap-constrained backtest exceeds this on the 2004-2026 SPY sample.
BACKTEST_SHARPE = 0.7689
BACKTEST_CAGR = 0.0950
BACKTEST_MAX_DD = 0.3429
BACKTEST_WIN_RATE = None
BACKTEST_CALMAR = 0.2769
BACKTEST_CORR_SPY = 1.0

_ANNUALIZATION = 252


class VolatilityManagedLong(bt.Strategy):
    """Always-long with exposure scaled inversely to realized volatility."""

    params = (
        ("vol_window", 22),
        ("target_vol_annual", 0.15),
    )

    def _realized_vol_annual(self) -> float | None:
        window = int(self.params.vol_window)
        if len(self) <= window + 1:
            return None
        returns: list[float] = []
        for i in range(1, window + 1):  # start at 1 to exclude current bar (close[0])
            prev = float(self.data.close[-i - 1])
            curr = float(self.data.close[-i])
            if prev > 0:
                returns.append((curr / prev) - 1.0)
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(var) * math.sqrt(_ANNUALIZATION)

    def next(self) -> None:
        realized_vol = self._realized_vol_annual()
        if realized_vol is None or realized_vol <= 0:
            return

        target_vol = float(self.params.target_vol_annual)
        exposure_fraction = min(target_vol / realized_vol, 1.0)

        price = float(self.data.close[0])
        if price <= 0:
            return

        account_value = float(self.broker.getvalue())
        target_notional = account_value * exposure_fraction
        target_size = int(target_notional // price)

        if target_size <= 0:
            if self.position:
                self.close()
            return

        if self.position.size != target_size:
            self.order_target_size(target=target_size)
