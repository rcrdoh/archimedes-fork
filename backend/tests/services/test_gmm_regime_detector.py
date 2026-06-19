"""Unit coverage for the GMM market-regime detector (#661).

Hermetic by construction: NO yfinance, NO network, NO pickle-on-disk, NO DB.
We synthesize 4 well-separated Gaussian blobs in the 4-feature space
(vix_level, vix_21d_chg, realized_vol_21d, return_21d) whose VIX / return means
correspond to the four regimes, fit on those, and exercise:

  * fit_gmm_model labelling — all four regimes assigned; the high-VIX(>35) blob
    → CRISIS; the calm low-VIX positive-return blob → RISK_ON.
  * classify on the GMM path (fitted model + sufficient synthetic buffer) →
    plausible regime, confidence in [0.5, 0.95].
  * classify fallback when there is no model (nonexistent path) → delegates to a
    stub fallback and returns its sentinel verbatim.
  * classify fallback when history is too short → same delegation.
  * get_current_regime → None before any call, last classification after.
  * hysteresis on the GMM path — one contrary tick does NOT flip until confirmed.
  * load_gmm_model on a missing path → None (no raise).

Distinct from ``test_statistical_regime.py`` (the scipy 2-component online-EM
model) and ``test_vix_regime_detector.py`` (the rule-based fallback).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from archimedes.models.asset import MarketSnapshot
from archimedes.models.regime import Regime, RegimeClassification, RegimeSignals
from archimedes.services.gmm_regime_detector import (
    _CONF_MAX,
    _CONF_MIN,
    _MIN_HISTORY,
    FittedGmm,
    GmmRegimeDetector,
    fit_gmm_model,
    load_gmm_model,
)

# A path that never exists → load_gmm_model returns None → detector falls back.
_NONEXISTENT_MODEL = Path("/nonexistent/archimedes-gmm-test-does-not-exist.pkl")

# Per-blob centers in ORIGINAL feature space:
#   [vix_level, vix_21d_chg, realized_vol_21d, return_21d]
# Chosen well-separated so the GMM recovers the four clusters deterministically.
#   RISK_ON     : low VIX, falling VIX, low vol, positive return
#   TRANSITION  : mid VIX, flat VIX, mid vol, slightly negative return
#   RISK_OFF    : elevated VIX, rising VIX, high vol, negative return
#   CRISIS      : extreme VIX (> 35), spiking VIX, very high vol, deeply negative
_BLOB_CENTERS = {
    Regime.RISK_ON: np.array([12.0, -0.10, 0.10, 0.05]),
    Regime.TRANSITION: np.array([20.0, 0.00, 0.18, -0.01]),
    Regime.RISK_OFF: np.array([28.0, 0.20, 0.28, -0.05]),
    Regime.CRISIS: np.array([50.0, 0.60, 0.55, -0.20]),
}
# Small, tight per-feature spread so blobs do not overlap.
_BLOB_STD = np.array([1.5, 0.03, 0.02, 0.01])
_SAMPLES_PER_BLOB = 150


def _make_synthetic_features(seed: int = 7) -> tuple[np.ndarray, dict[Regime, np.ndarray]]:
    """Return an (N, 4) synthetic feature matrix + the per-regime center map.

    Four labelled Gaussian blobs, stacked. A fixed seed makes the fit
    deterministic across runs.
    """
    rng = np.random.default_rng(seed)
    blocks: list[np.ndarray] = []
    for center in _BLOB_CENTERS.values():
        block = rng.normal(loc=center, scale=_BLOB_STD, size=(_SAMPLES_PER_BLOB, 4))
        blocks.append(block)
    features = np.vstack(blocks)
    return features, dict(_BLOB_CENTERS)


def _fit_synthetic() -> FittedGmm:
    features, _ = _make_synthetic_features()
    return fit_gmm_model(features, random_state=42)


def _predict_regime(fitted: FittedGmm, point: np.ndarray) -> Regime:
    """Map a single original-space feature point to its GMM regime label."""
    scaled = fitted.scaler.transform(point.reshape(1, -1))
    component = int(np.argmax(fitted.gmm.predict_proba(scaled)[0]))
    return fitted.component_to_regime[component]


def _snapshot(*, vix: float, spy_price: float, ma50: float = 4900.0, ma200: float = 4800.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime.now(UTC),
        prices={"sSPY": spy_price},
        vix=vix,
        sp500_ma50=ma50,
        sp500_ma200=ma200,
    )


def _gmm_buffer(n: int = _MIN_HISTORY + 4, *, start_vix: float = 12.0, start_spy: float = 5000.0) -> list:
    """A calm, low-vol synthetic (vix, spy) history → lands in the RISK_ON blob.

    A gentle upward SPY drift with a tiny wobble and a flat-to-falling VIX
    produces features near the RISK_ON center (low VIX, low realized vol,
    positive 21-day return).
    """
    history = []
    for i in range(n):
        vix = start_vix - 0.02 * i  # very slowly falling VIX
        spy = start_spy * (1.0 + 0.0015 * i)  # gentle uptrend, ~0.15%/day
        history.append((vix, spy))
    return history


@dataclass(frozen=True)
class _SentinelFallback:
    """A tiny IRegimeDetector stub returning a fixed sentinel classification."""

    sentinel: RegimeClassification

    def classify(self, snapshot: MarketSnapshot) -> RegimeClassification:
        del snapshot  # stub ignores input; sentinel is fixed
        return self.sentinel

    def get_current_regime(self) -> RegimeClassification | None:
        return self.sentinel


def _sentinel_classification() -> RegimeClassification:
    return RegimeClassification(
        regime=Regime.TRANSITION,
        confidence=0.55,
        signals=RegimeSignals(
            vix_level=99.0,  # an obviously-distinctive marker value
            vix_rate_of_change=0.0,
            sp500_above_ma50=True,
            sp500_above_ma200=True,
        ),
        timestamp=datetime.now(UTC),
    )


class TestFitGmmModel:
    """fit_gmm_model on synthetic data assigns all four regimes correctly."""

    def test_assigns_all_four_regimes(self) -> None:
        fitted = _fit_synthetic()
        assert len(fitted.component_to_regime) == 4
        assert set(fitted.component_to_regime.values()) == {
            Regime.RISK_ON,
            Regime.RISK_OFF,
            Regime.TRANSITION,
            Regime.CRISIS,
        }

    def test_high_vix_blob_is_crisis(self) -> None:
        fitted = _fit_synthetic()
        crisis_point = _BLOB_CENTERS[Regime.CRISIS]
        assert _predict_regime(fitted, crisis_point) is Regime.CRISIS

    def test_calm_positive_return_blob_is_risk_on(self) -> None:
        fitted = _fit_synthetic()
        risk_on_point = _BLOB_CENTERS[Regime.RISK_ON]
        assert _predict_regime(fitted, risk_on_point) is Regime.RISK_ON

    def test_fit_is_deterministic(self) -> None:
        # Same input + random_state → identical labelling map.
        first = _fit_synthetic()
        second = _fit_synthetic()
        assert first.component_to_regime == second.component_to_regime

    def test_wrong_feature_shape_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="features must be"):
            fit_gmm_model(np.zeros((10, 3)))


class TestGmmClassifyPath:
    """classify on the GMM path with a fitted model + sufficient buffer."""

    def test_returns_plausible_regime_and_confidence(self) -> None:
        fitted = _fit_synthetic()
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL, seed_history=_gmm_buffer())
        det._model = fitted  # inject the in-memory fit (no pickle-on-disk)

        result = det.classify(_snapshot(vix=12.0, spy_price=5100.0))
        assert isinstance(result.regime, Regime)
        assert _CONF_MIN <= result.confidence <= _CONF_MAX

    def test_calm_buffer_classifies_risk_on(self) -> None:
        fitted = _fit_synthetic()
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL, seed_history=_gmm_buffer())
        det._model = fitted
        # The seeded calm/low-vol/up-trending history → RISK_ON blob.
        result = det.classify(_snapshot(vix=11.5, spy_price=5200.0))
        assert result.regime is Regime.RISK_ON

    def test_signals_are_populated(self) -> None:
        fitted = _fit_synthetic()
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL, seed_history=_gmm_buffer())
        det._model = fitted
        result = det.classify(_snapshot(vix=12.0, spy_price=5100.0))
        assert result.signals.vix_level == 12.0
        assert isinstance(result.signals.sp500_above_ma50, bool)
        assert isinstance(result.signals.sp500_above_ma200, bool)


class TestFallbackDelegation:
    """classify delegates to the fallback when the GMM path is ineligible."""

    def test_no_model_delegates_to_fallback(self) -> None:
        sentinel = _sentinel_classification()
        det = GmmRegimeDetector(
            model_path=_NONEXISTENT_MODEL,  # → load returns None → no model
            fallback=_SentinelFallback(sentinel),
            seed_history=_gmm_buffer(),  # plenty of history, but no model
        )
        assert det._model is None
        result = det.classify(_snapshot(vix=12.0, spy_price=5100.0))
        assert result is sentinel

    def test_insufficient_history_delegates_to_fallback(self) -> None:
        sentinel = _sentinel_classification()
        det = GmmRegimeDetector(
            model_path=_NONEXISTENT_MODEL,
            fallback=_SentinelFallback(sentinel),
            seed_history=None,  # empty buffer → far below _MIN_HISTORY
        )
        det._model = _fit_synthetic()  # model present, but history too short
        result = det.classify(_snapshot(vix=12.0, spy_price=5100.0))
        assert result is sentinel

    def test_missing_vix_delegates_to_fallback(self) -> None:
        sentinel = _sentinel_classification()
        det = GmmRegimeDetector(
            model_path=_NONEXISTENT_MODEL,
            fallback=_SentinelFallback(sentinel),
            seed_history=_gmm_buffer(),
        )
        det._model = _fit_synthetic()
        snap = MarketSnapshot(timestamp=datetime.now(UTC), prices={"sSPY": 5100.0}, vix=None)
        result = det.classify(snap)
        assert result is sentinel

    def test_default_fallback_is_vix_detector(self) -> None:
        from archimedes.services.vix_regime_detector import VixRegimeDetector

        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL)
        assert isinstance(det._fallback, VixRegimeDetector)


class TestGetCurrentRegime:
    """get_current_regime tracks the last classification."""

    def test_none_before_first_classify(self) -> None:
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL)
        assert det.get_current_regime() is None

    def test_returns_latest_after_classify(self) -> None:
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL)  # fallback path
        result = det.classify(_snapshot(vix=12.0, spy_price=5100.0))
        assert det.get_current_regime() is result


class TestHysteresis:
    """A one-off contrary GMM classification does not flip the regime."""

    def test_single_contrary_tick_does_not_flip(self) -> None:
        fitted = _fit_synthetic()
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL, seed_history=_gmm_buffer())
        det._model = fitted

        # First tick on the calm buffer confirms RISK_ON.
        first = det.classify(_snapshot(vix=11.5, spy_price=5300.0))
        assert first.regime is Regime.RISK_ON

        # Inject ONE crisis-like observation, then classify: the candidate may
        # be CRISIS/RISK_OFF but the confirmed regime must still lag (no flip
        # on a single contrary tick).
        det._buffer.append((55.0, 4200.0))  # one violent spike
        lagging = det.classify(_snapshot(vix=55.0, spy_price=4200.0))
        assert lagging.regime is Regime.RISK_ON
        assert lagging.regime_changed is False

    def test_confirmed_flip_after_two_contrary_ticks(self) -> None:
        fitted = _fit_synthetic()
        det = GmmRegimeDetector(model_path=_NONEXISTENT_MODEL, seed_history=_gmm_buffer())
        det._model = fitted
        det.classify(_snapshot(vix=11.5, spy_price=5300.0))  # confirm RISK_ON

        # Drive the buffer firmly into the crisis blob with sustained spikes so
        # the candidate is a consistent non-RISK_ON regime for two ticks.
        for _ in range(8):
            det._buffer.append((52.0, 4000.0))
        t1 = det.classify(_snapshot(vix=52.0, spy_price=4000.0))
        for _ in range(2):
            det._buffer.append((52.0, 4000.0))
        t2 = det.classify(_snapshot(vix=52.0, spy_price=4000.0))

        # By the second sustained contrary tick the regime has switched away
        # from RISK_ON (the exact target regime depends on the fitted mapping,
        # but it must no longer be RISK_ON and the change must be flagged once).
        assert t2.regime is not Regime.RISK_ON
        assert t1.regime_changed is True or t2.regime_changed is True


class TestLoadGmmModel:
    """load_gmm_model never raises on a bad path."""

    def test_missing_path_returns_none(self) -> None:
        assert load_gmm_model(_NONEXISTENT_MODEL) is None

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        bad = tmp_path / "corrupt.pkl"
        bad.write_bytes(b"not a valid pickle stream \x00\x01\x02")
        assert load_gmm_model(bad) is None

    def test_non_fittedgmm_pickle_returns_none(self, tmp_path: Path) -> None:
        import pickle

        wrong = tmp_path / "wrong.pkl"
        with wrong.open("wb") as fh:
            pickle.dump({"not": "a FittedGmm"}, fh)
        assert load_gmm_model(wrong) is None
