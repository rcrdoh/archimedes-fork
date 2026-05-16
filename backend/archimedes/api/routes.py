"""REST API route definitions — wired to chain services.

All endpoints return JSON matching the schemas in schemas.py.
Daniel codes the frontend fetch calls against these paths.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from archimedes.api.schemas import (
    AssetListResponse,
    AssetPriceHistoryResponse,
    ContractAddressesResponse,
    RegimeResponse,
    StrategyListResponse,
    StrategyResponse,
    SwapQuoteResponse,
    PoolListResponse,
    PoolResponse,
    TraceListResponse,
    TraceResponse,
    VaultDetailResponse,
    VaultListResponse,
)
from archimedes.services.asset_service import AssetService
from archimedes.services.vault_service import VaultService
from archimedes.services.config_service import ConfigService
from archimedes.services.strategy_provider import default_provider
from archimedes.services.strategy_architect import default_architect
from archimedes.services.strategy_guardrail import apply_guardrail
from archimedes.services.construction_trace import build_construction_trace
from archimedes.models.strategy import Strategy, StrategyStatus
from archimedes.api.architect_schemas import (
    ConstructionSelectionResponse,
    ConstructionTraceResponse,
    StrategyConstructionRequest,
    StrategyConstructionResponse,
)
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
_strategy_provider = default_provider()
_architect = default_architect()


def _to_strategy_response(s: Strategy) -> StrategyResponse:
    """Map the shared Strategy dataclass to the frontend response shape.

    Backtest fields are left None until Önder's IBacktestEvaluator runs and
    populates a BacktestResult — surfacing them as null is honest (no
    evaluation yet) and matches the "deltas surfaced, not hidden" principle.
    """
    return StrategyResponse(
        id=s.id,
        paper_arxiv_id=s.paper_arxiv_id,
        paper_title=s.paper_title,
        paper_authors=s.paper_authors,
        methodology_summary=s.methodology_summary,
        asset_universe=s.asset_universe,
        position_sizing=s.position_sizing.value,
        rebalance_frequency=s.rebalance_frequency.value,
        status=s.status.value,
    )


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
    """List strategies in the library. Backed by LocalStrategyProvider."""
    status_filter = StrategyStatus(status) if status else None
    strategies = _strategy_provider.list_strategies(status=status_filter)
    total = len(strategies)
    window = strategies[offset : offset + limit]
    return StrategyListResponse(
        strategies=[_to_strategy_response(s) for s in window],
        total=total,
    )


@strategies_router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """Get a single strategy by ID. Backed by LocalStrategyProvider."""
    strategy = _strategy_provider.get_strategy(strategy_id)
    if strategy is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_strategy_response(strategy)


@strategies_router.post("/construct", response_model=StrategyConstructionResponse)
async def construct_strategy(req: StrategyConstructionRequest):
    """Interactive strategy architect — the 'design me a portfolio' path.

    User intent + risk profile → Claude selects/weights paper-grounded
    strategies → deterministic guardrail → hashed reasoning trace. The
    trace_hash is the same artifact Chuan/Marten's ITracePublisher anchors
    on-chain. This is the interactive counterpart to Chuan's autonomous
    IAgentOrchestrator; they share the provider + guardrail.
    """
    # propose() may issue a blocking Claude call — keep the event loop free.
    try:
        proposal = await asyncio.to_thread(
            _architect.propose,
            req.intent,
            req.risk_profile,
            req.capital_usdc,
            req.regime,
        )
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"LLM backend unavailable: {exc}") from exc
    guardrail = apply_guardrail(proposal)
    trace = build_construction_trace(proposal, guardrail)

    by_id = {s.strategy_id: s for s in proposal.selected}
    selected = []
    for sid, weight in sorted(guardrail.strategy_weights.items()):
        sel = by_id.get(sid)
        strat = _strategy_provider.get_strategy(sid)
        selected.append(
            ConstructionSelectionResponse(
                strategy_id=sid,
                paper_title=strat.paper_title if strat else "",
                weight=weight,
                rationale=sel.rationale if sel else "",
                paper_citation=sel.paper_citation if sel else "",
            )
        )

    return StrategyConstructionResponse(
        intent=proposal.intent,
        risk_profile=proposal.risk_profile,
        capital_usdc=proposal.capital_usdc,
        regime=proposal.regime,
        model_id=proposal.model_id,
        selected=selected,
        usyc_weight=guardrail.usyc_weight,
        overall_reasoning=proposal.overall_reasoning,
        risk_notes=proposal.risk_notes,
        guardrail_notes=guardrail.adjustments,
        trace=ConstructionTraceResponse(
            id=trace.id,
            decision_type=trace.decision_type.value,
            trigger=trace.trigger,
            timestamp=trace.timestamp.isoformat(),
            trace_hash=trace.trace_hash,
            arc_tx_hash=trace.arc_tx_hash,
            is_anchored=trace.is_anchored,
        ),
    )


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


def _known_token_meta(address: str) -> tuple[str, int]:
    """Return display symbol + decimals for known USDC/synthetic tokens."""
    from archimedes.chain.client import chain_client

    addr = address.lower()
    if addr == chain_client.settings.usdc_address.lower():
        return "USDC", 6
    for symbol, token_address in chain_client.settings.synth_addresses.items():
        if token_address and addr == token_address.lower():
            return symbol, 18
    return address[:8], 18


async def _token_decimals(address: str) -> int:
    """Fetch token decimals, falling back to known Archimedes conventions."""
    from archimedes.chain.contracts import get_contract_loader

    _, known_decimals = _known_token_meta(address)
    if known_decimals != 18:
        return known_decimals
    try:
        return await get_contract_loader().token(address).functions.decimals().call()
    except Exception:
        return known_decimals


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
        decimals_in = await _token_decimals(token_in)
        decimals_out = await _token_decimals(token_out)
        amount_in_raw = int(amount_in * 10**decimals_in)

        amount_out_raw = await router.functions.getAmountOut(
            chain_client.to_checksum(token_in),
            chain_client.to_checksum(token_out),
            amount_in_raw,
        ).call()

        one_unit_raw = 10**decimals_in
        spot_out_raw = await router.functions.getAmountOut(
            chain_client.to_checksum(token_in),
            chain_client.to_checksum(token_out),
            one_unit_raw,
        ).call()

        amount_out = amount_out_raw / 10**decimals_out
        spot_out = spot_out_raw / 10**decimals_out
        exec_price = amount_out / amount_in if amount_in else 0.0
        price_impact = max(((spot_out - exec_price) / spot_out) * 100, 0.0) if spot_out else 0.0

        return SwapQuoteResponse(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out=amount_out,
            price_impact_pct=price_impact,
            fee_pct=0.3,
            min_amount_out=amount_out * 0.995,
        )
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Quote failed: {str(e)}")


@swap_router.get("/pools", response_model=PoolListResponse)
async def list_swap_pools():
    """List AMM pools and reserves for the exchange UI."""
    from archimedes.chain.contracts import get_contract_loader

    loader = get_contract_loader()
    pools: list[PoolResponse] = []

    try:
        pool_addresses = await loader.amm_router.functions.getAllPools().call()
    except Exception:
        pool_addresses = []

    for pool_address in pool_addresses:
        try:
            pool = loader.amm_pool(pool_address)
            token0, token1, reserve0_raw, reserve1_raw, total_supply_raw, fee_bps = await asyncio.gather(
                pool.functions.token0().call(),
                pool.functions.token1().call(),
                pool.functions.reserve0().call(),
                pool.functions.reserve1().call(),
                pool.functions.totalSupply().call(),
                pool.functions.swapFeeBps().call(),
            )
            symbol0, decimals0 = _known_token_meta(token0)
            symbol1, decimals1 = _known_token_meta(token1)
            reserve0 = reserve0_raw / 10**decimals0
            reserve1 = reserve1_raw / 10**decimals1

            # Hackathon display estimate: USDC side if present, otherwise count the pair conservatively.
            tvl = 0.0
            if symbol0 == "USDC":
                tvl += reserve0 * 2
            elif symbol1 == "USDC":
                tvl += reserve1 * 2

            pools.append(
                PoolResponse(
                    address=pool_address,
                    token0=token0,
                    token1=token1,
                    symbol0=symbol0,
                    symbol1=symbol1,
                    reserve0=reserve0,
                    reserve1=reserve1,
                    tvl_usdc=tvl,
                    fee_pct=fee_bps / 100,
                    apr_pct=None,
                    total_supply=total_supply_raw / 1e18,
                )
            )
        except Exception:
            continue

    return PoolListResponse(pools=pools, total=len(pools))


# ── Config ────────────────────────────────────────────────────


@config_router.get("/contracts", response_model=ContractAddressesResponse)
async def get_contract_addresses():
    """Get all deployed contract addresses."""
    return await _config_svc.get_contract_addresses()
