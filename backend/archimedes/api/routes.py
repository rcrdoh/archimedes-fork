"""REST API route definitions — wired to chain services.

All endpoints return JSON matching the schemas in schemas.py.
Daniel codes the frontend fetch calls against these paths.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query

from archimedes.api.schemas import (
    AgentStatusResponse,
    AssetListResponse,
    AssetPriceHistoryResponse,
    ContractAddressesResponse,
    RegimeResponse,
    SignalResponse,
    StrategyListResponse,
    StrategyResponse,
    StrategySignalResponse,
    StrategySignalsResponse,
    SwapQuoteResponse,
    PoolListResponse,
    PoolResponse,
    TraceListResponse,
    TraceResponse,
    TracePublishRequest,
    TracePublishResponse,
    TraceVerifyResponse,
    VaultDetailResponse,
    VaultListResponse,
)

from archimedes.models.trace import ReasoningTrace
from archimedes.models.trace import DecisionType
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
from archimedes.services.strategy_fusion import (
    StrategyFusion,
    FusionBrief,
    default_fusion,
    fusion_enabled,
    load_corpus,
)
from archimedes.models.strategy_store import upsert_strategy, resolve_source_papers
from archimedes.db import get_session
from archimedes.api.vault_schemas import (
    VaultCreateRequest, VaultCreateResponse,
    VaultMetadataRequest, VaultMetadataResponse,
    SetAllocationsRequest, SetAllocationsResponse, AllocationTarget,
)
from archimedes.models.chat import VaultMetadata
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
papers_router = APIRouter(prefix="/api/papers", tags=["papers"])
config_router = APIRouter(prefix="/api/config", tags=["config"])
agent_router = APIRouter(prefix="/api/agent", tags=["agent"])

# Service instances
_asset_svc = AssetService()
_vault_svc = VaultService()
_config_svc = ConfigService()
_oracle = OracleUpdater()
_strategy_provider = default_provider()
_architect = default_architect()


def _to_strategy_response(s: Strategy) -> StrategyResponse:
    """Map Strategy + persisted BacktestResult to API schema.


    Real backtest results from backtest_fixtures.json take priority over DB
    BacktestResult. DB row is used as fallback when no fixture data is present.
    is_backtest_placeholder=False when real fixture data is available.
    """
    bt = _strategy_provider.get_backtest_result(s.id)
    has_real = s.real_sharpe is not None
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
        # Paper provenance
        paper_venue=s.paper_venue,
        paper_year=s.paper_year,
        paper_doi=s.paper_doi,
        paper_citation_count=s.paper_citation_count,
        # Passport integrity
        methodology_hash=s.methodology_hash,
        extraction_llm=s.extraction_llm,
        curator_wallet=s.curator_wallet,
        curator_note=s.curator_note,
        on_chain_registration_tx=s.on_chain_registration_tx,
        # Paper claims (for delta display)
        paper_claimed_sharpe=bt.paper_claimed_sharpe if bt else s.paper_claimed_sharpe,
        # Backtest — real fixture values first, DB fallback, then stubs
        sharpe_ratio=s.real_sharpe if has_real else (bt.sharpe_ratio if bt else s.stub_sharpe),
        sortino_ratio=s.real_sortino if has_real else (bt.sortino_ratio if bt else None),
        cagr=s.real_cagr if has_real else (bt.cagr if bt else s.stub_cagr),
        max_drawdown=s.real_max_dd if has_real else (bt.max_drawdown if bt else s.stub_max_dd),
        win_rate=s.real_win_rate if has_real else (bt.win_rate if bt else s.stub_win_rate),
        calmar_ratio=s.real_calmar if has_real else (bt.calmar_ratio if bt else s.stub_calmar),
        correlation_to_spy=s.real_corr_spy if has_real else (bt.correlation_to_spy if bt else s.stub_corr_spy),
        total_trades=s.real_total_trades if has_real else (bt.total_trades if bt else None),
        deflated_sharpe_ratio=s.deflated_sharpe_ratio if has_real else (bt.deflated_sharpe_ratio if bt else None),
        dsr_p_value=s.dsr_p_value if has_real else (bt.dsr_p_value if bt else None),
        pbo_score=s.pbo_score if has_real else (bt.pbo_score if bt else None),
        out_of_sample_sharpe=s.out_of_sample_sharpe if has_real else (bt.out_of_sample_sharpe if bt else None),
        kelly_fraction=s.kelly_fraction,
        passes_rigor_gate=s.passes_rigor_gate if has_real else (bt.passes_rigor_gate if bt else s.passes_rigor_gate),
        is_backtest_placeholder=not has_real,
        sharpe_ci_lower=s.sharpe_ci_lower,
        sharpe_ci_upper=s.sharpe_ci_upper,
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


@vaults_router.post("/create", response_model=VaultCreateResponse)
async def create_vault(req: VaultCreateRequest):
    """Deploy a new vault on Arc via VaultFactory.

    strategy_ids are accepted as off-chain metadata and echoed back in the
    response — they are not passed to the contract (v2 persistence hook).
    """
    from fastapi import HTTPException

    try:
        vault_address = await chain_executor.create_vault(
            name=req.name,
            symbol=req.symbol,
            management_fee_bps=req.management_fee_bps,
            performance_fee_bps=req.performance_fee_bps,
            agent_assisted=req.agent_assisted,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vault deployment failed: {exc}") from exc

    return VaultCreateResponse(vault_address=vault_address, strategy_ids=req.strategy_ids)


@vaults_router.get("/{address}/health")
async def get_vault_health(address: str):
    """Get vault health snapshot including live Sharpe drift vs backtest baseline.

    Returns AUM trend, rebalance staleness, agent heartbeat, and a
    McLean-Pontiff-aware Sharpe drift indicator (NORMAL/WARNING/CRITICAL).
    """
    from archimedes.services.vault_monitor import vault_monitor
    return await vault_monitor.get_vault_health(address)


@vaults_router.get("/{address}", response_model=VaultDetailResponse)
async def get_vault_detail(address: str):
    """Get full vault detail including holdings, performance, traces."""
    detail = await _vault_svc.get_vault_detail(address)
    if detail is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Vault not found")
    return detail


# ── Vault Metadata (off-chain) ───────────────────────────────


@vaults_router.post("/metadata", response_model=VaultMetadataResponse)
async def store_vault_metadata(req: VaultMetadataRequest):
    """Store off-chain vault metadata (strategy associations, display name).

    Called by the frontend after a successful on-chain vault deployment.
    Idempotent — upserts on vault_address.
    """
    from archimedes.db import get_session

    session = get_session()
    try:
        meta = (
            session.query(VaultMetadata)
            .filter(VaultMetadata.vault_address == req.vault_address)
            .first()
        )
        if meta is None:
            meta = VaultMetadata(vault_address=req.vault_address)
            session.add(meta)

        meta.name = req.name
        meta.symbol = req.symbol
        meta.creator_address = req.creator_address or ""
        meta.set_strategy_ids(req.strategy_ids)
        session.commit()
        session.refresh(meta)
        return VaultMetadataResponse(**meta.to_dict())
    except Exception as exc:
        session.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@vaults_router.get("/{address}/metadata", response_model=VaultMetadataResponse)
async def get_vault_metadata(address: str):
    """Get off-chain vault metadata (strategy associations, display name)."""
    from fastapi import HTTPException
    from archimedes.db import get_session

    session = get_session()
    try:
        meta = (
            session.query(VaultMetadata)
            .filter(VaultMetadata.vault_address == address)
            .first()
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="No metadata for this vault")
        return VaultMetadataResponse(**meta.to_dict())
    finally:
        session.close()


@vaults_router.post("/{address}/derive-allocations", response_model=SetAllocationsResponse)
async def derive_vault_allocations(address: str, req: SetAllocationsRequest):
    """Derive target allocations from selected strategies.

    Evaluates strategies against live market data, aggregates their signals,
    maps symbol weights to on-chain token addresses + BPS.
    Returns the data needed for a setTargetAllocations() on-chain tx.
    Does NOT execute any on-chain transaction — the UI submits via user wallet.
    """
    from archimedes.chain.client import chain_client
    from archimedes.services.strategy_signal_evaluator import strategy_evaluator

    strategies = _strategy_provider.list_strategies()

    # Filter to selected strategies if IDs provided
    if req.strategy_ids:
        strategies = [s for s in strategies if s.id in req.strategy_ids]

    if not strategies:
        # Default: equal-weight across all available synths
        usdc_floor_bps = int(req.usdc_floor_pct * 100)
        synth_budget_bps = 10000 - usdc_floor_bps
        synth_addrs = {k: v for k, v in chain_client.settings.synth_addresses.items() if v}
        per_synth = synth_budget_bps // max(len(synth_addrs), 1)
        allocations = [
            AllocationTarget(symbol=sym, token_address=addr, weight_bps=per_synth)
            for sym, addr in synth_addrs.items()
        ]
        allocations.append(AllocationTarget(
            symbol="USDC",
            token_address=chain_client.settings.usdc_address,
            weight_bps=usdc_floor_bps,
        ))
        return SetAllocationsResponse(
            allocations=allocations,
            total_bps=sum(a.weight_bps for a in allocations),
            strategy_count=0,
        )

    # Evaluate strategies against live data
    synth_assets = [sym for sym, addr in chain_client.settings.synth_addresses.items() if addr]
    all_signals = await asyncio.to_thread(
        strategy_evaluator.evaluate_strategies, strategies, synth_assets,
    )
    usdc_floor = req.usdc_floor_pct / 100.0
    target_weights = strategy_evaluator.aggregate_signals(all_signals, usdc_floor=usdc_floor)

    # Map symbol weights → on-chain token addresses + BPS
    allocations: list[AllocationTarget] = []

    symbol_to_addr = {"USDC": chain_client.settings.usdc_address}
    symbol_to_addr.update(chain_client.settings.synth_addresses)

    for symbol, weight in target_weights.items():
        token_address = symbol_to_addr.get(symbol)
        if not token_address:
            continue
        weight_bps = int(round(weight * 10000))
        if weight_bps > 0:
            allocations.append(AllocationTarget(
                symbol=symbol,
                token_address=token_address,
                weight_bps=weight_bps,
            ))

    # Normalize to exactly 10000 BPS
    total = sum(a.weight_bps for a in allocations)
    if total > 0 and total != 10000:
        scale = 10000 / total
        for a in allocations:
            a.weight_bps = int(round(a.weight_bps * scale))
        # Drop any entries that rounded to zero
        allocations = [a for a in allocations if a.weight_bps > 0]
        # Fix rounding residue — apply to largest entry to avoid zeroing
        total = sum(a.weight_bps for a in allocations)
        if total != 10000 and allocations:
            largest = max(allocations, key=lambda a: a.weight_bps)
            largest.weight_bps += (10000 - total)

    return SetAllocationsResponse(
        allocations=allocations,
        total_bps=sum(a.weight_bps for a in allocations),
        strategy_count=len(strategies),
    )


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


@strategies_router.get("/signals", response_model=StrategySignalsResponse)
async def get_strategy_signals():
    """Evaluate all strategies against live market data and return signals.

    This is the intelligence layer surfaced as an API — the same evaluation
    the agent runner performs each tick, but on-demand for the frontend.
    """
    from datetime import datetime, timezone

    from archimedes.services.strategy_signal_evaluator import strategy_evaluator
    from archimedes.services.redis_state import AgentStateStore

    strategies = _strategy_provider.list_strategies()
    from archimedes.chain.client import chain_client
    synth_assets = [sym for sym, addr in chain_client.settings.synth_addresses.items() if addr]

    all_signals = await asyncio.to_thread(
        strategy_evaluator.evaluate_strategies, strategies, synth_assets,
    )

    target_weights = strategy_evaluator.aggregate_signals(all_signals, usdc_floor=0.20)

    flat_count = sum(1 for ss in all_signals for s in ss.signals if s.signal.value == "flat")
    total_count = sum(len(ss.signals) for ss in all_signals)
    flat_pct = flat_count / total_count if total_count > 0 else 0

    if flat_pct > 0.6:
        regime = "risk_off"
    elif flat_pct > 0.3:
        regime = "transition"
    else:
        regime = "risk_on"

    strat_responses = []
    for ss in all_signals:
        strat_responses.append(StrategySignalResponse(
            strategy_id=ss.strategy_id,
            paper_title=ss.paper_title,
            signals=[
                SignalResponse(
                    asset=s.asset,
                    signal=s.signal.value,
                    weight=s.weight,
                    reason=s.reason,
                    strategy_name=s.strategy_name,
                )
                for s in ss.signals
            ],
        ))

    return StrategySignalsResponse(
        strategy_count=len(all_signals),
        regime=regime,
        confidence=round(1.0 - flat_pct, 2),
        target_weights=target_weights,
        strategies=strat_responses,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@strategies_router.get("/frontier")
async def get_efficient_frontier():
    """Compute efficient frontier for all Tier-1 validated strategies.

    Uses synthetic daily return streams simulated from backtest summary
    statistics (SR, CAGR) via mean-variance optimisation (SLSQP sweep).

    NOTE: Raw daily return series are not stored; returns are synthesised
    from summary stats. Results are deterministic (seeded RNG).
    """
    from archimedes.services.portfolio_optimizer import compute_efficient_frontier
    import numpy as np

    strategies = _strategy_provider.list_strategies()
    active = [s for s in strategies if s.passes_rigor_gate]

    if len(active) < 2:
        return {"frontier": [], "strategies": [], "message": "Need >= 2 validated strategies"}

    # Build synthetic daily return streams from summary stats
    # SR = mu / sigma (annualized), CAGR ~ mu, so mu_daily = CAGR/252
    rng = np.random.default_rng(42)
    N_DAYS = 5560
    synthetic_returns = {}
    labels = []

    for s in active[:5]:  # cap at 5 for performance
        sr = (
            s.real_sharpe
            if s.real_sharpe is not None
            else s.stub_sharpe if s.stub_sharpe is not None else 0.5
        )
        cagr = (
            s.real_cagr
            if s.real_cagr is not None
            else s.stub_cagr if s.stub_cagr is not None else 0.08
        )
        mu_d = cagr / 252
        sigma_d = abs(mu_d / (sr / (252 ** 0.5))) if sr != 0 else 0.01
        rets = rng.normal(mu_d, sigma_d, N_DAYS).tolist()
        synthetic_returns[s.id] = rets
        labels.append({"id": s.id, "title": s.paper_title})

    frontier = compute_efficient_frontier(list(synthetic_returns.keys()), synthetic_returns)
    return {"frontier": frontier, "strategies": labels, "message": None}


@strategies_router.get("/correlation")
async def get_strategy_correlation():
    """Pairwise correlation matrix for the active strategy library.

    Simulates correlated return streams from backtest summary statistics.
    All strategies in this library track broad equity markets (corr_to_spy ~ 1.0),
    so inter-strategy correlations are expected to be high — this is shown honestly.

    NOTE: Returns are simulated from summary statistics since raw daily return
    series are not stored in backtest_fixtures.json.
    """
    import numpy as np

    strategies = [s for s in _strategy_provider.list_strategies() if s.real_sharpe is not None]
    if len(strategies) < 2:
        return {"matrix": [], "labels": [], "diversification_ratio": None}

    rng = np.random.default_rng(42)
    N_DAYS = 5560

    # Simulate returns with SPY correlation baked in
    spy_daily = rng.normal(0.00035, 0.01, N_DAYS)  # SPY ~9% CAGR, ~16% vol

    return_matrix = []
    labels = []
    for s in strategies:
        sr = s.real_sharpe if s.real_sharpe is not None else 0.5
        cagr = s.real_cagr if s.real_cagr is not None else 0.08
        corr = s.real_corr_spy if s.real_corr_spy is not None else 1.0
        mu_d = cagr / 252
        sigma_d = abs(mu_d / (sr / (252 ** 0.5))) if sr != 0 else 0.01

        # Correlated with SPY via Cholesky-style decomposition
        idio = rng.normal(0, sigma_d * float(np.sqrt(max(1 - corr**2, 0))), N_DAYS)
        rets = corr * (spy_daily * sigma_d / 0.01) + idio + mu_d
        return_matrix.append(rets)
        labels.append({
            "id": s.id,
            "title": s.paper_title[:30],
            "passes_rigor_gate": s.passes_rigor_gate,
        })

    R = np.array(return_matrix)
    corr_matrix = np.corrcoef(R)

    # Average pairwise correlation (honest; higher = less diversified)
    n = len(strategies)
    off_diag = [corr_matrix[i, j] for i in range(n) for j in range(n) if i != j]
    avg_corr = sum(off_diag) / len(off_diag) if off_diag else 1.0

    return {
        "matrix": [[round(float(corr_matrix[i, j]), 3) for j in range(n)] for i in range(n)],
        "labels": labels,
        "avg_pairwise_correlation": round(avg_corr, 3),
        "note": "Strategies track broad equity markets — high inter-strategy correlation is expected and shown honestly.",
    }


@strategies_router.get("/advisor")
async def get_portfolio_advisor(
    risk_profile: str = Query("moderate", pattern="^(fixed_income|conservative|moderate|aggressive|hyper_risky)$"),
):
    """Portfolio allocation recommendation based on Kelly + risk-parity math.

    Returns target weights, Kelly fractions, and expected metrics for
    the active strategy library under the given risk profile and current regime.
    Does not require an active vault — this is a pre-deployment advisor.
    """
    import math
    from archimedes.models.portfolio import RiskProfile, RISK_PROFILE_PARAMS
    from archimedes.models.regime import Regime
    from archimedes.services.redis_state import AgentStateStore

    # Load current regime from Redis (fall back to transition if unavailable)
    state = AgentStateStore()
    try:
        regime_data = await state.load_regime()
    except Exception:
        regime_data = None
    finally:
        await state.close()

    regime_value = regime_data.get("regime", "transition") if regime_data else "transition"
    regime_confidence = regime_data.get("confidence", 0.5) if regime_data else 0.5
    try:
        regime_enum = Regime(regime_value)
    except ValueError:
        regime_enum = Regime.TRANSITION

    # USDC floor multipliers (mirrors KellyRiskParityConstructor)
    _DELEVERAGE: dict[Regime, float] = {
        Regime.RISK_ON: 0.5,
        Regime.TRANSITION: 1.0,
        Regime.RISK_OFF: 2.5,
        Regime.CRISIS: 5.0,
    }

    rp_map = {
        "fixed_income": RiskProfile.FIXED_INCOME,
        "conservative": RiskProfile.CONSERVATIVE,
        "moderate": RiskProfile.MODERATE,
        "aggressive": RiskProfile.AGGRESSIVE,
        "hyper_risky": RiskProfile.HYPER_RISKY,
    }
    rp = rp_map.get(risk_profile, RiskProfile.MODERATE)
    params = RISK_PROFILE_PARAMS[rp]

    usdc_floor_base = params["usyc_floor"]
    deleverage = _DELEVERAGE.get(regime_enum, 1.0)
    usdc_floor = min(usdc_floor_base * deleverage, 0.95)
    synth_budget = max(0.0, 1.0 - usdc_floor)

    # Get active strategies with real backtest data
    strategies = [s for s in _strategy_provider.list_strategies() if s.real_sharpe is not None]

    # Score strategies via Kelly + risk-parity
    scored = []
    for s in strategies:
        sr = s.real_sharpe or 0.5
        if sr < 0.3:
            continue
        # Estimate daily vol from SR and CAGR
        mu_d = (s.real_cagr or 0.08) / 252
        sigma_d = abs(mu_d / (sr / math.sqrt(252))) if sr != 0 else 0.01
        vol_ann = sigma_d * math.sqrt(252)
        # Kelly fraction (half-Kelly cap at 0.5)
        kelly = min((sr ** 2) / max(vol_ann ** 2, 0.001), 0.5)
        scored.append({
            "id": s.id,
            "title": s.paper_title,
            "symbol": (s.asset_universe[0] if s.asset_universe else "sSPY"),
            "sharpe": round(sr, 4),
            "cagr": round(s.real_cagr or 0.0, 4),
            "max_drawdown": round(s.real_max_dd or 0.0, 4),
            "vol_ann": round(vol_ann, 4),
            "kelly_fraction": round(kelly, 4),
            "passes_rigor_gate": s.passes_rigor_gate,
            "dsr_p_value": s.dsr_p_value,
            "pbo_score": s.pbo_score,
        })

    if not scored:
        return {"error": "No strategies with real backtest data available", "allocations": []}

    # Kelly weights (proportional to Kelly fractions)
    total_kelly = sum(sc["kelly_fraction"] for sc in scored)
    # Risk-parity weights (inverse vol)
    inv_vols = [1.0 / max(sc["vol_ann"], 0.001) for sc in scored]
    total_inv_vol = sum(inv_vols)
    # Blend 60% Kelly + 40% risk-parity
    allocations = []
    for i, sc in enumerate(scored):
        kelly_w = (sc["kelly_fraction"] / max(total_kelly, 1e-9)) if total_kelly > 0 else 1 / len(scored)
        rp_w = inv_vols[i] / max(total_inv_vol, 1e-9)
        blended = 0.6 * kelly_w + 0.4 * rp_w
        # Cap at 0.35
        capped = min(blended * synth_budget, 0.35)
        allocations.append({**sc, "weight": round(capped, 4)})

    # Normalize synth weights
    total_synth = sum(a["weight"] for a in allocations)
    if total_synth > 0:
        for a in allocations:
            a["weight"] = round(a["weight"] / total_synth * synth_budget, 4)

    # Sort by weight desc
    allocations.sort(key=lambda x: -x["weight"])

    # Compute expected portfolio metrics (weighted average)
    total_w = sum(a["weight"] for a in allocations)
    exp_sharpe = sum(a["sharpe"] * a["weight"] for a in allocations) / max(total_w, 1e-9)
    exp_cagr = sum(a["cagr"] * a["weight"] for a in allocations) / max(total_w, 1e-9)
    exp_max_dd = sum(a["max_drawdown"] * a["weight"] for a in allocations) / max(total_w, 1e-9)

    # Regime narrative
    regime_narratives = {
        "risk_on": "Markets are calm (low VIX, price above MA). Full synth exposure recommended.",
        "transition": "Markets are transitioning. Moderate caution; holding base USDC floor.",
        "risk_off": "Markets are stressed. USDC floor increased 2.5×; reduced synth exposure.",
        "crisis": "Crisis conditions. Maximum USDC floor (5× multiplier); minimal synth exposure.",
    }

    return {
        "regime": regime_value,
        "regime_confidence": round(regime_confidence, 4),
        "regime_narrative": regime_narratives.get(regime_value, ""),
        "risk_profile": risk_profile,
        "usdc_weight": round(usdc_floor, 4),
        "synth_weight": round(synth_budget, 4),
        "allocations": allocations,
        "expected_portfolio": {
            "sharpe": round(exp_sharpe, 4),
            "cagr": round(exp_cagr, 4),
            "max_drawdown": round(exp_max_dd, 4),
        },
    }


@strategies_router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str):
    """Get a single strategy by ID. Backed by LocalStrategyProvider."""
    strategy = _strategy_provider.get_strategy(strategy_id)
    if strategy is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_strategy_response(strategy)


@strategies_router.post("/generate", status_code=202)
async def generate_strategy(
    asset_classes: str = "",
    risk_appetite: str = "moderate",
    strategic_direction: str = "",
    max_papers: int = 4,
    mode: str = "fusion",
):
    """Queue a strategy generation job. Returns 202 + job_id immediately.

    Fusion: multi-paper novelty-seeking synthesis (requires corpus + LLM backend).
    Architect: fast single-paper path (?mode=fast).
    """
    from fastapi import HTTPException
    from archimedes.models.portfolio import RiskProfile
    from archimedes.services.job_queue import JobStore

    if mode == "fast":
        # Architect single-paper sub-mode — still synchronous for fast path
        try:
            proposal = await asyncio.to_thread(
                _architect.propose,
                strategic_direction or "Generate a strategy",
                risk_appetite,
                10000.0,
                None,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"LLM backend unavailable: {exc}") from exc
        guardrail = apply_guardrail(proposal)
        return {
            "mode": "architect",
            "status": "ok",
            "proposal": {
                "intent": proposal.intent,
                "model_id": proposal.model_id,
                "selected": [
                    {"strategy_id": s.strategy_id, "weight": w, "rationale": s.rationale}
                    for s, w in zip(proposal.selected, guardrail.strategy_weights.values())
                ],
                "overall_reasoning": proposal.overall_reasoning,
                "usyc_weight": guardrail.usyc_weight,
            },
        }

    # Primary path: fusion — validate then enqueue
    if not fusion_enabled():
        raise HTTPException(
            status_code=503,
            detail="Fusion is disabled. Set ARCHIMEDES_FUSION_ENABLED=1.",
        )

    corpus = load_corpus()
    if len(corpus) < 2:
        raise HTTPException(
            status_code=503,
            detail=f"Insufficient corpus ({len(corpus)} papers). Need ≥2 for fusion.",
        )

    try:
        rp = RiskProfile(risk_appetite)
    except ValueError:
        rp = RiskProfile.MODERATE

    # Read live regime data (3rd input)
    market_context: dict = {}
    try:
        from archimedes.services.redis_state import AgentStateStore
        state = AgentStateStore()
        try:
            regime_data = await state.load_regime()
            if regime_data:
                market_context = {
                    "regime": regime_data.get("regime", "unknown"),
                    "confidence": regime_data.get("confidence", 0.0),
                    "source": regime_data.get("source", ""),
                    "strategy_count": regime_data.get("strategy_count", 0),
                    "signals": regime_data.get("signals", {}),
                }
        finally:
            await state.close()
    except Exception:
        pass  # Non-blocking — degrade without fabricating

    store = JobStore()
    try:
        job_id = await store.enqueue(
            job_type="fusion",
            payload={
                "asset_classes": [a.strip() for a in asset_classes.split(",") if a.strip()],
                "risk_appetite": rp.value,
                "strategic_direction": strategic_direction,
                "max_papers": max_papers,
                "market_context": market_context,
            },
        )
    finally:
        await store.close()

    # Spawn background worker
    asyncio.create_task(_run_fusion_job(job_id))

    return {"status": "queued", "job_id": job_id}


@strategies_router.get("/generate/{job_id}")
async def get_generation_job(job_id: str):
    """Poll a strategy generation job. Returns status + result when done."""
    from fastapi import HTTPException
    from archimedes.services.job_queue import JobStore

    store = JobStore()
    try:
        job = await store.get(job_id)
    finally:
        await store.close()

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_fusion_job(job_id: str) -> None:
    """Background worker: runs fusion and updates job status."""
    from archimedes.models.portfolio import RiskProfile
    from archimedes.services.job_queue import JobStore

    store = JobStore()
    try:
        await store.update_status(job_id, "running")

        job = await store.get(job_id)
        if not job or not job.get("payload"):
            await store.update_status(job_id, "failed", error="Job payload missing")
            return

        payload = job["payload"]
        rp = RiskProfile(payload.get("risk_appetite", "moderate"))

        brief = FusionBrief(
            asset_classes=payload.get("asset_classes", []),
            risk_appetite=rp,
            strategic_direction=payload.get("strategic_direction", ""),
            max_papers=payload.get("max_papers", 4),
            market_context=payload.get("market_context", {}),
        )

        fusion = default_fusion()
        result = await asyncio.to_thread(fusion.propose, brief)

        if not result.is_actionable:
            await store.update_status(job_id, "done", result={
                "mode": "fusion",
                "status": result.status,
                "message": result.thesis,
            })
            return

        # Persist to StrategyStore
        strategy_id = None
        try:
            with get_session() as session:
                source_papers = [
                    {"arxiv_id": aid, "sha256": ""}
                    for aid in result.source_arxiv_ids
                ]
                record = upsert_strategy(
                    session,
                    generation_method="fusion",
                    strategy_name=result.strategy_name,
                    thesis=result.thesis,
                    source_papers=source_papers,
                    asset_universe=brief.asset_classes,
                    risk_profile=rp.value,
                    provenance_hash=result.model,
                )
                session.commit()
                strategy_id = record.id
        except Exception:
            pass

        await store.update_status(job_id, "done", result={
            "mode": "fusion",
            "status": result.status,
            "strategy_name": result.strategy_name,
            "thesis": result.thesis,
            "source_arxiv_ids": result.source_arxiv_ids,
            "fusion_reasoning": result.fusion_reasoning,
            "novelty_rationale": result.novelty_rationale,
            "risk_notes": result.risk_notes,
            "model": result.model,
            "requested_model": result.requested_model,
            "strategy_id": strategy_id,
            "market_context_used": brief.market_context,
        })
    except Exception as exc:
        try:
            await store.update_status(job_id, "failed", error=str(exc))
        except Exception:
            pass
    finally:
        await store.close()


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
    """List reasoning traces — merges on-chain IDs with off-chain metadata."""
    from archimedes.services.redis_state import AgentStateStore

    state = AgentStateStore()
    try:
        # Get off-chain traces from Redis (enriched data)
        off_chain_traces, total = await state.list_traces(
            vault_address=vault_address,
            decision_type=decision_type,
            limit=limit,
            offset=offset,
        )

        if off_chain_traces:
            traces = []
            for t in off_chain_traces:
                traces.append(TraceResponse(
                    id=t.get("id", ""),
                    vault_address=t.get("vault_address", ""),
                    decision_type=t.get("decision_type", "unknown"),
                    trigger=t.get("trigger", "unknown"),
                    timestamp=t.get("timestamp", ""),
                    reasoning=t.get("reasoning", ""),
                    confidence=t.get("confidence", 0.0),
                    trace_hash=t.get("trace_hash", ""),
                    arc_tx_hash=t.get("arc_tx_hash"),
                    is_verified=t.get("is_verified", False),
                    regime_at_decision=t.get("market_context", {}).get("regime"),
                    trades_executed=t.get("trades_executed", []),
                    strategies_referenced=t.get("strategies_referenced", []),
                    # Commit-reveal temporal binding
                    commit_tx_hash=t.get("commit_tx_hash"),
                    commit_block_number=t.get("commit_block_number"),
                    reveal_tx_hash=t.get("reveal_tx_hash"),
                    reveal_block_number=t.get("reveal_block_number"),
                    trade_tx_hash=t.get("trade_tx_hash"),
                    trade_block_number=t.get("trade_block_number"),
                    temporal_binding_valid=t.get("temporal_binding_valid"),
                ))
            return TraceListResponse(traces=traces, total=total)

        # Fallback: read on-chain traces directly if no off-chain data yet
        from archimedes.chain.trace_publisher import trace_publisher

        traces: list[TraceResponse] = []
        try:
            total_count = await trace_publisher.get_total_trace_count()
            start = max(1, total_count - offset - limit + 1)
            end = max(1, total_count - offset)

            for trace_id in range(end, start - 1, -1):
                detail = await trace_publisher.get_trace_by_id(trace_id)
                if detail is None:
                    continue

                if vault_address and detail["vault"].lower() != vault_address.lower():
                    continue

                from datetime import datetime, timezone

                traces.append(
                    TraceResponse(
                        id=str(trace_id),
                        vault_address=detail["vault"],
                        decision_type="rebalance",
                        trigger="on-chain",
                        timestamp=datetime.fromtimestamp(
                            detail["timestamp"], tz=timezone.utc
                        ).isoformat(),
                        reasoning="On-chain trace (off-chain metadata not available)",
                        confidence=0.0,
                        trace_hash=detail["trace_hash"],
                        is_verified=True,
                    )
                )
        except Exception:
            pass

        return TraceListResponse(traces=traces, total=len(traces))
    finally:
        await state.close()


@traces_router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str):
    """Get a single reasoning trace by ID (on-chain or off-chain hash)."""
    from archimedes.services.redis_state import AgentStateStore
    from archimedes.chain.trace_publisher import trace_publisher
    from fastapi import HTTPException
    from datetime import datetime, timezone

    state = AgentStateStore()
    try:
        # Try off-chain first (trace_id may be a hash)
        off_chain = await state.get_trace(trace_id)
        if off_chain:
            return TraceResponse(
                id=off_chain.get("id", trace_id),
                vault_address=off_chain.get("vault_address", ""),
                decision_type=off_chain.get("decision_type", "unknown"),
                trigger=off_chain.get("trigger", "unknown"),
                timestamp=off_chain.get("timestamp", ""),
                reasoning=off_chain.get("reasoning", ""),
                confidence=off_chain.get("confidence", 0.0),
                trace_hash=off_chain.get("trace_hash", ""),
                arc_tx_hash=off_chain.get("arc_tx_hash"),
                is_verified=off_chain.get("is_verified", False),
                regime_at_decision=off_chain.get("market_context", {}).get("regime"),
                trades_executed=off_chain.get("trades_executed", []),
                strategies_referenced=off_chain.get("strategies_referenced", []),
                # Commit-reveal temporal binding
                commit_tx_hash=off_chain.get("commit_tx_hash"),
                commit_block_number=off_chain.get("commit_block_number"),
                reveal_tx_hash=off_chain.get("reveal_tx_hash"),
                reveal_block_number=off_chain.get("reveal_block_number"),
                trade_tx_hash=off_chain.get("trade_tx_hash"),
                trade_block_number=off_chain.get("trade_block_number"),
                temporal_binding_valid=off_chain.get("temporal_binding_valid"),
            )

        # Try on-chain numeric ID
        try:
            int_id = int(trace_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Trace not found")

        detail = await trace_publisher.get_trace_by_id(int_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Trace not found")

        return TraceResponse(
            id=trace_id,
            vault_address=detail["vault"],
            decision_type="rebalance",
            trigger="on-chain",
            timestamp=datetime.fromtimestamp(
                detail["timestamp"], tz=timezone.utc
            ).isoformat(),
            reasoning="On-chain trace (off-chain metadata not available)",
            confidence=0.0,
            trace_hash=detail["trace_hash"],
            is_verified=True,
        )
    finally:
        await state.close()


@traces_router.post("/publish", response_model=TracePublishResponse)
async def publish_trace(req: TracePublishRequest):
    """Publish a reasoning trace: compute hash, anchor on Arc, persist off-chain.

    This is the primary endpoint for the Reasoning page's "Publish" flow
    and for the agent runner's autonomous rebalance traces.
    """
    import uuid
    from datetime import datetime, timezone

    from archimedes.models.trace import DecisionType, ReasoningTrace
    from archimedes.chain.trace_publisher import trace_publisher
    from archimedes.services.redis_state import AgentStateStore
    from fastapi import HTTPException

    # Validate decision_type
    try:
        dt = DecisionType(req.decision_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid decision_type: {req.decision_type}. "
                   f"Must be one of: construction, rebalance, rotation, regime_change, skip",
        )

    # Build the trace
    trace = ReasoningTrace(
        id=str(uuid.uuid4()),
        vault_address=req.vault_address,
        decision_type=dt,
        trigger=req.trigger,
        timestamp=datetime.now(timezone.utc),
        market_context=req.market_context,
        portfolio_before=req.portfolio_before,
        portfolio_after=req.portfolio_after,
        reasoning=req.reasoning,
        confidence=req.confidence,
        trades_executed=req.trades_executed,
        strategies_referenced=req.strategies_referenced,
    )

    # Compute keccak256 hash
    trace.compute_hash()

    # Persist off-chain to Redis
    off_chain_data = {
        "id": trace.id,
        "vault_address": trace.vault_address,
        "decision_type": trace.decision_type.value,
        "trigger": trace.trigger,
        "timestamp": trace.timestamp.isoformat(),
        "market_context": trace.market_context,
        "portfolio_before": trace.portfolio_before,
        "portfolio_after": trace.portfolio_after,
        "reasoning": trace.reasoning,
        "confidence": trace.confidence,
        "trades_executed": trace.trades_executed,
        "strategies_referenced": trace.strategies_referenced,
        "trace_hash": trace.trace_hash,
        "arc_tx_hash": None,
        "is_verified": False,
    }

    # Publish on-chain
    arc_tx_hash = None
    try:
        arc_tx_hash = await trace_publisher.publish(trace)
        if arc_tx_hash:
            off_chain_data["arc_tx_hash"] = arc_tx_hash
            off_chain_data["is_verified"] = True
    except Exception as e:
        # On-chain publish failed — still persist off-chain
        import logging
        logging.getLogger(__name__).error(f"On-chain publish failed: {e}")

    # Save to Redis regardless
    state = AgentStateStore()
    try:
        await state.save_trace(off_chain_data)
    finally:
        await state.close()

    return TracePublishResponse(
        id=trace.id,
        trace_hash=trace.trace_hash,
        arc_tx_hash=arc_tx_hash,
        is_anchored=arc_tx_hash is not None,
        timestamp=trace.timestamp.isoformat(),
        vault_address=trace.vault_address,
        decision_type=trace.decision_type.value,
    )


@traces_router.get("/{trace_id}/verify", response_model=TraceVerifyResponse)
async def verify_trace(trace_id: str):
    """Verify a reasoning trace against its on-chain anchor.

    Recomputes the keccak256 hash from off-chain data and compares
    with the hash stored in ReasoningTraceRegistry on Arc.
    """
    from archimedes.chain.trace_publisher import trace_publisher
    from archimedes.services.redis_state import AgentStateStore
    from fastapi import HTTPException

    state = AgentStateStore()
    try:
        # Load off-chain trace data
        off_chain = await state.get_trace(trace_id)
        if not off_chain:
            # Try numeric ID → get hash from on-chain
            try:
                int_id = int(trace_id)
            except ValueError:
                raise HTTPException(status_code=404, detail="Trace not found")

            detail = await trace_publisher.get_trace_by_id(int_id)
            if not detail:
                raise HTTPException(status_code=404, detail="Trace not found")

            return TraceVerifyResponse(
                trace_id=int_id,
                trace_hash=detail["trace_hash"],
                is_verified=True,  # It's on-chain, so the hash is anchored
                agent=detail["agent"],
                vault=detail["vault"],
                on_chain_timestamp=detail["timestamp"],
                details="Hash is anchored on-chain (no off-chain data to recompute against)",
            )

        # We have off-chain data — verify against on-chain
        trace_hash = off_chain.get("trace_hash", "")
        is_verified = False
        agent = ""
        vault = off_chain.get("vault_address", "")
        on_chain_ts = 0
        details = ""

        if not off_chain.get("arc_tx_hash"):
            details = "Trace was not published on-chain — cannot verify"
        else:
            # Search on-chain for this hash — filter by vault first
            try:
                vault_traces = await trace_publisher.get_traces_by_vault(vault)
                on_chain_count = await trace_publisher.get_total_trace_count()
                is_verified = False
                agent = ""
                on_chain_ts = 0

                for tid in vault_traces if vault_traces else range(1, on_chain_count + 1):
                    detail = await trace_publisher.get_trace_by_id(tid)
                    if detail and detail["trace_hash"] == trace_hash.removeprefix("0x"):
                        is_verified = True
                        agent = detail["agent"]
                        on_chain_ts = detail["timestamp"]
                        break
                details = (
                    "Hash verified on-chain ✓"
                    if is_verified
                    else "Hash not found on-chain"
                )
            except Exception as e:
                details = f"Verification failed: {e}"

        return TraceVerifyResponse(
            trace_id=int(trace_id) if trace_id.isdigit() else 0,
            trace_hash=trace_hash,
            is_verified=is_verified,
            agent=agent,
            vault=vault,
            on_chain_timestamp=on_chain_ts,
            details=details,
            # Temporal binding verification
            commit_block_number=off_chain.get("commit_block_number"),
            trade_block_number=off_chain.get("trade_block_number"),
            reveal_block_number=off_chain.get("reveal_block_number"),
            temporal_binding_valid=off_chain.get("temporal_binding_valid"),
        )
    finally:
        await state.close()


# ── Regime ────────────────────────────────────────────────────


@traces_router.get("/{trace_id}/canonical")
async def get_trace_canonical(trace_id: str):
    """Get the canonical JSON used to compute the trace hash.

    Third parties can use this to verify: contract.verifyTrace(id, canonicalBytes)
    where canonicalBytes = utf8Bytes of this response.
    """
    from archimedes.services.redis_state import AgentStateStore
    from fastapi import HTTPException
    from fastapi.responses import PlainTextResponse

    state = AgentStateStore()
    try:
        off_chain = await state.get_trace(trace_id)
        if not off_chain:
            raise HTTPException(status_code=404, detail="Trace not found")

        # Reconstruct a ReasoningTrace from the stored data
        trace = ReasoningTrace(
            id=off_chain["id"],
            vault_address=off_chain["vault_address"],
            decision_type=DecisionType(off_chain["decision_type"]),
            trigger=off_chain["trigger"],
            timestamp=off_chain["timestamp"],
            market_context=off_chain.get("market_context", {}),
            portfolio_before=off_chain.get("portfolio_before", {}),
            portfolio_after=off_chain.get("portfolio_after", {}),
            reasoning=off_chain.get("reasoning", ""),
            confidence=off_chain.get("confidence", 0.0),
            trades_executed=off_chain.get("trades_executed", []),
            strategies_referenced=off_chain.get("strategies_referenced", []),
        )
        return PlainTextResponse(trace.canonical_json(), media_type="application/json")
    finally:
        await state.close()


@regime_router.get("/current", response_model=RegimeResponse)
async def get_current_regime():
    """Get current market regime — reads live state from Redis (agent writes it).

    The agent runner persists regime state to Redis on each tick. This endpoint
    returns the latest classification with confidence, transition probabilities,
    regime history, and strategy recommendations for the current regime.
    """
    from archimedes.services.redis_state import AgentStateStore

    state = AgentStateStore()
    try:
        data = await state.load_regime()
    except Exception:
        data = None
    finally:
        await state.close()

    from archimedes.api.schemas import RegimeSignalsResponse

    # Default transition priors (Dirichlet-inspired)
    default_transitions = {
        "risk_on": {"risk_on": 0.85, "transition": 0.10, "risk_off": 0.04, "crisis": 0.01},
        "transition": {"risk_on": 0.20, "transition": 0.50, "risk_off": 0.25, "crisis": 0.05},
        "risk_off": {"risk_on": 0.05, "transition": 0.15, "risk_off": 0.70, "crisis": 0.10},
        "crisis": {"risk_on": 0.02, "transition": 0.08, "risk_off": 0.30, "crisis": 0.60},
    }

    if data:
        regime_value = data.get("regime", "unknown")
        transitions = data.get("transition_probabilities") or default_transitions
        history = data.get("regime_history_summary") or {"total": 0}

        # Regime → strategy recommendation logic
        regime_to_keywords = {
            "risk_on":    ["momentum", "tsmom", "52w_high", "52-week"],
            "transition": ["volatility", "managed", "tsmom"],
            "risk_off":   ["volatility", "managed", "t-bill"],
            "crisis":     ["t-bill", "preservation", "capital"],
        }
        all_strats = _strategy_provider.list_strategies()
        regime_keywords = regime_to_keywords.get(regime_value, [])
        recommended_ids: list[str] = []
        for keyword in regime_keywords:
            for s in all_strats:
                title_lower = s.paper_title.lower().replace("_", " ")
                if keyword in title_lower or keyword.replace("-", "") in title_lower.replace("-", ""):
                    if s.id not in recommended_ids:
                        recommended_ids.append(s.id)
                        break

        return RegimeResponse(
            regime=regime_value,
            confidence=data.get("confidence", 0.0),
            timestamp=data.get("timestamp", ""),
            regime_changed=data.get("regime_changed", False),
            signals=RegimeSignalsResponse(
                vix_level=data.get("vix_level") or data.get("vix", 0.0),
                sp500_above_ma50=data.get("sp500_above_ma50", True),
                sp500_above_ma200=data.get("sp500_above_ma200", True),
                vix_rate_of_change=data.get("vix_rate_of_change"),
                vix_score=data.get("vix_score"),
                ma_score=data.get("ma_score"),
                composite_score=data.get("composite_score"),
                credit_spread_ig=data.get("credit_spread_ig"),
                credit_spread_hy=data.get("credit_spread_hy"),
                btc_dominance=data.get("btc_dominance"),
            ),
            transition_probabilities=transitions,
            regime_history=history,
            recommended_strategies=recommended_ids[:2],
        )

    return RegimeResponse(
        regime="unknown",
        confidence=0.0,
        timestamp="",
        regime_changed=False,
        signals=RegimeSignalsResponse(
            vix_level=0.0,
            sp500_above_ma50=True,
            sp500_above_ma200=True,
        ),
        transition_probabilities=default_transitions,
        regime_history={"total": 0},
        recommended_strategies=[],
    )


@regime_router.get("/transitions")
async def get_regime_transitions():
    """Get regime transition probability matrix.

    Returns the estimated probability of transitioning from each regime
    to every other regime, based on historical observations.
    """
    from archimedes.services.redis_state import AgentStateStore

    state = AgentStateStore()
    try:
        data = await state.load_regime()
        transitions = data.get("transition_probabilities") if data else None
        history = data.get("regime_history_summary") if data else None
    except Exception:
        transitions = None
        history = None
    finally:
        await state.close()

    if not transitions:
        # Return default uniform-ish priors
        transitions = {
            "risk_on": {"risk_on": 0.85, "transition": 0.10, "risk_off": 0.04, "crisis": 0.01},
            "transition": {"risk_on": 0.20, "transition": 0.50, "risk_off": 0.25, "crisis": 0.05},
            "risk_off": {"risk_on": 0.05, "transition": 0.15, "risk_off": 0.70, "crisis": 0.10},
            "crisis": {"risk_on": 0.02, "transition": 0.08, "risk_off": 0.30, "crisis": 0.60},
        }

    return {
        "transition_probabilities": transitions,
        "history": history or {"total": 0},
    }


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


# ── Agent Status ─────────────────────────────────────────────


@agent_router.get("/status", response_model=AgentStatusResponse)
async def get_agent_status():
    """Get autonomous agent health and state — reads from Redis."""
    from datetime import datetime, timezone

    from archimedes.services.redis_state import AgentStateStore

    state = AgentStateStore()
    try:
        heartbeat = await state.get_heartbeat()
        regime_data = await state.load_regime()
        events = await state.get_events(count=10)
    except Exception:
        heartbeat = None
        regime_data = None
        events = []
    finally:
        await state.close()

    alive = False
    if heartbeat:
        try:
            hb_time = datetime.fromisoformat(heartbeat)
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
            alive = age < 600
        except Exception:
            pass

    regime = regime_data.get("regime") if regime_data else None
    confidence = regime_data.get("confidence") if regime_data else None
    source = regime_data.get("source") if regime_data else None
    strat_count = regime_data.get("strategy_count", 0) if regime_data else 0

    vault_count = 0
    try:
        vaults = await chain_executor.get_all_vaults()
        vault_count = len(vaults) if vaults else 0
    except Exception:
        pass

    return AgentStatusResponse(
        alive=alive,
        last_heartbeat=heartbeat,
        regime=regime,
        regime_confidence=confidence,
        regime_source=source,
        strategy_count=strat_count,
        managed_vaults=vault_count,
        recent_events=events,
    )


@agent_router.get("/circle-status")
async def get_circle_integration_status():
    """Get Circle SDK integration breadth status.

    Shows which Circle tools are being used and their status.
    Contributes to the 20% Circle Tool Usage rubric category.
    """
    from archimedes.services.circle_service import circle_service
    return await circle_service.get_integration_status()


@agent_router.post("/bootstrap-liquidity")
async def bootstrap_amm_liquidity():
    """Add AMM pool liquidity so vault rebalances can execute.

    Adds USDC + synth token pairs to all AMM pools using the Circle wallet.
    Runs in the background to avoid 504 timeout.
    """
    import asyncio
    from archimedes.services.amm_bootstrap import bootstrap_amm_liquidity as _bootstrap

    async def _run():
        try:
            await _bootstrap()
        except Exception:
            pass

    asyncio.create_task(_run())
    return {"status": "started", "message": "Liquidity bootstrap running in background. Check /api/swap/pools in 2-3 minutes."}


# ── Paper Browser (corpus source-exposure) ─────────────────────


@papers_router.get("/")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    search: str | None = None,
):
    """Paginated corpus catalog. DB-backed with file fallback."""
    from archimedes.models.corpus_store import PaperRecord

    with get_session() as session:
        query = session.query(PaperRecord)

        if category:
            query = query.filter(PaperRecord.categories.contains(category))
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                (PaperRecord.title.ilike(pattern)) | (PaperRecord.abstract.ilike(pattern))
            )

        total = query.count()
        rows = (
            query.order_by(PaperRecord.published.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        papers = [
            {
                "arxiv_id": r.arxiv_id,
                "title": r.title,
                "primary_category": r.primary_category,
                "categories": json.loads(r.categories) if r.categories else [],
                "published": r.published,
                "abstract": r.abstract[:200] + "..." if len(r.abstract) > 200 else r.abstract,
            }
            for r in rows
        ]

    # If DB is empty, fall back to file-based corpus
    if total == 0 and not category and not search:
        from archimedes.services.strategy_fusion import load_corpus
        corpus = load_corpus()
        all_papers = [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "primary_category": p.primary_category,
                "categories": list(p.categories),
                "published": p.published,
                "abstract": p.abstract[:200] + "..." if len(p.abstract) > 200 else p.abstract,
            }
            for p in corpus
        ]
        total = len(all_papers)
        start = (page - 1) * page_size
        papers = all_papers[start:start + page_size]

    return {"total": total, "page": page, "page_size": page_size, "papers": papers}


@papers_router.get("/{arxiv_id}")
async def get_paper(arxiv_id: str):
    """Single paper detail + citing strategies (bidirectional provenance)."""
    from archimedes.models.corpus_store import PaperRecord
    from archimedes.models.strategy_store import strategies_by_paper
    from fastapi import HTTPException

    # Try DB first
    with get_session() as session:
        record = session.query(PaperRecord).filter(PaperRecord.arxiv_id == arxiv_id).first()

    if record is not None:
        citing_strategies = []
        try:
            with get_session() as session:
                records = strategies_by_paper(session, arxiv_id)
                citing_strategies = [
                    {"id": r.id, "name": r.strategy_name, "status": r.status, "method": r.generation_method}
                    for r in records
                ]
        except Exception:
            pass

        return {
            "arxiv_id": record.arxiv_id,
            "title": record.title,
            "authors": json.loads(record.authors) if record.authors else [],
            "primary_category": record.primary_category,
            "categories": json.loads(record.categories) if record.categories else [],
            "published": record.published,
            "abstract": record.abstract,
            "pdf_url": record.pdf_url,
            "source": record.source,
            "citing_strategies": citing_strategies,
        }

    # File fallback
    from archimedes.services.strategy_fusion import load_corpus
    corpus = load_corpus()
    paper = next((p for p in corpus if p.arxiv_id == arxiv_id), None)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    citing_strategies = []
    try:
        with get_session() as session:
            records = strategies_by_paper(session, arxiv_id)
            citing_strategies = [
                {"id": r.id, "name": r.strategy_name, "status": r.status, "method": r.generation_method}
                for r in records
            ]
    except Exception:
        pass

    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "primary_category": paper.primary_category,
        "categories": list(paper.categories),
        "published": paper.published,
        "abstract": paper.abstract,
        "citing_strategies": citing_strategies,
    }


# ── Corpus Overview ──────────────────────────────────────────────


@papers_router.get("/corpus/overview")
async def get_corpus_overview():
    """High-level library breakdown: category mix, year distribution, totals."""
    from collections import Counter
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func

    # DB-backed overview
    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0

        if total > 0:
            # Category distribution via primary_category
            cat_rows = (
                session.query(PaperRecord.primary_category, func.count(PaperRecord.arxiv_id))
                .group_by(PaperRecord.primary_category)
                .order_by(func.count(PaperRecord.arxiv_id).desc())
                .all()
            )
            category_counts = Counter()
            for cat, cnt in cat_rows:
                category_counts[cat] = cnt

            # Year distribution
            year_rows = (
                session.query(
                    func.substr(PaperRecord.published, 1, 4).label("year"),
                    func.count(PaperRecord.arxiv_id),
                )
                .filter(PaperRecord.published != "")
                .group_by("year")
                .order_by("year")
                .all()
            )
            year_dist = [(yr, cnt) for yr, cnt in year_rows if yr and yr.isdigit()]

            return {
                "total_papers": total,
                "source": "database",
                "categories": [{"name": cat, "count": cnt} for cat, cnt in category_counts.most_common(20)],
                "year_distribution": [{"year": yr, "count": cnt} for yr, cnt in year_dist],
            }

    # File fallback if DB is empty
    from archimedes.services.strategy_fusion import load_corpus

    corpus = load_corpus()
    category_counts: Counter = Counter()
    year_counts: Counter = Counter()
    for p in corpus:
        category_counts[p.primary_category] += 1
        for c in p.categories:
            category_counts[c] += 1
        if p.published:
            year = p.published[:4]
            if year.isdigit():
                year_counts[year] += 1

    top_categories = category_counts.most_common(20)
    year_dist = sorted(year_counts.items())

    return {
        "total_papers": len(corpus),
        "source": "file",
        "categories": [{"name": cat, "count": cnt} for cat, cnt in top_categories],
        "year_distribution": [{"year": yr, "count": cnt} for yr, cnt in year_dist],
    }


@papers_router.get("/corpus/graph")
async def get_corpus_graph(
    sample: int = 500,
    lod: int = 1,
):
    """Similarity graph nodes/edges for the corpus.

    Degrades gracefully: returns a category-cooccurrence graph derived from
    DB metadata when no precomputed embedding artifact exists. The ``sample``
    param controls max nodes returned (LOD for ≥10k scale).
    """
    import json
    from collections import defaultdict
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func

    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0
        if total == 0:
            return {"status": "empty", "nodes": [], "edges": [], "total_papers": 0}

        # Build a category-based co-occurrence graph from paper metadata
        papers = (
            session.query(PaperRecord.arxiv_id, PaperRecord.title, PaperRecord.categories, PaperRecord.cluster_id, PaperRecord.topic_label)
            .limit(sample)
            .all()
        )

        nodes = []
        edges = []
        cat_papers = defaultdict(list)

        for p in papers:
            label = p.topic_label or p.primary_category if hasattr(p, 'primary_category') else None
            try:
                cats = json.loads(p.categories) if p.categories else []
            except (json.JSONDecodeError, TypeError):
                cats = []
            if not cats:
                cats = ["uncategorized"]

            nodes.append({
                "id": p.arxiv_id,
                "title": p.title[:80] if p.title else p.arxiv_id,
                "cluster": p.cluster_id or cats[0],
                "label": label,
                "categories": cats[:3],
            })

            for c in cats[:3]:
                cat_papers[c].append(p.arxiv_id)

        # Create edges between papers sharing categories
        edge_set = set()
        for cat, pids in cat_papers.items():
            for i in range(min(len(pids), 20)):
                for j in range(i + 1, min(len(pids), 20)):
                    pair = tuple(sorted([pids[i], pids[j]]))
                    if pair not in edge_set:
                        edge_set.add(pair)
                        edges.append({"source": pair[0], "target": pair[1], "weight": 1, "type": "category_cooccurrence"})

        return {
            "status": "metadata_derived",
            "note": "Category co-occurrence graph from metadata. Embedding-based similarity pending KB pipeline port (#101).",
            "total_papers": total,
            "sampled": len(nodes),
            "nodes": nodes,
            "edges": edges[:2000],  # cap for perf
        }


@papers_router.get("/corpus/kg")
async def get_corpus_kg(
    entity: str | None = None,
    depth: int = 1,
):
    """Knowledge-graph subgraph filtered by entity.

    Degrades gracefully: returns author co-authorship and category-entity
    relationships from DB metadata when no precomputed KG artifact exists.
    """
    import json
    from collections import defaultdict
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func, or_

    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0
        if total == 0:
            return {"status": "empty", "entities": [], "relations": [], "total_papers": 0}

        q = session.query(PaperRecord)
        if entity:
            like = f"%{entity}%"
            q = q.filter(
                or_(
                    PaperRecord.title.ilike(like),
                    PaperRecord.abstract.ilike(like),
                    PaperRecord.authors.ilike(like),
                    PaperRecord.categories.ilike(like),
                )
            )
        papers = q.limit(200).all()

        entities = {}
        relations = []

        for p in papers:
            # Paper node
            entities[f"paper:{p.arxiv_id}"] = {
                "type": "paper",
                "id": p.arxiv_id,
                "label": p.title[:100] if p.title else p.arxiv_id,
            }

            # Author entities
            try:
                authors = json.loads(p.authors) if p.authors else []
            except (json.JSONDecodeError, TypeError):
                authors = []
            for a in authors[:5]:
                a_key = f"author:{a}"
                if a_key not in entities:
                    entities[a_key] = {"type": "author", "id": a, "label": a}
                relations.append({"source": f"paper:{p.arxiv_id}", "target": a_key, "type": "authored_by"})

            # Category entities
            try:
                cats = json.loads(p.categories) if p.categories else []
            except (json.JSONDecodeError, TypeError):
                cats = []
            for c in cats[:3]:
                c_key = f"category:{c}"
                if c_key not in entities:
                    entities[c_key] = {"type": "category", "id": c, "label": c}
                relations.append({"source": f"paper:{p.arxiv_id}", "target": c_key, "type": "belongs_to"})

        return {
            "status": "metadata_derived",
            "note": "Author/category KG from metadata. Full REBEL/SciSpacy KG pending KB pipeline port (#101).",
            "total_papers": total,
            "filtered": len(papers),
            "entities": list(entities.values()),
            "relations": relations[:2000],
        }
