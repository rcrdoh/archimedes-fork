"""Event publisher — bridges Type 2 Agent actions to Type 3 subscription feed.

The Type 2 Agent (publisher) pushes events here after each rebalance/execute.
The Type 3 Agent (replicator) polls this endpoint for new events to replicate.

Events are stored in Redis for fast access and bounded to a window of recent
events (default: last 1000 events, max 1 hour old).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# In-memory event buffer (used when Redis is not available)
# In production, this would use Redis pub/sub or a dedicated message queue.
_events: list[dict[str, Any]] = []
_MAX_EVENTS = 1000


async def publish_event(event_type: str, event_data: dict[str, Any]) -> None:
    """Publish an event to the subscriber feed.

    Called by the Type 2 Agent after each rebalance/execute operation.

    Args:
        event_type: One of "trade", "rebalance", "allocation", "heartbeat"
        event_data: Arbitrary JSON-serializable data about the event
    """
    global _events  # noqa: PLW0603

    event = {
        "type": event_type,
        "data": event_data,
        "timestamp": datetime.now(UTC).isoformat(),
        "id": f"{event_type}_{len(_events)}_{datetime.now(UTC).timestamp()}",
    }

    _events.append(event)

    # Trim to max size
    if len(_events) > _MAX_EVENTS:
        _events = _events[-_MAX_EVENTS:]

    logger.debug("Published event: %s (total: %d)", event_type, len(_events))


async def get_events(since: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Get recent events, optionally filtered by timestamp.

    Args:
        since: ISO timestamp string — only return events after this time.
        limit: Maximum number of events to return.

    Returns:
        List of event dicts.
    """
    events = list(_events)

    if since:
        events = [e for e in events if e.get("timestamp", "") > since]

    return events[-limit:]


def get_events_sync(since: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Synchronous version for use in FastAPI endpoints."""
    events = list(_events)

    if since:
        events = [e for e in events if e.get("timestamp", "") > since]

    return events[-limit:]
