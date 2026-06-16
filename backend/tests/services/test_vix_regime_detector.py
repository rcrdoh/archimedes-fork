"""Unit coverage for the VIX/MA rule-based market-regime detector (#660).

Pure-function + small state-machine tests — no I/O, no DB, no network, so the
file runs under the hermetic gate. Covers the calibration table (all four
regimes + the CRISIS-over-RISK_OFF ordering), the distance-to-boundary
confidence band, the MA-positioning helper (missing MA / missing price →
conservative False), the VIX rate-of-change, and the two-tick hysteresis
state machine (first-tick immediate adoption, lag-by-one switch, reset on a
disagreeing candidate, clear on agreement).

Distinct from ``test_regime_detector.py`` (the older 18/25/35 heuristic): this
exercises the refined 15/25/30/40 detector with hysteresis that issue #660
actually wires into the agent runner.
"""

from __future__ import annotations

from datetime import UTC, datetime

from archimedes.models.asset import MarketSnapshot
from archimedes.models.regime import Regime
from archimedes.services.vix_regime_detector import (
    _CONF_MAX,
    _CONF_MIN,
    VixRegimeDetector,
)


def _snapshot(
    *,
    vix: float | None = 20.0,
    sp500_price: float | None = 5000.0,
    ma50: float | None = 4900.0,
    ma200: float | None = 4800.0,
    price_key: str = "sSPY",
) -> MarketSnapshot:
    """Build a minimal MarketSnapshot exercising the detector's inputs."""
    prices: dict[str, float] = {}
    if sp500_price is not None:
        prices[price_key] = sp500_price
    return MarketSnapshot(
        timestamp=datetime.now(UTC),
        prices=prices,
        vix=vix,
        sp500_ma50=ma50,
        sp500_ma200=ma200,
    )


class TestCalibrationTable:
    """The (VIX, MA positioning) → Regime mapping, including precedence."""

    def test_extreme_vix_is_crisis_regardless_of_trend(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=45.0))  # >= 40 → CRISIS outright
        assert cls.regime is Regime.CRISIS

    def test_stress_vix_with_broken_trend_is_crisis(self) -> None:
        det = VixRegimeDetector()
        # VIX >= 30 AND below MA200 → CRISIS (price under the 200-day MA).
        cls = det.classify(_snapshot(vix=32.0, sp500_price=4000.0, ma200=4800.0))
        assert cls.regime is Regime.CRISIS

    def test_stress_vix_with_intact_trend_is_only_risk_off(self) -> None:
        det = VixRegimeDetector()
        # VIX 32 but price ABOVE MA200 → not CRISIS; >= 25 → RISK_OFF.
        cls = det.classify(_snapshot(vix=32.0, sp500_price=5000.0, ma200=4800.0))
        assert cls.regime is Regime.RISK_OFF

    def test_elevated_vix_is_risk_off(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=28.0))  # >= 25 → RISK_OFF
        assert cls.regime is Regime.RISK_OFF

    def test_broken_trend_alone_is_risk_off(self) -> None:
        det = VixRegimeDetector()
        # Calm VIX but price below MA200 → RISK_OFF on the trend break.
        cls = det.classify(_snapshot(vix=20.0, sp500_price=4000.0, ma200=4800.0))
        assert cls.regime is Regime.RISK_OFF

    def test_calm_vix_with_uptrend_is_risk_on(self) -> None:
        det = VixRegimeDetector()
        # VIX <= 15 AND above both MAs → RISK_ON.
        cls = det.classify(_snapshot(vix=12.0, sp500_price=5000.0, ma50=4900.0, ma200=4800.0))
        assert cls.regime is Regime.RISK_ON

    def test_calm_vix_below_ma50_is_transition_not_risk_on(self) -> None:
        det = VixRegimeDetector()
        # VIX calm and above MA200 (so not RISK_OFF) but below MA50 → not
        # RISK_ON (needs both MAs) → TRANSITION.
        cls = det.classify(_snapshot(vix=14.0, sp500_price=4850.0, ma50=4900.0, ma200=4800.0))
        assert cls.regime is Regime.TRANSITION

    def test_mid_vix_intact_trend_is_transition(self) -> None:
        det = VixRegimeDetector()
        # VIX 20 (between calm and elevated), above both MAs → TRANSITION.
        cls = det.classify(_snapshot(vix=20.0, sp500_price=5000.0, ma50=4900.0, ma200=4800.0))
        assert cls.regime is Regime.TRANSITION


class TestConfidence:
    """Confidence is clamped to [_CONF_MIN, _CONF_MAX] and grows with distance."""

    def test_confidence_within_band(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=20.0))
        assert _CONF_MIN <= cls.confidence <= _CONF_MAX

    def test_on_boundary_is_minimum_confidence(self) -> None:
        det = VixRegimeDetector()
        # VIX exactly on a boundary (40) → distance 0 → minimum confidence.
        cls = det.classify(_snapshot(vix=40.0))
        assert cls.confidence == _CONF_MIN

    def test_midband_confidence_value(self) -> None:
        det = VixRegimeDetector()
        # VIX 20 is 5 points from the nearest boundary (15 or 25):
        # 0.5 + (5/15) * (0.95 - 0.5) = 0.65.
        cls = det.classify(_snapshot(vix=20.0))
        assert cls.confidence == 0.65

    def test_far_from_boundary_is_capped(self) -> None:
        det = VixRegimeDetector()
        # VIX 70 is 30 points past the 40 boundary → scaled would exceed 1,
        # so confidence clamps to the max.
        cls = det.classify(_snapshot(vix=70.0))
        assert cls.confidence == _CONF_MAX


class TestMaPositioning:
    """The _above_ma helper degrades conservatively to False."""

    def test_missing_ma_is_not_above(self) -> None:
        det = VixRegimeDetector()
        # ma200 missing → treated as "not above" → trend break → at least RISK_OFF.
        cls = det.classify(_snapshot(vix=12.0, ma200=None))
        assert cls.signals.sp500_above_ma200 is False
        assert cls.regime is Regime.RISK_OFF

    def test_missing_price_is_not_above(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=12.0, sp500_price=None))
        assert cls.signals.sp500_above_ma50 is False
        assert cls.signals.sp500_above_ma200 is False

    def test_accepts_plain_spy_price_key(self) -> None:
        det = VixRegimeDetector()
        # The classifier accepts both "sSPY" (live oracle) and "SPY" (spec).
        cls = det.classify(_snapshot(vix=12.0, sp500_price=5000.0, price_key="SPY"))
        assert cls.signals.sp500_above_ma50 is True
        assert cls.regime is Regime.RISK_ON


class TestVixRateOfChange:
    """VIX RoC is zero on the first tick and a fraction thereafter."""

    def test_first_tick_roc_is_zero(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=20.0))
        assert cls.signals.vix_rate_of_change == 0.0

    def test_subsequent_roc_is_fractional_change(self) -> None:
        det = VixRegimeDetector()
        det.classify(_snapshot(vix=20.0))
        cls = det.classify(_snapshot(vix=22.0))
        # (22 - 20) / 20 = 0.1
        assert cls.signals.vix_rate_of_change == 0.1


class TestHysteresis:
    """The two-tick confirmation state machine."""

    def test_first_classification_adopts_immediately(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=12.0))
        assert cls.regime is Regime.RISK_ON
        assert cls.previous_regime is None
        assert cls.regime_changed is False

    def test_regime_lags_one_tick_before_switching(self) -> None:
        det = VixRegimeDetector()
        det.classify(_snapshot(vix=12.0))  # confirmed RISK_ON
        # First disagreeing tick: candidate is CRISIS but confirmed still lags.
        lagging = det.classify(_snapshot(vix=45.0))
        assert lagging.regime is Regime.RISK_ON
        assert lagging.regime_changed is False
        # Second consecutive CRISIS tick: now it switches.
        switched = det.classify(_snapshot(vix=45.0))
        assert switched.regime is Regime.CRISIS
        assert switched.regime_changed is True
        assert switched.previous_regime is Regime.RISK_ON

    def test_disagreeing_candidate_resets_pending_count(self) -> None:
        det = VixRegimeDetector()
        det.classify(_snapshot(vix=12.0))  # confirmed RISK_ON
        det.classify(_snapshot(vix=45.0))  # pending CRISIS, count 1
        # A different candidate (RISK_OFF) resets the pending switch...
        det.classify(_snapshot(vix=28.0, sp500_price=5000.0))  # pending RISK_OFF, count 1
        # ...so a single later CRISIS tick is only count 1 again, no switch.
        still = det.classify(_snapshot(vix=45.0))
        assert still.regime is Regime.RISK_ON
        assert still.regime_changed is False

    def test_agreement_clears_pending_switch(self) -> None:
        det = VixRegimeDetector()
        det.classify(_snapshot(vix=12.0))  # confirmed RISK_ON
        det.classify(_snapshot(vix=45.0))  # pending CRISIS, count 1
        det.classify(_snapshot(vix=12.0))  # candidate == confirmed → clears pending
        # One CRISIS tick after a clear is only count 1 → still no switch.
        still = det.classify(_snapshot(vix=45.0))
        assert still.regime is Regime.RISK_ON
        assert still.regime_changed is False


class TestGetCurrentRegime:
    """get_current_regime returns the latest classification, or None."""

    def test_none_before_first_classify(self) -> None:
        det = VixRegimeDetector()
        assert det.get_current_regime() is None

    def test_returns_latest_after_classify(self) -> None:
        det = VixRegimeDetector()
        cls = det.classify(_snapshot(vix=12.0))
        assert det.get_current_regime() is cls

    def test_seeded_previous_regime_enables_immediate_hysteresis(self) -> None:
        # Seeding a prior confirmed regime means the first disagreeing tick
        # does NOT adopt immediately — it must clear the two-tick gate.
        det = VixRegimeDetector(previous_regime=Regime.RISK_ON)
        lagging = det.classify(_snapshot(vix=45.0))
        assert lagging.regime is Regime.RISK_ON
        assert lagging.regime_changed is False
