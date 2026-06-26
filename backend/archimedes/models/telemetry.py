"""Telemetry data models — human-vs-agent traction counter (issue #428).

The traction counter is the hackathon win-condition instrument: it measures
how much of the live traffic is *humans* (browser sessions) vs *agents*
(internal agent runner + external bots/scripts) so the "agents make markets"
narrative is backed by a real, live number rather than a claim.

Identity model (today, single-user MVP):
  - HUMAN  = a valid SIWE wallet session cookie (``archimedes_session``).
  - AGENT  = a valid ``X-Internal-Agent-Key`` header (internal), OR no session
             plus a non-browser User-Agent (external bot/script).
  - Default (browser UA, no session) = HUMAN — the demo is open, so an
    un-signed-in browser visitor still counts as a human.

Only response *shapes* live here; classification logic lives in the telemetry
middleware and the counter persistence lives in ``services/telemetry_store.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MetricsResponse(BaseModel):
    """Public traction counter — humans vs agents over the live deployment.

    Served by ``GET /api/metrics``. Counts are monotonic cumulative totals
    since the Redis counters were last reset (deploy / flush).
    """

    human_count: int = Field(..., description="Requests classified as human (SIWE session / browser).")
    agent_count: int = Field(..., description="Requests classified as agent (internal key / bot UA).")
    total_requests: int = Field(..., description="human_count + agent_count.")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp this snapshot was read.")
