"""Portfolio optimization endpoints — /api/portfolio/*.

Thin HTTP layer over :func:`archimedes.services.portfolio_optimizer.optimize_weights`.
The solvers themselves (MVO / HRP / Black-Litterman / robust) landed via #554 +
#570; this router exposes them to the UI (PortfolioAdvisorPanels' optimizer
selector POSTs here).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

portfolio_router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# UI sends short ids ("bl"); the optimizer service uses full names.
_METHOD_ALIASES = {
    "mvo": "mvo",
    "hrp": "hrp",
    "bl": "black_litterman",
    "black_litterman": "black_litterman",
    "robust": "robust",
}

_PRICE_FETCH_TIMEOUT_S = 45.0
_MIN_HISTORY_BARS = 60  # below this, covariance estimates are too noisy to act on


class OptimizeRequest(BaseModel):
    method: str = Field("mvo", description="One of: mvo, hrp, bl, black_litterman, robust")
    risk_profile: str = Field("moderate", pattern="^(fixed_income|conservative|moderate|aggressive|hyper_risky)$")
    symbols: list[str] | None = Field(
        None,
        description="Synth symbols to allocate across; defaults to the standard scan universe.",
        max_length=50,
    )


@portfolio_router.post("/optimize")
async def optimize_portfolio(req: OptimizeRequest) -> dict:
    """Compute optimal synth-asset weights with the requested optimizer.

    Returns {method, optimizer, risk_profile, usdc_weight, weights, symbols_used,
    history_bars, timestamp}. Weights sum to (1 - usdc_floor) for the profile;
    the USDC floor is reported separately as usdc_weight.

    503 when price history is unavailable (e.g. data provider down) — the UI
    degrades gracefully on that status.
    """
    from archimedes.models.portfolio import RISK_PROFILE_PARAMS, RiskProfile
    from archimedes.services.portfolio_optimizer import optimize_weights
    from archimedes.services.strategy_signal_evaluator import (
        DEFAULT_SCAN_UNIVERSE,
        _fetch_price_histories,
    )

    optimizer = _METHOD_ALIASES.get(req.method.lower())
    if optimizer is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown optimizer '{req.method}'. Expected one of {sorted(_METHOD_ALIASES)}.",
        )

    rp = RiskProfile(req.risk_profile)
    usdc_floor = RISK_PROFILE_PARAMS[rp]["usyc_floor"]
    synth_budget = max(0.0, 1.0 - usdc_floor)

    universe = req.symbols or list(DEFAULT_SCAN_UNIVERSE)
    try:
        price_histories = await asyncio.wait_for(
            asyncio.to_thread(_fetch_price_histories, universe, "2y"),
            timeout=_PRICE_FETCH_TIMEOUT_S,
        )
    except Exception:
        price_histories = {}

    daily_returns: dict[str, list[float]] = {}
    for sym, series in price_histories.items():
        rets = series.pct_change().dropna()
        if len(rets) >= _MIN_HISTORY_BARS:
            daily_returns[sym] = rets.tolist()

    if len(daily_returns) < 2:
        raise HTTPException(
            status_code=503,
            detail="Price history unavailable — optimizer needs ≥2 assets with ≥60 bars of returns.",
        )

    symbols = sorted(daily_returns)
    weights = await asyncio.to_thread(
        optimize_weights,
        symbols,
        daily_returns,
        rp,
        synth_budget,
        optimizer,
    )

    return {
        "method": req.method,
        "optimizer": optimizer,
        "risk_profile": req.risk_profile,
        "usdc_weight": round(usdc_floor, 4),
        "weights": {s: round(w, 6) for s, w in weights.items()},
        "symbols_used": symbols,
        "history_bars": min(len(r) for r in daily_returns.values()),
        "timestamp": datetime.now(UTC).isoformat(),
    }
