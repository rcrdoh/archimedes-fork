"""Strategy registry — lightweight lookup for publisher / single-strategy contexts.

Wraps the file-system-backed ``LocalStrategyProvider`` so that a caller can
look up a single ``Strategy`` (``StrategyPassport``) by ID without pulling in
the full provider API.  This is the intended entry point for
``strategy_runner_publisher`` and similar agent-adjacent components that only
need ``get(strategy_id)``.
"""

from __future__ import annotations

import logging
from typing import Any

from archimedes.services.strategy_provider import default_provider

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Single-strategy lookup delegating to ``LocalStrategyProvider``.

    Usage::

        registry = StrategyRegistry()
        strategy = registry.get("my_strategy_id")
        if strategy:
            print(strategy.parameters)   # → strategy_spec dict
    """

    def __init__(self) -> None:
        self._provider = default_provider()

    def get(self, strategy_id: str) -> Any | None:
        """Look up a strategy by its identifier.

        Returns the ``Strategy`` (``StrategyPassport``) dataclass instance
        with a ``.parameters`` convenience property, or *None* when the
        strategy ID is unknown.
        """
        raw = self._provider.get_strategy(strategy_id)
        if raw is None:
            logger.warning("Strategy %s not found in provider", strategy_id)
            return None
        # Provide a ``.parameters`` alias over ``strategy_spec`` so the
        # publisher code can use ``strategy.parameters`` without caring
        # about the internal field name.
        if hasattr(raw, "strategy_spec"):
            raw.parameters = raw.strategy_spec  # type: ignore[attr-defined]
        return raw
