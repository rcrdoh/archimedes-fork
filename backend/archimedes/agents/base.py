"""Base protocol for Archimedes agents.

Every agent in the multi-agent architecture exposes a common interface
so the generation pipeline can route to any of them uniformly.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentLike(Protocol):
    """Minimal protocol every Archimedes agent satisfies.

    Agents may expose additional methods beyond ``run`` — this protocol
    captures the shared surface the generation pipeline relies on.
    """

    async def run(self, intent: str, **kwargs: Any) -> dict[str, Any]:
        """Execute the agent's primary task.

        Parameters
        ----------
        intent : str
            User-facing intent / prompt describing what to generate.
        **kwargs
            Agent-specific parameters (risk tolerance, asset universe, etc.).

        Returns
        -------
        dict[str, Any]
            Agent output.  Typically includes ``strategy_spec``,
            ``rigor_verdict``, ``papers``, etc. — shape varies by agent.
        """
        ...
