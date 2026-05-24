# Archimedes — Shared Data Models
# These types cross component boundaries. Every team member depends on them.
# Change policy: announce in Discord before modifying any model here.

from archimedes.models.paper_ref import PaperRef
from archimedes.models.strategy import (
    StrategyPassport,
    Strategy,  # Backwards-compat alias
    StrategyStatus,
    SignalDefinition,
    PositionSizing,
    RebalanceFrequency,
)
from archimedes.models.backtest import BacktestResult
from archimedes.models.regime import Regime, RegimeSignals, RegimeClassification
from archimedes.models.portfolio import (
    RiskProfile,
    Portfolio,
    PortfolioHolding,
    TargetAllocation,
    RebalanceDecision,
    TradeOrder,
    TradeDirection,
)
from archimedes.models.vault import VaultInfo, VaultTier, VaultMetrics
from archimedes.models.trace import ReasoningTrace, DecisionType
from archimedes.models.asset import AssetInfo, AssetType, AssetPrice

__all__ = [
    # Paper reference
    "PaperRef",
    # Strategy passport
    "StrategyPassport",
    "Strategy",  # Backwards-compat alias
    "StrategyStatus",
    "SignalDefinition",
    "PositionSizing",
    "RebalanceFrequency",
    # Backtest
    "BacktestResult",
    # Regime
    "Regime",
    "RegimeSignals",
    "RegimeClassification",
    # Portfolio
    "RiskProfile",
    "Portfolio",
    "PortfolioHolding",
    "TargetAllocation",
    "RebalanceDecision",
    "TradeOrder",
    "TradeDirection",
    # Vault
    "VaultInfo",
    "VaultTier",
    "VaultMetrics",
    # Trace
    "ReasoningTrace",
    "DecisionType",
    # Asset
    "AssetInfo",
    "AssetType",
    "AssetPrice",
]
