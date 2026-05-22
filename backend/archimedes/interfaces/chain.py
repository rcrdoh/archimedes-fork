"""On-chain backend interfaces.

These wrap all interactions with Arc contracts and Circle SDK.
The agent orchestrator calls these.

Reviewer: Chuan (on-chain integration layer — `chain/` subpackage).
Coverage: Marten — per CLAUDE.md § "Lead + coverage", lanes are guidance
for review, not gates for who may author.
"""

from __future__ import annotations

from typing import Protocol

from archimedes.models.asset import AssetPrice, MarketSnapshot
from archimedes.models.portfolio import Portfolio, TradeOrder
from archimedes.models.trace import ReasoningTrace


class IOracleUpdater(Protocol):
    """Fetches real-world prices and pushes them to the on-chain PriceOracle.

    Reviewer: Chuan (on-chain integration); coverage: Marten.
    Runs on a polling loop (every ~60 seconds for hackathon).

    Design reference: ecosystem-design-spec.md § 3.6
    """

    async def fetch_prices(self) -> list[AssetPrice]:
        """Fetch current prices from external data sources (yfinance, CoinGecko).

        Returns prices for all registered synthetic assets:
          sTSLA, sSPY, sGLD, sBTC + USYC yield rate

        Must handle API failures gracefully (return last known price).
        """
        ...

    async def push_prices_on_chain(self, prices: list[AssetPrice]) -> str | None:
        """Call PriceOracle.batchSetPrices() on Arc.

        Args:
            prices: List of AssetPrice to push

        Returns:
            Transaction hash if successful, None if failed.
        """
        ...

    async def fetch_market_snapshot(self) -> MarketSnapshot:
        """Fetch a full market snapshot including regime signals.

        Returns MarketSnapshot with:
          - All asset prices
          - VIX level
          - S&P 500 moving averages (50d, 200d)
          - Credit spreads (if available)
          - BTC dominance
          - USYC yield

        This is the input to IRegimeDetector.
        """
        ...


class IChainExecutor(Protocol):
    """Executes on-chain transactions for the agent.

    Reviewer: Chuan (on-chain integration); coverage: Marten.
    Handles Circle SDK wallet management, transaction signing,
    and confirmation tracking.

    Design reference: ecosystem-design-spec.md § 3.2 (rebalance via AMM)
    """

    async def execute_trades(
        self,
        vault_address: str,
        trades: list[TradeOrder],
    ) -> list[str]:
        """Execute a batch of trades for a vault via the AMM.

        For each TradeOrder:
          1. Approve token spend on AMM router
          2. Call IAMMRouter.swap() with slippage protection
          3. Confirm transaction

        Args:
            vault_address: The vault executing the trades
            trades: List of TradeOrder to execute

        Returns:
            List of transaction hashes (one per trade).
            Raises on failure (partial execution is possible).
        """
        ...

    async def read_portfolio(self, vault_address: str) -> Portfolio:
        """Read a vault's current holdings from on-chain state.

        Calls IVault.getHoldings() and enriches with current prices
        to compute weights and USDC values.
        """
        ...

    async def create_vault(
        self,
        name: str,
        symbol: str,
        management_fee_bps: int,
        performance_fee_bps: int,
        agent_assisted: bool,
    ) -> str:
        """Deploy a new vault via VaultFactory.

        Returns the new vault contract address.
        """
        ...

    async def get_vault_metrics(self, vault_address: str) -> dict:
        """Read vault metrics from on-chain (AUM, share price, HWM, etc.)."""
        ...


class ITracePublisher(Protocol):
    """Publishes reasoning trace hashes to the on-chain ReasoningTraceRegistry.

    Reviewer: Chuan (on-chain integration); coverage: Marten.
    Called by the agent orchestrator after every decision.

    Design reference: design.md § 4.4, ecosystem-design-spec.md § 3.4
    """

    async def publish(self, trace: ReasoningTrace) -> str | None:
        """Publish a reasoning trace hash on-chain.

        Steps:
          1. trace.compute_hash() to get the SHA-256
          2. Call IReasoningTraceRegistry.publishTrace(vault, hash, metadata)
          3. Store arc_tx_hash back on the trace

        Args:
            trace: The ReasoningTrace to anchor on-chain

        Returns:
            Arc transaction hash if successful, None if failed.
        """
        ...

    async def verify(self, trace: ReasoningTrace) -> bool:
        """Verify a trace against its on-chain hash.

        Calls IReasoningTraceRegistry.verifyTrace(traceId, fullTrace).
        """
        ...

    async def get_trace_count(self, vault_address: str) -> int:
        """Get total published traces for a vault."""
        ...
