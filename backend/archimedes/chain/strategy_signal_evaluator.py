"""Signal evaluation wrapper for the publisher agent context.

Evaluates a single paper-grounded strategy against live market data by
delegating to the full ``strategy_evaluator`` in
``archimedes.services.strategy_signal_evaluator``.  This module exists so
that ``strategy_runner_publisher`` can ``await evaluate_strategy_signals()``
without pulling the services-level API directly into its critical path.

Design
------
* Single-strategy convenience — the publisher runs *one* strategy per agent,
  so this module wraps the list-oriented ``strategy_evaluator.evaluate_strategies()``
  with a ``strategy_id`` + ``parameters`` interface.
* Sync-to-async bridge — the services-level evaluator is synchronous (it
  downloads price data via ``yfinance``); this module runs it inside
  ``asyncio.to_thread()`` so the publisher's event loop is not blocked.
* Dict return — the publisher's ``_eval_step_payload()`` expects a plain
  ``dict`` for ``signal_summary``, not rich dataclass objects.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from archimedes.services.strategy_provider import default_provider
from archimedes.services.strategy_signal_evaluator import strategy_evaluator

logger = logging.getLogger(__name__)

# Map a strategy's declared asset_universe → synth symbols for the evaluator.
# Must stay in sync with the same table in services.strategy_signal_evaluator.
_SYNTH_MAP: dict[str, str] = {
    "SPY": "sSPY",
    "QQQ": "sQQQ",
    "IWM": "sIWM",
    "TSLA": "sTSLA",
    "NVDA": "sNVDA",
    "BTC": "sBTC",
    "ETH": "sETH",
    "GOLD": "sGOLD",
    "SILVER": "sSI",
    "COPPER": "sHG",
    "OIL": "sOIL",
    "BRENT": "sBRENT",
    "NATGAS": "sNG",
    "NIKKEI": "sNKY",
    "TREASURY": "sBIL",
    "BIL": "sBIL",
    "DAX": "sDAX",
    "FTSE": "sFTSE",
    "CAC": "sCAC",
    "BIST": "sBIST",
    "TUR": "sTUR",
}


def _resolve_synth_assets(strategy: Any) -> list[str]:
    """Convert a strategy's ``asset_universe`` to synth-symbol list.

    Falls back to a reasonable default set when the strategy declares no
    explicit universe.
    """
    raw: list[str] = getattr(strategy, "asset_universe", []) or []
    synths: list[str] = []
    seen: set[str] = set()
    for ticker in raw:
        sym = _SYNTH_MAP.get(ticker)
        if sym and sym not in seen:
            synths.append(sym)
            seen.add(sym)
    return synths or [
        "sSPY", "sQQQ", "sIWM", "sTSLA", "sNVDA",
        "sBTC", "sETH", "sGOLD", "sOIL",
    ]


async def evaluate_strategy_signals(
    strategy_id: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a single strategy and return a signal summary dict.

    Parameters
    ----------
    strategy_id:
        The unique identifier of the strategy to evaluate.
    parameters:
        Optional parameters (``strategy_spec``) passed through to the
        evaluator.  May be *None* when the caller has not loaded the
        full strategy object.

    Returns
    -------
    dict
        A serialisable signal summary suitable for use in the publisher's
        ``signal_summary`` payload field::

            {
                "strategy_id": "...",
                "strategy_name": "...",
                "paper_title": "...",
                "n_signals": 3,
                "signals": [
                    {
                        "asset": "sSPY",
                        "signal": "long",
                        "weight": 0.5,
                        "reason": "..."
                    },
                    ...
                ]
            }

        Returns an empty dict when the strategy cannot be loaded or
        evaluation fails.
    """
    # 1. Load the strategy from the provider.
    provider = default_provider()
    strategy = provider.get_strategy(strategy_id)
    if strategy is None:
        logger.warning("Strategy %s not found — cannot evaluate signals", strategy_id)
        return {}

    # 2. Resolve the asset universe to synth symbols.
    synth_assets = _resolve_synth_assets(strategy)

    # 3. Delegate to the real (synchronous) evaluator in a thread so the
    #    caller's event loop is not blocked by yfinance downloads.
    try:
        results: list[Any] = await asyncio.to_thread(
            strategy_evaluator.evaluate_strategies,
            [strategy],
            synth_assets,
            None,  # price_histories → let evaluator fetch live
            False,  # scan_full_universe
        )
    except Exception as exc:
        logger.error("Signal evaluation failed for %s: %s", strategy_id, exc)
        return {}

    if not results:
        logger.warning("No signals returned for strategy %s", strategy_id)
        return {}

    signal_set = results[0]

    # 4. Serialise to a plain dict.
    signals_data = [
        {
            "asset": s.asset,
            "signal": s.signal.value,
            "weight": s.weight,
            "reason": s.reason,
        }
        for s in getattr(signal_set, "signals", [])
    ]

    return {
        "strategy_id": signal_set.strategy_id,
        "strategy_name": getattr(signal_set, "strategy_name", strategy_id),
        "paper_title": getattr(signal_set, "paper_title", ""),
        "n_signals": len(signals_data),
        "signals": signals_data,
    }
