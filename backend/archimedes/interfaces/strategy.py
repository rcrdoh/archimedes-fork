"""Strategy provider interface.

Curates the v1 strategy library (5-10 hand-curated strategies)
and the arxiv extraction pipeline as a demo feature.
This interface abstracts both: the backend doesn't care whether a
strategy was hand-curated or LLM-extracted.

Reviewer: Dan (strategy engine + corpus curation); coverage: Önder.
Per CLAUDE.md § "Lead + coverage", lanes are guidance for review, not gates
for who may author.
"""

from __future__ import annotations

from typing import Protocol

from archimedes.models.strategy import Strategy, StrategyStatus


class IStrategyProvider(Protocol):
    """Provides strategies to the portfolio agent.

    Reviewer: Dan; coverage: Önder.
    Consumers: agent orchestrator, backtest evaluator.

    Design reference: design.md § 4.1
    """

    def list_strategies(
        self,
        status: StrategyStatus | None = None,
        asset_universe: list[str] | None = None,
    ) -> list[Strategy]:
        """List available strategies, optionally filtered.

        Args:
            status: Filter by lifecycle status (None = all)
            asset_universe: Filter to strategies that trade any of these symbols

        Returns:
            List of Strategy objects. For the hackathon MVP this returns
            the 5-10 pre-curated strategies.
        """
        ...

    def get_strategy(self, strategy_id: str) -> Strategy | None:
        """Get a single strategy by ID. Returns None if not found."""
        ...

    def get_strategies_for_risk_profile(
        self,
        risk_profile_name: str,
    ) -> list[Strategy]:
        """Get strategies compatible with a risk profile.

        Filters by:
          - Conservative: low-vol momentum, mean reversion, bond-heavy
          - Moderate: balanced factor exposure, trend following
          - Aggressive: high-conviction momentum, concentrated
          - Hyper-risky: leveraged, sector concentration

        This is Dan's curation judgment call.
        """
        ...

    def extract_from_paper(
        self,
        arxiv_id: str,
    ) -> Strategy | None:
        """[DEMO FEATURE] Extract a strategy from an arxiv paper using LLM.

        This runs the full pipeline: fetch paper → parse → extract signals →
        generate strategy definition. Returns None if extraction fails.

        For the hackathon demo, this runs on 2-3 pre-selected papers.
        """
        ...
