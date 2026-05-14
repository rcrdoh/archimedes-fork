"""REST API response schemas — Daniel's frontend depends on these.

These are Pydantic models that define the JSON shape of every API response.
Chuan implements the FastAPI endpoints; Daniel codes the frontend against
these schemas. Changes here require a heads-up to Daniel.

Convention:
  - All monetary values in USDC are floats (display-friendly)
  - All on-chain addresses are checksummed hex strings
  - All timestamps are ISO 8601 strings
  - Pagination uses limit/offset
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Assets
# ═══════════════════════════════════════════════════════════════


class AssetResponse(BaseModel):
    """Single asset in the ecosystem."""

    address: str
    symbol: str
    name: str
    asset_type: str  # "synthetic" | "bridged" | "native" | "vault_token"
    decimals: int
    price_usd: float
    price_change_24h: float = 0.0  # Percentage change
    oracle_address: str | None = None


class AssetListResponse(BaseModel):
    assets: list[AssetResponse]


class AssetPriceHistoryResponse(BaseModel):
    """Historical prices for charting."""

    symbol: str
    prices: list[PricePoint]
    interval: str  # "1h" | "1d" | "1w"


class PricePoint(BaseModel):
    timestamp: str  # ISO 8601
    price: float


# ═══════════════════════════════════════════════════════════════
# Vaults
# ═══════════════════════════════════════════════════════════════


class VaultHolding(BaseModel):
    """A single position in a vault."""

    symbol: str
    token_address: str
    amount: float
    value_usdc: float
    weight_pct: float  # e.g. 30.5 = 30.5%


class VaultSummaryResponse(BaseModel):
    """Vault card for the leaderboard/list view."""

    address: str
    name: str
    symbol: str
    tier: int  # 1 or 2
    creator: str  # Wallet address
    aum_usdc: float
    share_price: float
    return_24h: float
    return_7d: float
    return_30d: float
    return_inception: float
    sharpe_ratio: float | None = None
    management_fee_pct: float  # e.g. 1.5
    performance_fee_pct: float  # e.g. 20.0
    is_agent_assisted: bool
    depositors: int
    last_rebalance: str | None = None  # ISO 8601
    created_at: str


class VaultDetailResponse(BaseModel):
    """Full vault detail page data."""

    # Core info (same as summary)
    address: str
    name: str
    symbol: str
    tier: int
    creator: str
    aum_usdc: float
    share_price: float
    is_agent_assisted: bool

    # Fees
    management_fee_pct: float
    performance_fee_pct: float
    high_water_mark: float

    # Holdings
    holdings: list[VaultHolding]
    target_allocations: list[VaultHolding]  # Target weights

    # Performance
    return_24h: float
    return_7d: float
    return_30d: float
    return_inception: float
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None

    # Equity curve for charting
    equity_curve: list[PricePoint] = []

    # Strategy info (Tier 1 only)
    strategy_ids: list[str] = []
    current_regime: str | None = None  # "risk_on" | "risk_off" | etc.

    # Recent reasoning traces
    recent_traces: list[TraceResponse] = []

    # Metadata
    depositors: int = 0
    last_rebalance: str | None = None
    created_at: str = ""


class VaultListResponse(BaseModel):
    vaults: list[VaultSummaryResponse]
    total: int


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════


class StrategyResponse(BaseModel):
    """Strategy detail for the strategy explorer."""

    id: str
    paper_arxiv_id: str
    paper_title: str
    paper_authors: list[str] = []
    methodology_summary: str
    asset_universe: list[str]
    position_sizing: str
    rebalance_frequency: str
    status: str  # "candidate" | "validated" | "live" | "retired"

    # Backtest results (if evaluated)
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None
    cagr: float | None = None
    win_rate: float | None = None
    total_trades: int | None = None
    paper_claimed_sharpe: float | None = None

    # Equity curve for charting
    equity_curve: list[PricePoint] = []


class StrategyListResponse(BaseModel):
    strategies: list[StrategyResponse]
    total: int


# ═══════════════════════════════════════════════════════════════
# Reasoning Traces
# ═══════════════════════════════════════════════════════════════


class TraceResponse(BaseModel):
    """A single reasoning trace for display."""

    id: str
    vault_address: str
    decision_type: str  # "construction" | "rebalance" | "rotation" | "regime_change" | "skip"
    trigger: str
    timestamp: str  # ISO 8601
    reasoning: str  # Human-readable explanation
    confidence: float

    # On-chain verification
    trace_hash: str
    arc_tx_hash: str | None = None
    is_verified: bool = False  # Has on-chain hash been confirmed?

    # Context
    regime_at_decision: str | None = None
    trades_executed: list[TradeExecutedResponse] = []
    strategies_referenced: list[str] = []


class TradeExecutedResponse(BaseModel):
    symbol: str
    direction: str  # "buy" | "sell"
    amount: float
    value_usdc: float


class TraceListResponse(BaseModel):
    traces: list[TraceResponse]
    total: int


# ═══════════════════════════════════════════════════════════════
# Regime
# ═══════════════════════════════════════════════════════════════


class RegimeResponse(BaseModel):
    """Current market regime for display."""

    regime: str  # "risk_on" | "risk_off" | "transition" | "crisis"
    confidence: float
    timestamp: str
    previous_regime: str | None = None
    regime_changed: bool = False
    signals: RegimeSignalsResponse


class RegimeSignalsResponse(BaseModel):
    vix_level: float
    sp500_above_ma50: bool
    sp500_above_ma200: bool
    credit_spread_ig: float | None = None
    btc_dominance: float | None = None


# ═══════════════════════════════════════════════════════════════
# Swap (AMM preview)
# ═══════════════════════════════════════════════════════════════


class SwapQuoteResponse(BaseModel):
    """Preview a swap before user signs the transaction."""

    token_in: str  # Address
    token_out: str
    amount_in: float
    amount_out: float
    price_impact_pct: float  # e.g. 0.5 = 0.5%
    fee_pct: float  # e.g. 0.3 = 0.3%
    min_amount_out: float  # After slippage tolerance


# ═══════════════════════════════════════════════════════════════
# Contract Addresses (for frontend to call on-chain directly)
# ═══════════════════════════════════════════════════════════════


class ContractAddressesResponse(BaseModel):
    """All deployed contract addresses. Frontend needs these for direct on-chain calls."""

    usdc: str
    synthetic_factory: str
    amm_router: str
    vault_factory: str
    reasoning_trace_registry: str
    asset_registry: str
    price_oracle: str

    # Individual synthetic token addresses
    synthetics: dict[str, str]  # symbol → address, e.g. {"sTSLA": "0x..."}

    # AMM pool addresses
    pools: dict[str, str]  # pair → address, e.g. {"USDC/sTSLA": "0x..."}

    # Vault addresses
    vaults: dict[str, str]  # symbol → address, e.g. {"vMOMENTUM": "0x..."}

    # Chain info
    chain_id: int
    rpc_url: str
