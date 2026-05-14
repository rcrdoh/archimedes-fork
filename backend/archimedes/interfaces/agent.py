"""Agent orchestrator interface — Chuan implements this.

This is the brain of the system. It polls on a schedule, reads market state,
runs Önder's math, decides whether to act, and dispatches to Marten's executor.

All other interfaces plug into this one.
"""

from __future__ import annotations

from typing import Protocol

from archimedes.models.portfolio import RebalanceDecision
from archimedes.models.regime import RegimeClassification
from archimedes.models.trace import ReasoningTrace


class IAgentOrchestrator(Protocol):
    """The autonomous portfolio agent — the main polling loop.

    Owner: Chuan
    Dependencies:
      - IRegimeDetector (Önder)
      - IPortfolioConstructor (Önder)
      - IStrategyProvider (Dan)
      - IOracleUpdater (Marten)
      - IChainExecutor (Marten)
      - ITracePublisher (Marten)

    Design reference: design.md § 4.3
    """

    async def tick(self) -> None:
        """Run one iteration of the agent loop.

        The full pipeline per tick:

          1. Marten's IOracleUpdater.fetch_market_snapshot()
          2. Marten's IOracleUpdater.push_prices_on_chain()
          3. Önder's IRegimeDetector.classify(snapshot)
          4. For each managed vault:
             a. Marten's IChainExecutor.read_portfolio(vault)
             b. Check rebalance triggers:
                - Drift > 5% from target
                - Regime changed
                - Strategy rolling 30d Sharpe < 0.5 for 7 days
                - Calendar (weekly)
             c. If triggered:
                - Dan's IStrategyProvider.list_strategies()
                - Önder's IPortfolioConstructor.construct(...)
                - Compute trades = diff(current, target)
                - Cost-benefit: only rebalance if benefit > 2 * cost
             d. If rebalancing:
                - Marten's IChainExecutor.execute_trades(vault, trades)
                - Generate ReasoningTrace
                - Marten's ITracePublisher.publish(trace)
             e. If skipping:
                - Generate skip trace (DecisionType.SKIP)
                - Optionally publish skip trace
          5. Sleep until next tick
        """
        ...

    async def evaluate_vault(self, vault_address: str) -> RebalanceDecision:
        """Evaluate a single vault and decide whether to rebalance.

        Returns a RebalanceDecision with should_rebalance, trades, reasoning.
        Does NOT execute — the caller decides whether to proceed.
        """
        ...

    async def get_current_regime(self) -> RegimeClassification | None:
        """Get the most recent regime classification."""
        ...

    async def get_managed_vaults(self) -> list[str]:
        """List vault addresses this agent manages (Tier 1 + agent-assisted Tier 2)."""
        ...

    async def generate_reasoning_trace(
        self,
        decision: RebalanceDecision,
        regime: RegimeClassification,
    ) -> ReasoningTrace:
        """Generate a structured reasoning trace for a decision.

        Uses Claude API to produce a human-readable explanation that
        references the market context, strategies, and trade rationale.
        """
        ...
