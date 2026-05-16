"""Strategy signal evaluator — paper-grounded strategies as live allocation signals.

Each strategy file in analytics-engine/strategies/ contains executable trading
logic encoded as a backtrader Strategy class. This module extracts the core
signal rule from each strategy and evaluates it against live market data,
producing a per-asset target weight.

No backtrader dependency — the signal rules are simple enough to evaluate
directly with numpy/pandas on a price DataFrame.

Design reference:
  - design.md § 4.3.2 (portfolio construction from strategy signals)
  - analytics-engine/strategies/*.py (source of truth for trading logic)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Signal(Enum):
    """Strategy signal for a single asset."""
    LONG = "long"       # Full exposure
    FLAT = "flat"        # No exposure (in cash/USDC)
    SCALED = "scaled"    # Partial exposure (vol-targeting)


@dataclass
class AssetSignal:
    """A single strategy's signal for one asset."""
    strategy_id: str
    strategy_name: str
    asset: str               # e.g. "sSPY"
    signal: Signal
    weight: float            # 0.0 to 1.0 — target portfolio fraction for this asset
    reason: str              # Human-readable explanation


@dataclass
class StrategySignals:
    """All signals from one strategy across all assets."""
    strategy_id: str
    strategy_name: str
    paper_title: str
    signals: list[AssetSignal]

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.signals)


# ─── Price data helper ────────────────────────────────────────────

def _fetch_price_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    """Fetch daily closing prices for a symbol.

    Maps synth symbols to yfinance tickers.
    Returns a pd.Series indexed by date.
    """
    yf_map = {
        "sTSLA": "TSLA",
        "sNVDA": "NVDA",
        "sSPY": "SPY",
        "sGOLD": "GC=F",
        "sOIL": "CL=F",
        "sNKY": "^N225",
        "sBTC": "BTC-USD",
    }
    yf_ticker = yf_map.get(symbol)
    if not yf_ticker:
        return pd.Series(dtype=float)

    try:
        import yfinance as yf
        data = yf.download(yf_ticker, period=period, interval=interval, progress=False)
        if data.empty:
            return pd.Series(dtype=float)
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close.name = symbol
        return close
    except Exception as e:
        logger.warning("Failed to fetch price history for %s: %s", symbol, e)
        return pd.Series(dtype=float)


def _fetch_price_histories(symbols: list[str], period: str = "1y") -> dict[str, pd.Series]:
    """Fetch price histories for multiple symbols."""
    result: dict[str, pd.Series] = {}
    for sym in symbols:
        series = _fetch_price_history(sym, period=period)
        if not series.empty:
            result[sym] = series
    return result


# ─── Signal evaluators — one per paper strategy ────────────────────
#
# Each evaluator is a pure function:
#   (asset_symbol, price_history) → AssetSignal
#
# The logic mirrors the backtrader Strategy class in the corresponding
# analytics-engine/strategies/ file.

def _faber_sma200_signal(
    strategy_id: str,
    asset: str,
    prices: pd.Series,
) -> AssetSignal:
    """Faber 2007 — long when close > SMA200, flat otherwise.

    Mirrors: FaberSMA200.next() in faber_2007_sma200_timing.py
    Rule: price > 200-day SMA → long; else → flat
    """
    sma_period = 200
    if len(prices) < sma_period + 1:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Faber SMA200",
            asset=asset,
            signal=Signal.FLAT,
            weight=0.0,
            reason=f"Insufficient data ({len(prices)} bars, need {sma_period + 1})",
        )

    sma = prices.rolling(sma_period).mean()
    current_price = float(prices.iloc[-1])
    current_sma = float(sma.iloc[-1])

    if current_price > current_sma:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Faber SMA200",
            asset=asset,
            signal=Signal.LONG,
            weight=1.0,
            reason=f"Price {current_price:.2f} > SMA200 {current_sma:.2f} → long",
        )
    else:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Faber SMA200",
            asset=asset,
            signal=Signal.FLAT,
            weight=0.0,
            reason=f"Price {current_price:.2f} ≤ SMA200 {current_sma:.2f} → flat",
        )


def _vol_managed_signal(
    strategy_id: str,
    asset: str,
    prices: pd.Series,
    target_vol_annual: float = 0.15,
) -> AssetSignal:
    """Moreira & Muir 2017 — scale exposure by target_vol / realized_vol.

    Mirrors: VolatilityManagedLong.next() in moreira_muir_2017_volatility_managed.py
    Rule: exposure = min(target_vol / realized_vol_annual, 1.0)
    """
    vol_window = 22
    annualization = 252

    if len(prices) < vol_window + 1:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Vol-Managed",
            asset=asset,
            signal=Signal.SCALED,
            weight=0.5,
            reason=f"Insufficient data ({len(prices)} bars), defaulting to 50%",
        )

    # Compute realized volatility from daily returns
    returns = prices.pct_change().dropna().tail(vol_window)
    if len(returns) < 2:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Vol-Managed",
            asset=asset,
            signal=Signal.SCALED,
            weight=0.5,
            reason="Too few returns, defaulting to 50%",
        )

    realized_vol = float(returns.std() * np.sqrt(annualization))
    if realized_vol <= 0:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="Vol-Managed",
            asset=asset,
            signal=Signal.LONG,
            weight=1.0,
            reason="Zero realized vol → full exposure",
        )

    exposure = min(target_vol_annual / realized_vol, 1.0)
    current_price = float(prices.iloc[-1])

    signal_type = Signal.LONG if exposure >= 0.95 else Signal.SCALED
    return AssetSignal(
        strategy_id=strategy_id,
        strategy_name="Vol-Managed",
        asset=asset,
        signal=signal_type,
        weight=exposure,
        reason=f"Realized vol {realized_vol:.1%}, target {target_vol_annual:.0%} → exposure {exposure:.0%} (price {current_price:.2f})",
    )


def _tsmom_signal(
    strategy_id: str,
    asset: str,
    prices: pd.Series,
) -> AssetSignal:
    """Moskowitz, Ooi, Pedersen 2012 — long when 12-month return positive.

    Mirrors: TimeSeriesMomentum.next() in moskowitz_ooi_pedersen_2012_tsmom.py
    Rule: trailing 252-day return > 0 → long; else → flat
    """
    lookback = 252

    if len(prices) < lookback + 1:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="TSMOM",
            asset=asset,
            signal=Signal.FLAT,
            weight=0.0,
            reason=f"Insufficient data ({len(prices)} bars, need {lookback + 1})",
        )

    current_price = float(prices.iloc[-1])
    past_price = float(prices.iloc[-lookback - 1])
    trailing_return = (current_price / past_price) - 1.0

    if trailing_return > 0:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="TSMOM",
            asset=asset,
            signal=Signal.LONG,
            weight=1.0,
            reason=f"12m return {trailing_return:+.1%} ({past_price:.2f} → {current_price:.2f}) → long",
        )
    else:
        return AssetSignal(
            strategy_id=strategy_id,
            strategy_name="TSMOM",
            asset=asset,
            signal=Signal.FLAT,
            weight=0.0,
            reason=f"12m return {trailing_return:+.1%} ({past_price:.2f} → {current_price:.2f}) → flat",
        )


def _buy_hold_signal(
    strategy_id: str,
    asset: str,
    prices: pd.Series,
) -> AssetSignal:
    """Buy-and-hold baseline — always fully invested."""
    return AssetSignal(
        strategy_id=strategy_id,
        strategy_name="Buy & Hold",
        asset=asset,
        signal=Signal.LONG,
        weight=1.0,
        reason="Buy-and-hold: always fully invested",
    )


# ─── Strategy → evaluator mapping ─────────────────────────────────

# Maps strategy code_hash prefix to its evaluator function.
# In production, this would be auto-discovered from strategy metadata.
_STRATEGY_EVALUATORS: dict[str, callable] = {
    # faber_2007_sma200_timing.py
    "Faber": _faber_sma200_signal,
    "SMA200": _faber_sma200_signal,
    # moreira_muir_2017_volatility_managed.py
    "Volatility": _vol_managed_signal,
    "Vol-Managed": _vol_managed_signal,
    # moskowitz_ooi_pedersen_2012_tsmom.py
    "Time Series Momentum": _tsmom_signal,
    "TSMOM": _tsmom_signal,
    # pipeline_buy_hold.py
    "Buy-and-Hold": _buy_hold_signal,
}


def _get_evaluator(strategy_name: str, strategy_code_path: str | None = None) -> callable:
    """Find the evaluator function for a strategy by title or filename keyword match."""
    name_lower = strategy_name.lower()
    path_lower = (strategy_code_path or "").lower()
    combined = name_lower + " " + path_lower

    for keyword, evaluator in _STRATEGY_EVALUATORS.items():
        if keyword.lower() in combined:
            return evaluator
    # Default: buy-and-hold (always long)
    return _buy_hold_signal


# ─── Public API ────────────────────────────────────────────────────

class StrategySignalEvaluator:
    """Evaluates paper-grounded strategies against live market data.

    This IS the intelligence layer. No heuristics, no regime detector —
    the strategies themselves determine allocations through their
    published signal rules.
    """

    def evaluate_strategies(
        self,
        strategies: list,
        synth_assets: list[str],
        price_histories: dict[str, pd.Series] | None = None,
    ) -> list[StrategySignals]:
        """Evaluate all strategies against live data.

        Args:
            strategies: List of Strategy dataclasses from LocalStrategyProvider
            synth_assets: List of synth symbols to evaluate (e.g. ["sSPY", "sTSLA"])
            price_histories: Optional pre-fetched price data. If None, fetches from yfinance.

        Returns:
            List of StrategySignals, one per strategy.
        """
        # Fetch price histories if not provided
        if price_histories is None:
            price_histories = _fetch_price_histories(synth_assets, period="1y")

        if not price_histories:
            logger.warning("No price histories available — returning empty signals")
            return []

        # Map strategy asset universes to synth symbols
        synth_map = {
            "SPY": "sSPY", "TSLA": "sTSLA", "NVDA": "sNVDA",
            "BTC": "sBTC", "GOLD": "sGOLD", "OIL": "sOIL",
            "NIKKEI": "sNKY", "TREASURY": "sGOLD",
        }

        results: list[StrategySignals] = []

        for strategy in strategies:
            # Map strategy's asset universe to synth symbols (deduplicated)
            strategy_synths: list[str] = []
            seen_synths: set[str] = set()
            for ticker in strategy.asset_universe:
                sym = synth_map.get(ticker)
                if sym and sym in price_histories and sym not in seen_synths:
                    strategy_synths.append(sym)
                    seen_synths.add(sym)

            if not strategy_synths:
                # Fallback: evaluate on all available synths
                strategy_synths = list(price_histories.keys())

            evaluator = _get_evaluator(strategy.paper_title, strategy.strategy_code_path)
            signals: list[AssetSignal] = []

            for asset in strategy_synths:
                prices = price_histories.get(asset)
                if prices is None or prices.empty:
                    continue
                signal = evaluator(strategy.id, asset, prices)
                signals.append(signal)

            if signals:
                results.append(StrategySignals(
                    strategy_id=strategy.id,
                    strategy_name=strategy.paper_title,
                    paper_title=strategy.paper_title,
                    signals=signals,
                ))

                logger.info(
                    "Strategy '%s': %s",
                    strategy.paper_title,
                    ", ".join(f"{s.asset}={s.signal.value}({s.weight:.0%})" for s in signals),
                )

        return results

    def aggregate_signals(
        self,
        all_signals: list[StrategySignals],
        usdc_floor: float = 0.20,
    ) -> dict[str, float]:
        """Aggregate strategy signals into target portfolio weights.

        Each strategy votes on each asset. Votes are averaged across
        strategies, then normalized to (1 - usdc_floor).

        Args:
            all_signals: Output of evaluate_strategies()
            usdc_floor: Minimum USDC allocation (0.0 to 1.0)

        Returns:
            Dict of symbol → target weight (all positive, sum to 1.0)
        """
        if not all_signals:
            return {"USDC": 1.0}

        # Collect votes per asset
        asset_votes: dict[str, list[float]] = {}
        for strat_signals in all_signals:
            for sig in strat_signals.signals:
                asset_votes.setdefault(sig.asset, []).append(sig.weight)

        # Average votes
        raw_weights: dict[str, float] = {}
        for asset, votes in asset_votes.items():
            raw_weights[asset] = sum(votes) / len(votes)

        # Scale to synth budget (1 - usdc_floor)
        synth_budget = 1.0 - usdc_floor
        total_raw = sum(raw_weights.values())

        if total_raw > 0:
            normalized = {k: v / total_raw * synth_budget for k, v in raw_weights.items()}
        else:
            normalized = {}

        # Add USDC floor
        normalized["USDC"] = usdc_floor

        # Round and return
        return {k: round(v, 4) for k, v in sorted(normalized.items())}


# Singleton
strategy_evaluator = StrategySignalEvaluator()
