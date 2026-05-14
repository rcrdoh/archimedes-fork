"""REST API route definitions — wired to chain services.

All endpoints return JSON matching the schemas in schemas.py.
Daniel codes the frontend fetch calls against these paths.
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
from archimedes.services.asset_service import AssetService
from archimedes.services.vault_service import VaultService
from archimedes.services.config_service import ConfigService
from archimedes.chain.oracle_updater import OracleUpdater
from archimedes.chain.executor import chain_executor

# ═══════════════════════════════════════════════════════════════
# Router definitions
# ═══════════════════════════════════════════════════════════════

assets_router = APIRouter(prefix="/api/assets", tags=["assets"])
vaults_router = APIRouter(prefix="/api/vaults", tags=["vaults"])
strategies_router = APIRouter(prefix="/api/strategies", tags=["strategies"])
traces_router = APIRouter(prefix="/api/traces", tags=["traces"])
regime_router = APIRouter(prefix="/api/regime", tags=["regime"])
swap_router = APIRouter(prefix="/api/swap", tags=["swap"])
config_router = APIRouter(prefix="/api/config", tags=["config"])

# Service instances
_asset_svc = AssetService()
_vault_svc = VaultService()
_config_svc = ConfigService()
_oracle = OracleUpdater()


# ── Assets ────────────────────────────────────────────────────


@assets_router.get("/", response_model=AssetListResponse)
async def list_assets():
    """List all assets in the ecosystem with current prices."""
    return await _asset_svc.list_assets()


@assets_router.get("/{symbol}/history", response_model=AssetPriceHistoryResponse)
async def get_asset_price_history(
    symbol: str,
    interval: str = Query("1d", pattern="^(1h|1d|1w)$"),
    limit: int = Query(30, ge=1, le=365),
):
    """Get historical prices for an asset (for charting)."""
    # TODO: Implement with stored price history
    return AssetPriceHistoryResponse(
        symbol=symbol,
        prices=[],
        interval=interval,
    )


# ── Vaults ────────────────────────────────────────────────────


@vaults_router.get("/", response_model=VaultListResponse)
async def list_vaults(
    tier: int | None = Query(None, ge=1, le=2),
    sort_by: str = Query("aum", pattern="^(aum|return_24h|return_7d|sharpe|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List vaults for the marketplace leaderboard."""
    return await _vault_svc.list_vaults(
        tier=tier, sort_by=sort_by, order=order, limit=limit, offset=offset
    )


@vaults_router.get("/{address}", response_model=VaultDetailResponse)
async def get_vault_detail(address: str):
    """Get full vault detail including holdings, performance, traces."""
    detail = await _vault_svc.get_vault_detail(address)
    if detail is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Vault not found")
    return detail


# ── Strategies ────────────────────────────────────────────────


@strategies_router.get("/", response_model=StrategyListResponse)
async def list_strategies(
    status: str | None = Query(None, pattern="^(candidate|validated|live|retired)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List strategies in the library. Dan owns the implementation."""
    # TODO: Dan implements the strategy provider
    return StrategyListResponse(strategies=[], total=0)


@strategies_router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """Get a single strategy. Dan owns the implementation."""
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Strategy not found")


# ── Reasoning Traces ──────────────────────────────────────────


@traces_router.get("/", response_model=TraceListResponse)
async def list_traces(
    vault_address: str | None = None,
    decision_type: str | None = Query(
        None, pattern="^(construction|rebalance|rotation|regime_change|skip)$"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List reasoning traces from on-chain registry."""
    from archimedes.chain.trace_publisher import trace_publisher

    traces: list[TraceResponse] = []

    try:
        total_count = await trace_publisher.get_total_trace_count()

        # Iterate through recent traces
        start = max(1, total_count - offset - limit + 1)
        end = max(1, total_count - offset)

        for trace_id in range(end, start - 1, -1):
            detail = await trace_publisher.get_trace_by_id(trace_id)
            if detail is None:
                continue

            # Filter by vault if specified
            if vault_address and detail["vault"].lower() != vault_address.lower():
                continue

            from datetime import datetime, timezone

            traces.append(
                TraceResponse(
                    id=str(trace_id),
                    vault_address=detail["vault"],
                    decision_type="rebalance",
                    trigger="unknown",
                    timestamp=datetime.fromtimestamp(
                        detail["timestamp"], tz=timezone.utc
                    ).isoformat(),
                    reasoning="On-chain trace",
                    confidence=0.0,
                    trace_hash=detail["trace_hash"],
                    is_verified=True,
                )
            )
    except Exception:
        pass

    return TraceListResponse(traces=traces, total=len(traces))


@traces_router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str):
    """Get a single reasoning trace."""
    from archimedes.chain.trace_publisher import trace_publisher
    from fastapi import HTTPException
    from datetime import datetime, timezone

    try:
        detail = await trace_publisher.get_trace_by_id(int(trace_id))
        if detail is None:
            raise HTTPException(status_code=404, detail="Trace not found")

        return TraceResponse(
            id=trace_id,
            vault_address=detail["vault"],
            decision_type="rebalance",
            trigger="unknown",
            timestamp=datetime.fromtimestamp(
                detail["timestamp"], tz=timezone.utc
            ).isoformat(),
            reasoning="On-chain trace",
            confidence=0.0,
            trace_hash=detail["trace_hash"],
            is_verified=True,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Trace not found")


# ── Regime ────────────────────────────────────────────────────


@regime_router.get("/current", response_model=RegimeResponse)
async def get_current_regime():
    """Get current market regime. Önder owns the classifier."""
    # TODO: Wire to Önder's regime detector
    return RegimeResponse(
        regime="risk_on",
        confidence=0.75,
        timestamp="2026-05-14T00:00:00Z",
        regime_changed=False,
        signals={
            "vix_level": 15.5,
            "sp500_above_ma50": True,
            "sp500_above_ma200": True,
        },
    )


# ── Swap ──────────────────────────────────────────────────────


@swap_router.get("/quote", response_model=SwapQuoteResponse)
async def get_swap_quote(
    token_in: str = Query(..., description="Input token address"),
    token_out: str = Query(..., description="Output token address"),
    amount_in: float = Query(..., gt=0, description="Amount of input token"),
):
    """Preview a swap via AMM router."""
    from archimedes.chain.client import chain_client
    from archimedes.chain.contracts import get_contract_loader

    try:
        loader = get_contract_loader()
        router = loader.amm_router

        # Call getAmountOut on the router (preview)
        amount_out = await router.functions.getAmountOut(
            chain_client.to_checksum(token_in),
            chain_client.to_checksum(token_out),
            int(amount_in * 1e18),  # Assuming 18 decimals for input
        ).call()

        return SwapQuoteResponse(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=amount_out / 1e18,
            price_impact_pct=0.5,  # Estimated
            fee_pct=0.3,
            min_amount_out=amount_out / 1e18 * 0.995,  # 0.5% slippage tolerance
        )
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Quote failed: {str(e)}")


# ── Config ────────────────────────────────────────────────────


@config_router.get("/contracts", response_model=ContractAddressesResponse)
async def get_contract_addresses():
    """Get all deployed contract addresses."""
    return await _config_svc.get_contract_addresses()
