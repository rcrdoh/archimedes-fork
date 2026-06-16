"""VIX/MA rule-based market-regime detector — concrete ``IRegimeDetector``.

This is the exogenous market-regime classifier wired into the agent runner
(issue #660). It is deliberately rule-based and hermetic: no fitted model
artifact, no return history, no new pip dependency. The thresholds are
named constants drawn from practitioner literature (VIX term structure +
moving-average trend filters), so the classification is interpretable and
fully unit-testable.

Distinct from ``EnsembleConsensus`` (issue #659): that is an *endogenous*
signal (how flat the strategy ensemble's own signals are); this is an
*exogenous* read on what the market is doing (VIX level, S&P 500 trend).
The agent runner carries both, clearly labelled.

Calibration table (issue #660):

    VIX >= 40  OR  (VIX >= 30 AND not above MA200)        -> CRISIS
    VIX >= 25  OR  not above MA200                         -> RISK_OFF
    VIX <= 15  AND above MA50 AND above MA200              -> RISK_ON
    everything else                                        -> TRANSITION

Confidence is derived from the distance between the current VIX and the
nearest decision-boundary threshold, clamped to [0.5, 0.95]. A two-tick
confirmation rule (hysteresis) prevents a single noisy snapshot from
flipping the regime: the candidate regime must repeat on two consecutive
``classify`` calls before it is adopted.

Owner: Önder (portfolio math + risk pricing); coverage: Dan.
Design reference: design.md § 4.3.3; IRegimeDetector docstring (math.py).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from archimedes.models.asset import MarketSnapshot
from archimedes.models.regime import (
    Regime,
    RegimeClassification,
    RegimeSignals,
)

logger = logging.getLogger(__name__)

# ─── Calibration thresholds (named, not magic numbers) ───────────────
# VIX boundaries. Practitioner convention: sub-15 VIX is a calm/complacent
# tape; the 20s are elevated; 30+ is stress; 40+ is full crisis (the GFC
# 2008 and COVID-2020 peaks both blew through 40).
_VIX_CALM = 15.0  # at/below -> eligible for RISK_ON
_VIX_ELEVATED = 25.0  # at/above -> at least RISK_OFF
_VIX_STRESS = 30.0  # at/above + trend break -> CRISIS
_VIX_CRISIS = 40.0  # at/above -> CRISIS outright

# Confidence is clamped to this band — a rule-based classifier should never
# claim certainty (1.0) nor be a coin-flip (< 0.5).
_CONF_MIN = 0.5
_CONF_MAX = 0.95
# VIX points of distance-to-boundary that map to full _CONF_MAX confidence.
# 15 points is roughly one regime band wide, so being a full band away from
# the nearest boundary earns maximum confidence.
_CONF_VIX_SCALE = 15.0

# Hysteresis: a new candidate regime must be observed on this many consecutive
# classify() calls before the detector actually switches to it. Matches the
# IRegimeDetector docstring ("2+ confirming signals before changing regime").
_CONFIRMATIONS_REQUIRED = 2

# Symbols we try, in order, to find the S&P 500 spot price in a snapshot.
# The issue spec names "SPY"; the live oracle publishes "sSPY". We accept
# either so the classifier works against both.
_SP500_PRICE_KEYS = ("SPY", "sSPY")


class VixRegimeDetector:
    """Rule-based VIX + moving-average market-regime classifier.

    Implements ``IRegimeDetector`` (interfaces/math.py): ``classify`` and
    ``get_current_regime``. Stateful across calls — it tracks the previous
    VIX (for rate-of-change), the confirmed regime, and a pending-candidate
    counter for the two-tick hysteresis rule.
    """

    def __init__(self, previous_regime: Regime | None = None) -> None:
        self._confirmed_regime: Regime | None = previous_regime
        self._last_classification: RegimeClassification | None = None
        self._last_vix: float | None = None
        # Hysteresis bookkeeping: the candidate awaiting confirmation and how
        # many consecutive times it has now been seen.
        self._pending_regime: Regime | None = None
        self._pending_count: int = 0

    # ─── IRegimeDetector ─────────────────────────────────────────────

    def classify(self, snapshot: MarketSnapshot) -> RegimeClassification:
        """Classify the current market regime from a snapshot.

        Applies the calibration table to derive a *candidate* regime, then
        the two-tick hysteresis rule to decide whether to adopt it. Returns
        a ``RegimeClassification`` whose ``regime`` is the currently
        *confirmed* regime (which may lag the candidate by up to one tick).
        """
        vix = snapshot.vix if snapshot.vix is not None else 20.0

        above_ma50 = self._above_ma(snapshot, snapshot.sp500_ma50)
        above_ma200 = self._above_ma(snapshot, snapshot.sp500_ma200)

        candidate = self._raw_regime(vix, above_ma50, above_ma200)
        confidence = self._confidence(vix)

        # Hysteresis: only switch the confirmed regime once the candidate has
        # repeated for _CONFIRMATIONS_REQUIRED consecutive calls. The very
        # first classification adopts its candidate immediately (no prior to
        # confirm against).
        previous_confirmed = self._confirmed_regime
        regime_changed = self._apply_hysteresis(candidate)

        signals = RegimeSignals(
            vix_level=vix,
            vix_rate_of_change=self._vix_roc(vix),
            sp500_above_ma50=above_ma50,
            sp500_above_ma200=above_ma200,
            credit_spread_ig=snapshot.credit_spread_ig,
            credit_spread_hy=snapshot.credit_spread_hy,
            btc_dominance=snapshot.btc_dominance,
        )

        classification = RegimeClassification(
            regime=self._confirmed_regime or candidate,
            confidence=round(confidence, 2),
            signals=signals,
            timestamp=datetime.now(UTC),
            previous_regime=previous_confirmed,
            regime_changed=regime_changed,
        )

        self._last_vix = vix
        self._last_classification = classification
        logger.info(
            "Regime: %s (candidate=%s, confidence=%.2f, changed=%s, VIX=%.1f, above_ma50=%s, above_ma200=%s)",
            classification.regime.value,
            candidate.value,
            confidence,
            regime_changed,
            vix,
            above_ma50,
            above_ma200,
        )
        return classification

    def get_current_regime(self) -> RegimeClassification | None:
        """Return the most recent classification, or None if never classified."""
        return self._last_classification

    # ─── Rule table ──────────────────────────────────────────────────

    @staticmethod
    def _raw_regime(vix: float, above_ma50: bool, above_ma200: bool) -> Regime:
        """Map (VIX, MA positioning) to a regime via the calibration table.

        Ordering matters — checks run most-defensive-first so CRISIS wins
        over RISK_OFF when both conditions hold.
        """
        if vix >= _VIX_CRISIS or (vix >= _VIX_STRESS and not above_ma200):
            return Regime.CRISIS
        if vix >= _VIX_ELEVATED or not above_ma200:
            return Regime.RISK_OFF
        if vix <= _VIX_CALM and above_ma50 and above_ma200:
            return Regime.RISK_ON
        return Regime.TRANSITION

    @staticmethod
    def _above_ma(snapshot: MarketSnapshot, ma: float | None) -> bool:
        """Whether the S&P 500 spot trades above a given moving average.

        Returns False when the MA is unavailable or no S&P spot price is in
        the snapshot — a conservative default (treats missing trend data as
        "not confirmed above"), which biases toward the defensive regimes.
        """
        if ma is None:
            return False
        price = 0.0
        for key in _SP500_PRICE_KEYS:
            value = snapshot.prices.get(key)
            if value:
                price = value
                break
        return price > ma

    # ─── Confidence ──────────────────────────────────────────────────

    @staticmethod
    def _confidence(vix: float) -> float:
        """Confidence from the distance between VIX and the nearest boundary.

        The further VIX sits from the closest decision boundary, the more
        confident the classification (a VIX of 12 is unambiguously calm; a
        VIX of 24.9 is a hair from flipping to RISK_OFF). Distance is scaled
        by ``_CONF_VIX_SCALE`` and clamped to [_CONF_MIN, _CONF_MAX].
        """
        boundaries = (_VIX_CALM, _VIX_ELEVATED, _VIX_STRESS, _VIX_CRISIS)
        distance = min(abs(vix - b) for b in boundaries)
        scaled = distance / _CONF_VIX_SCALE
        return max(_CONF_MIN, min(_CONF_MAX, _CONF_MIN + scaled * (_CONF_MAX - _CONF_MIN)))

    def _vix_roc(self, vix: float) -> float:
        """VIX rate of change vs the previously seen VIX (fraction).

        Zero on the first observation (no prior to compare against) or when
        the previous VIX was non-positive.
        """
        if self._last_vix is None or self._last_vix <= 0:
            return 0.0
        return round((vix - self._last_vix) / self._last_vix, 4)

    # ─── Hysteresis ──────────────────────────────────────────────────

    def _apply_hysteresis(self, candidate: Regime) -> bool:
        """Advance the confirmation state machine; return whether regime changed.

        - First-ever classification: adopt the candidate immediately.
        - Candidate equals the confirmed regime: reset any pending switch.
        - Candidate differs: require ``_CONFIRMATIONS_REQUIRED`` consecutive
          observations before adopting it.
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = candidate
            self._pending_regime = None
            self._pending_count = 0
            return False

        if candidate == self._confirmed_regime:
            # Candidate agrees with the status quo — clear any pending switch.
            self._pending_regime = None
            self._pending_count = 0
            return False

        # Candidate disagrees with the confirmed regime.
        if candidate == self._pending_regime:
            self._pending_count += 1
        else:
            self._pending_regime = candidate
            self._pending_count = 1

        if self._pending_count >= _CONFIRMATIONS_REQUIRED:
            self._confirmed_regime = candidate
            self._pending_regime = None
            self._pending_count = 0
            return True

        return False
