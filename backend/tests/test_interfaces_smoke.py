"""Smoke-import the interface Protocol package.

These are typing-only Protocol classes — their bodies are intentionally
just `...` ellipses. The only meaningful coverage signal is that the
module imports cleanly and the published `__all__` symbols resolve to
the expected Protocol classes; that lets the rest of the codebase
import-against-name without surprise.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from typing import Protocol

from archimedes import interfaces
from archimedes.interfaces.agent import IAgentOrchestrator
from archimedes.interfaces.chain import (
    IChainExecutor,
    IOracleUpdater,
    ITracePublisher,
)
from archimedes.interfaces.math import (
    IBacktestEvaluator,
    IPortfolioConstructor,
    IRegimeDetector,
)
from archimedes.interfaces.strategy import IStrategyProvider


def test_all_symbols_exported() -> None:
    expected = {
        "IAgentOrchestrator",
        "IBacktestEvaluator",
        "IChainExecutor",
        "IOracleUpdater",
        "IPortfolioConstructor",
        "IRegimeDetector",
        "IStrategyProvider",
        "ITracePublisher",
    }
    assert set(interfaces.__all__) == expected


def test_all_symbols_are_protocols() -> None:
    """Each interface is a typing.Protocol — the structural-typing contract."""
    for cls in (
        IAgentOrchestrator,
        IBacktestEvaluator,
        IChainExecutor,
        IOracleUpdater,
        IPortfolioConstructor,
        IRegimeDetector,
        IStrategyProvider,
        ITracePublisher,
    ):
        assert issubclass(cls, Protocol) or Protocol in cls.__mro__


def test_exported_names_match_module_attributes() -> None:
    for name in interfaces.__all__:
        assert hasattr(interfaces, name)


def test_agent_orchestrator_has_documented_methods() -> None:
    # The protocol surface is part of the cross-team contract; pin the
    # method names so any rename forces a deliberate update.
    expected = {"tick", "evaluate_vault", "get_current_regime", "get_managed_vaults", "generate_reasoning_trace"}
    assert expected <= set(dir(IAgentOrchestrator))
