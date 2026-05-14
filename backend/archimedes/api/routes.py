"""REST API route definitions — the contract between Chuan's backend and Daniel's frontend.

This file defines the endpoint signatures. Chuan implements the handlers.
Daniel codes the frontend fetch calls against these paths and response schemas.

All endpoints return JSON matching the schemas in schemas.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from archimedes.api.schemas import (
    AssetListResponse,
    AssetPriceHistoryResponse,
    ContractAddressesResponse,
    RegimeResponse,
    StrategyListResponse,
    StrategyResponse,
    SwapQuoteResponse,
    TraceListResponse,
    TraceResponse,
    VaultDetailResponse,
    VaultListResponse,
)

# ═══════════════════════════════════════════════════════════════
# Router definitions — endpoint signatures only
# ═══════════════════════════════════════════════════════════════

assets_router = APIRouter(prefix="/api/assets", tags=["assets"])
vaults_router = APIRouter(prefix="/api/vaults", tags=["vaults"])
strategies_router = APIRouter(prefix="/api/strategies", tags=["strategies"])
traces_router = APIRouter(prefix="/api/traces", tags=["traces"])
regime_router = APIRouter(prefix="/api/regime", tags=["regime"])
swap_router = APIRouter(prefix="/api/swap", tags=["swap"])
config_router = APIRouter(prefix="/api/config", tags=["config"])


# ── Assets ────────────────────────────────────────────────────


@assets_router.get("/", response_model=AssetListResponse)
async def list_assets():
    """List all assets in the ecosystem with current prices.

    Used by: Daniel (asset price display, swap token selector)
    """
    ...


@assets_router.get("/{symbol}/history", response_model=AssetPriceHistoryResponse)
async def get_asset_price_history(
    symbol: str,
    interval: str = Query("1d", regex="^(1h|1d|1w)$"),
    limit: int = Query(30, ge=1, le=365),
):
    """Get historical prices for an asset (for charting).

    Used by: Daniel (price charts on asset detail / vault detail)
    """
    ...


# ── Vaults ────────────────────────────────────────────────────


@vaults_router.get("/", response_model=VaultListResponse)
async def list_vaults(
    tier: int | None = Query(None, ge=1, le=2),
    sort_by: str = Query("aum", regex="^(aum|return_24h|return_7d|sharpe|created_at)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List vaults for the marketplace leaderboard.

    Used by: Daniel (leaderboard page — the marketplace landing page)
    Sort options: aum, return_24h, return_7d, sharpe, created_at
    """
    ...


@vaults_router.get("/{address}", response_model=VaultDetailResponse)
async def get_vault_detail(address: str):
    """Get full vault detail including holdings, performance, traces.

    Used by: Daniel (vault detail page)
    """
    ...


# ── Strategies ────────────────────────────────────────────────


@strategies_router.get("/", response_model=StrategyListResponse)
async def list_strategies(
    status: str | None = Query(None, regex="^(candidate|validated|live|retired)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List strategies in the library.

    Used by: Daniel (strategy explorer — aspirational #11)
    """
    ...


@strategies_router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """Get a single strategy with full backtest results.

    Used by: Daniel (strategy detail page)
    """
    ...


# ── Reasoning Traces ──────────────────────────────────────────


@traces_router.get("/", response_model=TraceListResponse)
async def list_traces(
    vault_address: str | None = None,
    decision_type: str | None = Query(
        None, regex="^(construction|rebalance|rotation|regime_change|skip)$"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List reasoning traces, optionally filtered by vault or decision type.

    Used by: Daniel (reasoning trace viewer — part of vault detail)
    """
    ...


@traces_router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str):
    """Get a single reasoning trace with full detail.

    Used by: Daniel (trace detail view — shows reasoning + on-chain verification)
    """
    ...


# ── Regime ────────────────────────────────────────────────────


@regime_router.get("/current", response_model=RegimeResponse)
async def get_current_regime():
    """Get the current market regime classification.

    Used by: Daniel (regime indicator in header/dashboard)
    """
    ...


# ── Swap ──────────────────────────────────────────────────────


@swap_router.get("/quote", response_model=SwapQuoteResponse)
async def get_swap_quote(
    token_in: str = Query(..., description="Input token address"),
    token_out: str = Query(..., description="Output token address"),
    amount_in: float = Query(..., gt=0, description="Amount of input token"),
):
    """Preview a swap (price, impact, fees) before user signs the tx.

    Used by: Daniel (swap UI — user sees preview before signing with wallet)
    Note: the actual swap is a direct on-chain tx signed by the user's wallet.
    This endpoint just provides the preview calculation.
    """
    ...


# ── Config ────────────────────────────────────────────────────


@config_router.get("/contracts", response_model=ContractAddressesResponse)
async def get_contract_addresses():
    """Get all deployed contract addresses.

    Used by: Daniel (frontend needs addresses to construct on-chain transactions).
    This is the bridge between Chuan's deployments and Daniel's frontend.
    Returns addresses for all contracts + synthetic tokens + pools + vaults.
    """
    ...
