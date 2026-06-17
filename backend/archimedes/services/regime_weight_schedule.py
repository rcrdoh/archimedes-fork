"""Regime-aware weight schedule for portfolio construction.

Maps (risk_profile, regime) → {bull_weight, bear_weight, neutral_weight}
where the weights represent the target allocation mix between bull-tilted,
bear-tilted, and regime-neutral strategies.

Usage:
    from archimedes.services.regime_weight_schedule import regime_weight_schedule

    mix = regime_weight_schedule("moderate", "risk_off")
    # → {"bull": 0.25, "bear": 0.70, "neutral": 0.05}

The schedule is hardcoded v1 per issue #164 spec. The bull/bear/neutral
weights sum to 1.0 and determine how the Portfolio Construction Agent
tilts strategy selection based on the detected market regime.

Owner: Önder (portfolio math lane)
Spec: docs/specs/launch-execution-plan-2026-05-23.md § T-PE.7
"""

from __future__ import annotations

import logging
from typing import TypedDict

from archimedes.services.log_scrubber import sanitize_log_value

logger = logging.getLogger(__name__)


class RegimeMix(TypedDict):
    bull: float
    bear: float
    neutral: float


# Hardcoded v1 weight schedules per the issue #164 spec.
# Outer key: risk profile. Inner key: regime state.
_SCHEDULE: dict[str, dict[str, RegimeMix]] = {
    "fixed_income": {
        "risk_on": {"bull": 0.30, "bear": 0.60, "neutral": 0.10},
        "risk_off": {"bull": 0.10, "bear": 0.80, "neutral": 0.10},
        "transition": {"bull": 0.20, "bear": 0.60, "neutral": 0.20},
        "crisis": {"bull": 0.05, "bear": 0.85, "neutral": 0.10},
    },
    "conservative": {
        "risk_on": {"bull": 0.50, "bear": 0.40, "neutral": 0.10},
        "risk_off": {"bull": 0.20, "bear": 0.70, "neutral": 0.10},
        "transition": {"bull": 0.30, "bear": 0.50, "neutral": 0.20},
        "crisis": {"bull": 0.10, "bear": 0.80, "neutral": 0.10},
    },
    "moderate": {
        "risk_on": {"bull": 0.70, "bear": 0.25, "neutral": 0.05},
        "risk_off": {"bull": 0.25, "bear": 0.70, "neutral": 0.05},
        "transition": {"bull": 0.40, "bear": 0.40, "neutral": 0.20},
        "crisis": {"bull": 0.15, "bear": 0.75, "neutral": 0.10},
    },
    "aggressive": {
        "risk_on": {"bull": 0.85, "bear": 0.10, "neutral": 0.05},
        "risk_off": {"bull": 0.10, "bear": 0.85, "neutral": 0.05},
        "transition": {"bull": 0.50, "bear": 0.40, "neutral": 0.10},
        "crisis": {"bull": 0.05, "bear": 0.90, "neutral": 0.05},
    },
    "hyper_risky": {
        "risk_on": {"bull": 0.95, "bear": 0.03, "neutral": 0.02},
        "risk_off": {"bull": 0.05, "bear": 0.93, "neutral": 0.02},
        "transition": {"bull": 0.55, "bear": 0.35, "neutral": 0.10},
        "crisis": {"bull": 0.02, "bear": 0.95, "neutral": 0.03},
    },
}

# Default for unknown regime or profile
_DEFAULT_MIX: RegimeMix = {"bull": 0.40, "bear": 0.40, "neutral": 0.20}


def regime_weight_schedule(risk_profile: str, regime: str) -> RegimeMix:
    """Look up the bull/bear/neutral weight mix for a given profile + regime.

    Args:
        risk_profile: One of "fixed_income", "conservative", "moderate",
                      "aggressive", "hyper_risky".
        regime: One of "risk_on", "risk_off", "transition", "crisis".

    Returns:
        RegimeMix with bull + bear + neutral summing to 1.0.
    """
    profile_schedule = _SCHEDULE.get(risk_profile.lower())
    if not profile_schedule:
        logger.warning("regime_weight_schedule: unknown profile %r, using default", sanitize_log_value(risk_profile))
        return _DEFAULT_MIX

    mix = profile_schedule.get(regime.lower())
    if not mix:
        logger.warning(
            "regime_weight_schedule: unknown regime %r for %s, using transition",
            sanitize_log_value(regime),
            sanitize_log_value(risk_profile),
        )
        mix = profile_schedule.get("transition", _DEFAULT_MIX)

    return mix


def apply_regime_tilt(
    strategies: list,
    regime: str,
    risk_profile: str,
) -> tuple[list, RegimeMix]:
    """Filter and weight strategies by regime tilt.

    Partitions strategies by their ``regime_tag`` (bull/bear/regime_neutral)
    and returns them ordered by the regime weight schedule — strategies
    matching the dominant regime tilt come first, weighted higher.

    Returns:
        (sorted_strategies, regime_mix) — strategies sorted by tilt
        priority, and the mix used for portfolio display.
    """
    mix = regime_weight_schedule(risk_profile, regime)

    # Partition by regime_tag
    buckets: dict[str, list] = {"bull": [], "bear": [], "regime_neutral": []}
    for s in strategies:
        tag = getattr(s, "regime_tag", "regime_neutral") or "regime_neutral"
        if tag in buckets:
            buckets[tag].append(s)
        else:
            buckets["regime_neutral"].append(s)

    # Build priority-sorted list: highest-weighted regime bucket first
    sorted_pairs = sorted(
        [("bull", mix["bull"]), ("bear", mix["bear"]), ("regime_neutral", mix["neutral"])],
        key=lambda x: -x[1],
    )

    result = []
    for tag, _weight in sorted_pairs:
        result.extend(buckets.get(tag, []))

    return result, mix
