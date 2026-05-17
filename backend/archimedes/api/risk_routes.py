"""Risk analysis API endpoints.

Dedicated risk router that aggregates strategy backtest stubs and
on-chain vault holdings into portfolio-level risk summaries.
"""

from __future__ import annotations

from fastapi import APIRouter

from archimedes.api.risk_schemas import (
    PortfolioRiskResponse,
    RiskProfileBand,
    RiskProfileBandsResponse,
    StrategyRiskSummary,
)
from archimedes.services.strategy_provider import default_provider

risk_router = APIRouter(prefix="/api/risk", tags=["risk"])

_strategy_provider = default_provider()

# ── Risk Profile Bands ───────────────────────────────────────
# Thresholds used to classify a portfolio into one of four tiers.
# These are the same four levels used by the strategy architect
# (architect_schemas.py RiskProfileLiteral).

RISK_BANDS: list[dict] = [
    {
        "label": "conservative",
        "max_dd": 0.10,
        "target_sharpe": 0.50,
        "max_vol": 0.10,
        "color": "#22C55E",  # green
    },
    {
        "label": "moderate",
        "max_dd": 0.20,
        "target_sharpe": 0.80,
        "max_vol": 0.18,
        "color": "#D4A853",  # amber/gold
    },
    {
        "label": "aggressive",
        "max_dd": 0.35,
        "target_sharpe": 1.00,
        "max_vol": 0.30,
        "color": "#F97316",  # orange
    },
    {
        "label": "hyper_risky",
        "max_dd": 0.60,
        "target_sharpe": 1.20,
        "max_vol": 0.50,
        "color": "#EF4444",  # red
    },
]


def _classify_risk_profile(worst_max_dd: float) -> str:
    """Classify portfolio into a risk tier based on worst strategy max drawdown.

    Picks the lowest band whose max_dd >= worst_max_dd.
    Falls back to hyper_risky if worst_max_dd exceeds all bands.
    """
    for band in RISK_BANDS:
        if worst_max_dd <= band["max_dd"]:
            return band["label"]
    return "hyper_risky"


def _classify_concentration(hhi: float) -> str:
    """Qualitative label for Herfindahl-Hirschman Index."""
    if hhi < 0.15:
        return "diversified"
    if hhi < 0.25:
        return "moderate"
    return "concentrated"


def _derive_risk_level(sharpe: float | None) -> str:
    """Simple risk level from Sharpe ratio."""
    if sharpe is None:
        return "High"
    if sharpe > 1.0:
        return "Low"
    if sharpe > 0.5:
        return "Medium"
    return "High"


# ── Endpoints ────────────────────────────────────────────────


@risk_router.get("/profiles", response_model=RiskProfileBandsResponse)
async def get_risk_profiles():
    """Return the four risk-profile bands with threshold boundaries.

    Used by the frontend to render the risk-profile-vs-actual visualization.
    """
    return RiskProfileBandsResponse(
        bands=[RiskProfileBand(**b) for b in RISK_BANDS],
    )


@risk_router.get("/portfolio", response_model=PortfolioRiskResponse)
async def get_portfolio_risk():
    """Aggregate portfolio-level risk metrics from strategy backtest stubs.

    Computes:
      - Avg Sharpe, worst max drawdown, avg correlation to SPY, best Calmar
      - Per-strategy derived volatility (abs(cagr) / sharpe when both present)
      - Concentration HHI from on-chain vault holdings (if available)
      - Actual risk profile classification based on worst max DD
    """
    strategies = _strategy_provider.list_strategies()

    # ── Per-strategy summaries ───────────────────────────────
    summaries: list[StrategyRiskSummary] = []
    sharpe_vals: list[float] = []
    dd_vals: list[float] = []
    corr_vals: list[float] = []
    calmar_vals: list[float] = []
    vol_vals: list[float] = []

    for s in strategies:
        sharpe = s.stub_sharpe
        max_dd = s.stub_max_dd
        cagr = s.stub_cagr
        calmar = s.stub_calmar
        corr = s.stub_corr_spy

        # Derive annualized volatility: σ ≈ |CAGR| / Sharpe
        # (rough approximation from Sharpe = (r - rf) / σ, assuming rf ≈ 0)
        volatility = None
        if sharpe and sharpe > 0 and cagr is not None:
            volatility = abs(cagr) / sharpe

        if sharpe is not None:
            sharpe_vals.append(sharpe)
        if max_dd is not None:
            dd_vals.append(max_dd)
        if corr is not None:
            corr_vals.append(corr)
        if calmar is not None:
            calmar_vals.append(calmar)
        if volatility is not None:
            vol_vals.append(volatility)

        summaries.append(
            StrategyRiskSummary(
                id=s.id,
                paper_title=s.paper_title,
                status=s.status.value,
                sharpe_ratio=sharpe,
                volatility=volatility,
                max_drawdown=max_dd,
                cagr=cagr,
                win_rate=s.stub_win_rate,
                calmar_ratio=calmar,
                correlation_to_spy=corr,
                risk_level=_derive_risk_level(sharpe),
            )
        )

    # ── Aggregates ───────────────────────────────────────────
    avg_sharpe = sum(sharpe_vals) / len(sharpe_vals) if sharpe_vals else 0.0
    worst_dd = max(dd_vals) if dd_vals else 0.0
    avg_corr = sum(corr_vals) / len(corr_vals) if corr_vals else 0.0
    best_calmar = max(calmar_vals) if calmar_vals else 0.0
    avg_vol = sum(vol_vals) / len(vol_vals) if vol_vals else 0.0

    # ── Concentration HHI (from on-chain vault holdings) ─────
    # Try to read on-chain vault metrics for an AUM-weighted HHI.
    # Fall back to equal-weight across strategies if no vaults.
    hhi = 0.0
    holding_count = 0

    try:
        from archimedes.chain.executor import chain_executor

        vault_addresses = await chain_executor.get_all_vaults()
        if vault_addresses:
            # Use per-vault AUM as weights to compute concentration
            total_aum = 0.0
            vault_aums: list[float] = []

            for vault_addr in vault_addresses:
                try:
                    metrics = await chain_executor.get_vault_metrics(vault_addr)
                    aum = metrics.get("total_aum_usdc", 0.0)
                    if aum > 0:
                        vault_aums.append(aum)
                        total_aum += aum
                except Exception:
                    continue

            if total_aum > 0 and vault_aums:
                holding_count = len(vault_aums)
                weights = [a / total_aum for a in vault_aums]
                hhi = sum(w * w for w in weights)
    except Exception:
        pass

    # Fallback: equal weight across strategies
    if hhi == 0.0 and strategies:
        holding_count = len(strategies)
        hhi = 1.0 / len(strategies)  # equal weight HHI

    return PortfolioRiskResponse(
        strategy_count=len(strategies),
        avg_sharpe=round(avg_sharpe, 3),
        worst_max_dd=round(worst_dd, 4),
        avg_correlation_spy=round(avg_corr, 3),
        best_calmar=round(best_calmar, 3),
        avg_volatility=round(avg_vol, 4),
        concentration_hhi=round(hhi, 4),
        concentration_label=_classify_concentration(hhi),
        holding_count=holding_count,
        actual_risk_profile=_classify_risk_profile(worst_dd),
        strategies=summaries,
    )
