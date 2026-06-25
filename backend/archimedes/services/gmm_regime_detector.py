"""GMM market-regime detector — data-driven ``IRegimeDetector`` (issue #661).

A statistically-principled drop-in for the rule-based ``VixRegimeDetector``.
It fits a 4-component sklearn Gaussian Mixture over a 4-feature vector and
labels each latent component as one of the four market regimes (RISK_ON /
RISK_OFF / TRANSITION / CRISIS) by inspecting the component means in the
ORIGINAL feature space.

Basis. Regime-switching models of financial returns are a long-standing tool:
Hamilton 1989 ("A New Approach to the Economic Analysis of Nonstationary Time
Series and the Business Cycle", Econometrica) introduced Markov-switching
regimes; Ang & Bekaert 2002 ("International Asset Allocation With Regime
Shifts", RFS) showed regime structure in volatility/correlation. A Gaussian
Mixture is the unconditional (no Markov transition) cousin: each regime is a
Gaussian cluster in feature space, and posterior responsibilities give a
soft regime probability. We deliberately keep transition dynamics out of scope
— this is a clustering classifier with hysteresis layered on for stability.

HONEST FALLBACK. A meaningful fit needs ≥504 trading days (~2y) of real
``^VIX`` + ``SPY`` data. We never fetch that in tests or CI and never commit a
fitted artifact. So when no fitted model is present, OR the rolling history is
too short, OR the snapshot lacks VIX/price, the detector delegates verbatim to
a ``VixRegimeDetector`` fallback. The real model is produced offline by
``scripts/fit_gmm_regime.py`` and written to ``DEFAULT_GMM_MODEL_PATH`` (which
is git-ignored). Until that artifact exists, this detector behaves exactly like
the rule-based one — no fabricated model, no fake data.

Owner: Önder (portfolio math + risk pricing); coverage: Dan.
Design reference: IRegimeDetector docstring (math.py); VixRegimeDetector (the
fallback + structural template).
"""

from __future__ import annotations

import logging
import pickle
import weakref
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from archimedes.interfaces.math import IRegimeDetector
from archimedes.models.asset import MarketSnapshot
from archimedes.models.regime import (
    Regime,
    RegimeClassification,
    RegimeSignals,
)
from archimedes.services.vix_regime_detector import VixRegimeDetector

logger = logging.getLogger(__name__)

# ─── Module constants (named, not magic numbers) ─────────────────────
# Where the offline-fitted artifact lives. Data-derived + stale-prone, so it is
# git-ignored (see .gitignore) and produced only by scripts/fit_gmm_regime.py.
DEFAULT_GMM_MODEL_PATH = Path(__file__).parent / "gmm_model.pkl"

# Feature engineering windows. 21 trading days ≈ one calendar month — the
# standard short-horizon momentum/volatility window in the regime-switching
# literature (Ang & Bekaert 2002 use monthly observations).
_FEATURE_WINDOW = 21  # lookback (in days) for changes / realized vol
# We need WINDOW+1 observations to compute a 21-day change (t and t-21), so the
# rolling buffer must hold at least 22 points before the GMM path is eligible.
_MIN_HISTORY = _FEATURE_WINDOW + 1  # = 22

# GaussianMixture configuration. Four components ↔ four regimes; "full"
# covariance lets each regime have its own feature correlation structure.
_N_COMPONENTS = 4

# Annualization factor for daily realized volatility (252 trading days/yr).
_TRADING_DAYS_PER_YEAR = 252

# Hysteresis: a new candidate regime must repeat on this many consecutive
# classify() calls before being adopted — matches the IRegimeDetector contract
# ("2+ confirming signals before changing regime") and VixRegimeDetector.
_CONFIRMATIONS_REQUIRED = 2

# Posterior-probability confidence is clamped to this band: a soft classifier
# should never claim certainty (1.0) nor be a coin-flip (< 0.5).
_CONF_MIN = 0.5
_CONF_MAX = 0.95

# Component-labelling thresholds (in ORIGINAL feature space). A component whose
# mean VIX exceeds this is full-crisis rather than merely defensive — the GFC
# 2008 and COVID 2020 peaks both blew through 35.
_CRISIS_VIX_THRESHOLD = 35.0

# Rolling buffer of recent (vix, spy_price) observations. 64 > _MIN_HISTORY so a
# few short ticks at startup still warm up toward the GMM-eligible threshold.
_BUFFER_MAXLEN = 64

# Feature vector layout (THIS EXACT ORDER, everywhere — fit and inference):
#   0: vix_level         — the raw VIX level
#   1: vix_21d_chg       — (vix_t - vix_{t-21}) / vix_{t-21}
#   2: realized_vol_21d  — std(spy_daily_returns[-21:]) * sqrt(252)
#   3: return_21d        — (spy_t - spy_{t-21}) / spy_{t-21}
_FEATURE_NAMES = ("vix_level", "vix_21d_chg", "realized_vol_21d", "return_21d")
_IDX_VIX = 0
_IDX_RETURN = 3

# Symbols we try, in order, to find the S&P 500 spot price in a snapshot —
# matches VixRegimeDetector ("sSPY" is the live oracle key; "SPY" is the spec).
_SP500_PRICE_KEYS = ("SPY", "sSPY")


@dataclass(frozen=True)
class FittedGmm:
    """A fitted GMM regime model: scaler + mixture + component→regime mapping.

    ``scaler`` standardizes raw features; ``gmm`` is fit on the scaled features;
    ``component_to_regime`` maps each of the ``_N_COMPONENTS`` latent component
    indices to a ``Regime``. All three are needed at inference time.
    """

    scaler: StandardScaler
    gmm: GaussianMixture
    component_to_regime: dict[int, Regime]


@dataclass(frozen=True)
class GmmRegimeHealth:
    """Health diagnostic for the GMM regime detector subsystem (T0.5).

    Mirrors ``PaperRAGHealth`` so ``/health`` can surface GMM degradation the
    same way it surfaces the paper-RAG TF-IDF fallback.
    """

    status: str  # live | degraded
    reason: str = ""


# Weak reference to the most-recently-constructed detector, so the module-level
# ``gmm_regime_health()`` probe used by ``/health`` can report the live
# instance's state without the request handler needing a handle on the agent
# runner. A weakref avoids pinning a detector alive past its natural lifetime.
_LAST_DETECTOR: weakref.ReferenceType[GmmRegimeDetector] | None = None


def _register_detector(detector: GmmRegimeDetector) -> None:
    """Record the newest detector instance for the health probe."""
    global _LAST_DETECTOR
    _LAST_DETECTOR = weakref.ref(detector)


def gmm_regime_health() -> GmmRegimeHealth:
    """Report GMM regime-detector health for ``/health`` (T0.5).

    - ``live``: a fitted GMM artifact is loaded → data-driven regime calls.
    - ``degraded``: no fitted artifact → every classify delegates to the
      rule-based ``VixRegimeDetector`` fallback. This is the expected steady
      state until ``scripts/fit_gmm_regime.py`` produces an artifact, but it
      MUST be visible rather than silent: rule-based calls would otherwise be
      presented as if the data-driven model were live.

    Probes the most-recently-constructed detector if one exists; otherwise
    checks the default artifact path directly so the flag is meaningful even
    before any detector is instantiated (e.g. a cold ``/health`` hit).
    """
    detector = _LAST_DETECTOR() if _LAST_DETECTOR is not None else None
    if detector is not None:
        return detector.health()
    if DEFAULT_GMM_MODEL_PATH.exists():
        return GmmRegimeHealth(status="live", reason="data-driven GMM regime model present")
    return GmmRegimeHealth(
        status="degraded",
        reason=f"no fitted GMM model at {DEFAULT_GMM_MODEL_PATH} — rule-based fallback active",
    )


def _label_components(scaler: StandardScaler, gmm: GaussianMixture) -> dict[int, Regime]:
    """Deterministically map each latent component to a ``Regime``.

    Components are unlabelled after fitting; we assign meaning by inspecting
    each component's mean in the ORIGINAL feature space (via
    ``scaler.inverse_transform``). The rule (deterministic; covers all four):

      1. Highest VIX-mean component → CRISIS if that VIX-mean > 35, else RISK_OFF.
      2. Among the remaining components, the lowest VIX-mean one is the calm
         regime: RISK_ON if its 21-day-return mean is positive, else TRANSITION.
      3. Any still-unassigned components are labelled by DESCENDING VIX-mean,
         alternating RISK_OFF then TRANSITION, so higher-vol leftovers skew
         defensive. This guarantees every component gets exactly one label.
    """
    means_original = scaler.inverse_transform(gmm.means_)
    vix_means = means_original[:, _IDX_VIX]
    return_means = means_original[:, _IDX_RETURN]

    order_by_vix_desc = list(np.argsort(vix_means)[::-1])  # highest VIX first
    mapping: dict[int, Regime] = {}

    # 1. Highest-VIX component → CRISIS (if extreme) else RISK_OFF.
    crisis_idx = order_by_vix_desc[0]
    mapping[crisis_idx] = Regime.CRISIS if vix_means[crisis_idx] > _CRISIS_VIX_THRESHOLD else Regime.RISK_OFF

    # 2. Lowest-VIX remaining component → calm regime (RISK_ON / TRANSITION by
    #    the sign of its mean 21-day return).
    remaining = [c for c in order_by_vix_desc if c not in mapping]
    calm_idx = min(remaining, key=lambda c: vix_means[c])
    mapping[calm_idx] = Regime.RISK_ON if return_means[calm_idx] >= 0 else Regime.TRANSITION

    # 3. Assign anything left by descending VIX-mean, alternating defensive
    #    (RISK_OFF) then mixed (TRANSITION). Deterministic given the sort.
    leftovers = [c for c in order_by_vix_desc if c not in mapping]
    alternating = (Regime.RISK_OFF, Regime.TRANSITION)
    for i, comp in enumerate(leftovers):
        mapping[comp] = alternating[i % len(alternating)]

    return mapping


def fit_gmm_model(features: np.ndarray, random_state: int = 42) -> FittedGmm:
    """Fit the GMM regime model on a 4-feature matrix. Pure — no I/O.

    ``features`` is an ``(n_samples, 4)`` array in the documented
    ``_FEATURE_NAMES`` order. Standardizes the features, fits a 4-component
    full-covariance Gaussian Mixture, then labels the components.

    ``random_state`` is threaded into ``GaussianMixture`` so a given input
    matrix yields a deterministic fit (and hence a deterministic labelling).
    """
    features = np.asarray(features, dtype=float)
    if features.ndim != 2 or features.shape[1] != len(_FEATURE_NAMES):
        raise ValueError(f"features must be (n_samples, {len(_FEATURE_NAMES)}), got {features.shape}")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    gmm = GaussianMixture(
        n_components=_N_COMPONENTS,
        covariance_type="full",
        random_state=random_state,
    )
    gmm.fit(scaled)

    mapping = _label_components(scaler, gmm)
    return FittedGmm(scaler=scaler, gmm=gmm, component_to_regime=mapping)


def save_gmm_model(fitted: FittedGmm, path: Path) -> None:
    """Pickle a ``FittedGmm`` to ``path`` (creating parent dirs as needed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(fitted, fh)
    logger.info("Saved fitted GMM regime model to %s", path)


def load_gmm_model(path: Path) -> FittedGmm | None:
    """Load a ``FittedGmm`` from ``path``; return None on missing/corrupt file.

    Never raises — a missing artifact is the expected steady state (it is
    git-ignored and produced offline), and a corrupt one should degrade to the
    rule-based fallback rather than crash the agent runner.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            obj = pickle.load(fh)
    except Exception as exc:  # corrupt pickle, version skew, truncated file…
        logger.warning("Could not load GMM model from %s (%s) — using fallback", path, exc)
        return None
    if not isinstance(obj, FittedGmm):
        logger.warning("File at %s is not a FittedGmm — using fallback", path)
        return None
    return obj


class GmmRegimeDetector:
    """Data-driven GMM market-regime classifier with a rule-based fallback.

    Implements ``IRegimeDetector`` (interfaces/math.py): ``classify`` and
    ``get_current_regime``. Maintains a rolling buffer of recent
    ``(vix, spy_price)`` observations from which the 4-feature vector is built.

    When no fitted model is loaded, OR the buffer is shorter than
    ``_MIN_HISTORY``, OR the snapshot lacks VIX/price, ``classify`` delegates to
    ``self._fallback`` (a ``VixRegimeDetector`` by default). Otherwise it runs
    the GMM path: build features → scale → ``predict_proba`` → argmax component
    → regime via the fitted mapping, with the same two-tick hysteresis the
    fallback uses.
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_GMM_MODEL_PATH,
        fallback: IRegimeDetector | None = None,
        seed_history: list[tuple[float, float]] | None = None,
    ) -> None:
        self._model: FittedGmm | None = load_gmm_model(model_path)
        self._model_path = Path(model_path)
        self._fallback: IRegimeDetector = fallback or VixRegimeDetector()
        # Rolling (vix, spy_price) buffer, optionally pre-seeded for tests / warm
        # starts. maxlen caps memory; we only ever read the trailing window.
        self._buffer: deque[tuple[float, float]] = deque(maxlen=_BUFFER_MAXLEN)
        if seed_history:
            self._buffer.extend(seed_history)
        # Hysteresis bookkeeping for the GMM path (mirrors VixRegimeDetector).
        self._confirmed_regime: Regime | None = None
        self._pending_regime: Regime | None = None
        self._pending_count: int = 0
        self._last: RegimeClassification | None = None
        # ── Loud-fallback telemetry (T0.5) ───────────────────────────
        # The detector silently delegating to the rule-based fallback is a
        # claim-integrity issue: the product would present rule-based regime
        # calls as if the data-driven GMM were live. We track the degradation
        # explicitly so /health can surface it, and we WARN once-per-reason so
        # the log carries the structured signal without spamming on every tick.
        self._fallback_warned: set[str] = set()
        if self._model is None:
            self._warn_fallback(
                "no_fitted_model",
                f"GMM regime model artifact absent at {self._model_path} — "
                "delegating to rule-based VixRegimeDetector fallback",
            )
        # Register as the most-recently-constructed detector so the module-level
        # gmm_regime_health() probe (used by /health) can report live state.
        _register_detector(self)

    def _warn_fallback(self, reason: str, detail: str) -> None:
        """Emit a structured WARN for a fallback/degradation, once per reason.

        ``reason`` is a stable machine key (logged as ``fallback_reason``) so
        downstream log search can pivot on it; ``detail`` is the human message.
        Deduped per detector instance so a per-tick fallback path warns once,
        not on every ``classify`` call.
        """
        if reason in self._fallback_warned:
            return
        self._fallback_warned.add(reason)
        logger.warning(
            "GMM regime detector degraded — silent fallback averted: %s",
            detail,
            extra={
                "event": "gmm_regime_fallback",
                "fallback_reason": reason,
                "detector": "GmmRegimeDetector",
            },
        )

    @property
    def is_degraded(self) -> bool:
        """True when no fitted GMM model is loaded (rule-based fallback active).

        This is the steady-state degradation signal: with no offline-fitted
        artifact present, *every* ``classify`` call delegates to the rule-based
        fallback, so the data-driven detector is not actually live.
        """
        return self._model is None

    def health(self) -> GmmRegimeHealth:
        """Per-instance health diagnostic (live | degraded)."""
        if self._model is None:
            return GmmRegimeHealth(
                status="degraded",
                reason=f"no fitted GMM model at {self._model_path} — rule-based fallback active",
            )
        return GmmRegimeHealth(status="live", reason="data-driven GMM regime model loaded")

    # ─── IRegimeDetector ─────────────────────────────────────────────

    def classify(self, snapshot: MarketSnapshot) -> RegimeClassification:
        """Classify the current market regime, GMM path or fallback.

        Always appends the snapshot's (vix, spy_price) to the rolling buffer
        first (so history accumulates even while we fall back), then chooses the
        path. The returned classification's ``regime`` is the *confirmed*
        regime on the GMM path (post-hysteresis); on the fallback path it is
        whatever the fallback returns, verbatim.
        """
        vix = snapshot.vix
        spy_price = self._spy_price(snapshot)

        # Accumulate history regardless of which path we take.
        if vix is not None and spy_price is not None:
            self._buffer.append((float(vix), float(spy_price)))

        # ── Fallback conditions ──────────────────────────────────────
        if self._model is None or vix is None or spy_price is None or len(self._buffer) < _MIN_HISTORY:
            self._warn_fallback(
                self._fallback_reason(vix, spy_price),
                "classify() delegated to rule-based VixRegimeDetector "
                f"(model_loaded={self._model is not None}, vix={vix is not None}, "
                f"spy_price={spy_price is not None}, history={len(self._buffer)}/{_MIN_HISTORY})",
            )
            result = self._fallback.classify(snapshot)
            self._last = result
            return result

        # ── GMM path ─────────────────────────────────────────────────
        features = self._build_features()
        scaled = self._model.scaler.transform(features.reshape(1, -1))
        proba = self._model.gmm.predict_proba(scaled)[0]
        component = int(np.argmax(proba))
        candidate = self._model.component_to_regime.get(component, Regime.TRANSITION)
        confidence = self._confidence(float(proba[component]))

        previous_confirmed = self._confirmed_regime
        regime_changed = self._apply_hysteresis(candidate)

        signals = RegimeSignals(
            vix_level=float(vix),
            vix_rate_of_change=float(features[1]),  # the 21-day VIX change
            sp500_above_ma50=self._above_ma(snapshot.sp500_ma50, spy_price),
            sp500_above_ma200=self._above_ma(snapshot.sp500_ma200, spy_price),
            credit_spread_ig=snapshot.credit_spread_ig,
            credit_spread_hy=snapshot.credit_spread_hy,
            btc_dominance=snapshot.btc_dominance,
        )

        result = RegimeClassification(
            regime=self._confirmed_regime or candidate,
            confidence=round(confidence, 2),
            signals=signals,
            timestamp=datetime.now(UTC),
            previous_regime=previous_confirmed,
            regime_changed=regime_changed,
        )
        self._last = result
        logger.info(
            "GMM regime: %s (candidate=%s, component=%d, confidence=%.2f, changed=%s, VIX=%.1f)",
            result.regime.value,
            candidate.value,
            component,
            confidence,
            regime_changed,
            vix,
        )
        return result

    def get_current_regime(self) -> RegimeClassification | None:
        """Return the most recent classification, or None if never classified."""
        return self._last

    # ─── Feature engineering ─────────────────────────────────────────

    def _build_features(self) -> np.ndarray:
        """Build the 4-feature vector from the trailing buffer window.

        Reads the last ``_MIN_HISTORY`` observations. Layout follows
        ``_FEATURE_NAMES`` exactly. Assumes ``len(self._buffer) >= _MIN_HISTORY``
        (the caller guarantees this).
        """
        window = list(self._buffer)[-_MIN_HISTORY:]
        vix_series = np.array([v for v, _ in window], dtype=float)
        spy_series = np.array([p for _, p in window], dtype=float)

        vix_now = vix_series[-1]
        vix_then = vix_series[0]  # _FEATURE_WINDOW days ago
        spy_now = spy_series[-1]
        spy_then = spy_series[0]

        vix_21d_chg = (vix_now - vix_then) / vix_then if vix_then else 0.0
        return_21d = (spy_now - spy_then) / spy_then if spy_then else 0.0

        # Daily SPY returns across the window → annualized realized vol.
        daily_returns = np.diff(spy_series) / spy_series[:-1]
        realized_vol_21d = float(np.std(daily_returns) * np.sqrt(_TRADING_DAYS_PER_YEAR))

        return np.array([vix_now, vix_21d_chg, realized_vol_21d, return_21d], dtype=float)

    def _fallback_reason(self, vix: float | None, spy_price: float | None) -> str:
        """Stable machine key naming WHY the GMM path was skipped this tick."""
        if self._model is None:
            return "no_fitted_model"
        if vix is None or spy_price is None:
            return "missing_market_data"
        return "insufficient_history"

    @staticmethod
    def _spy_price(snapshot: MarketSnapshot) -> float | None:
        """Find the S&P 500 spot price under either accepted key, or None."""
        for key in _SP500_PRICE_KEYS:
            value = snapshot.prices.get(key)
            if value:
                return float(value)
        return None

    @staticmethod
    def _above_ma(ma: float | None, spy_price: float) -> bool:
        """Whether SPY trades above a given MA (False when the MA is missing)."""
        if ma is None:
            return False
        return spy_price > ma

    # ─── Confidence ──────────────────────────────────────────────────

    @staticmethod
    def _confidence(posterior: float) -> float:
        """Clamp the max posterior responsibility to [_CONF_MIN, _CONF_MAX]."""
        return max(_CONF_MIN, min(_CONF_MAX, posterior))

    # ─── Hysteresis (mirrors VixRegimeDetector) ──────────────────────

    def _apply_hysteresis(self, candidate: Regime) -> bool:
        """Advance the confirmation state machine; return whether regime changed.

        - First-ever GMM classification: adopt the candidate immediately.
        - Candidate equals the confirmed regime: clear any pending switch.
        - Candidate differs: require ``_CONFIRMATIONS_REQUIRED`` consecutive
          observations before adopting it.
        """
        if self._confirmed_regime is None:
            self._confirmed_regime = candidate
            self._pending_regime = None
            self._pending_count = 0
            return False

        if candidate == self._confirmed_regime:
            self._pending_regime = None
            self._pending_count = 0
            return False

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
