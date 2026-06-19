"""Offline trainer for the GMM market-regime detector (issue #661).

NOT run in CI and NOT imported by the app at runtime — it needs network access
(yfinance) and writes a git-ignored pickle. This is the ONLY place the fitted
``gmm_model.pkl`` artifact is produced; the runtime detector
(``GmmRegimeDetector``) loads that artifact and otherwise falls back to the
rule-based ``VixRegimeDetector``.

What it does:
  1. Fetch ~2 years of daily ``^VIX`` and ``SPY`` closes via yfinance.
  2. Build the daily 4-feature matrix (vix_level, vix_21d_chg,
     realized_vol_21d, return_21d) — the SAME order the detector uses —
     producing ≥504 rows.
  3. Fit the 4-component GMM via ``fit_gmm_model`` (the shared pure function).
  4. Save it to ``DEFAULT_GMM_MODEL_PATH``.

Run:
    python scripts/fit_gmm_regime.py

The yfinance import lives inside ``main()`` so importing this module (e.g. for
a smoke test of ``build_feature_matrix``) does NOT require the network or the
yfinance package.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

# Make the backend package importable when run as a top-level script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from archimedes.services.gmm_regime_detector import (
    _FEATURE_WINDOW,
    _TRADING_DAYS_PER_YEAR,
    DEFAULT_GMM_MODEL_PATH,
    fit_gmm_model,
    save_gmm_model,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fit_gmm_regime")

# ~2 years of trading days clears the ≥504-row bar with margin for the
# _FEATURE_WINDOW warm-up that the rolling features consume.
_LOOKBACK_PERIOD = "3y"
_MIN_FIT_ROWS = 504


def build_feature_matrix(vix_closes: np.ndarray, spy_closes: np.ndarray) -> np.ndarray:
    """Build the daily (n, 4) feature matrix from aligned VIX + SPY close series.

    Feature order matches ``GmmRegimeDetector`` exactly:
        [vix_level, vix_21d_chg, realized_vol_21d, return_21d].

    The first ``_FEATURE_WINDOW`` rows are dropped (no 21-day lookback yet).
    """
    vix_closes = np.asarray(vix_closes, dtype=float)
    spy_closes = np.asarray(spy_closes, dtype=float)
    if vix_closes.shape != spy_closes.shape:
        raise ValueError(f"VIX/SPY series length mismatch: {vix_closes.shape} vs {spy_closes.shape}")

    rows: list[list[float]] = []
    for t in range(_FEATURE_WINDOW, len(spy_closes)):
        vix_now = vix_closes[t]
        vix_then = vix_closes[t - _FEATURE_WINDOW]
        spy_now = spy_closes[t]
        spy_then = spy_closes[t - _FEATURE_WINDOW]

        vix_21d_chg = (vix_now - vix_then) / vix_then if vix_then else 0.0
        return_21d = (spy_now - spy_then) / spy_then if spy_then else 0.0

        window = spy_closes[t - _FEATURE_WINDOW : t + 1]
        daily_returns = np.diff(window) / window[:-1]
        realized_vol_21d = float(np.std(daily_returns) * np.sqrt(_TRADING_DAYS_PER_YEAR))

        rows.append([float(vix_now), float(vix_21d_chg), realized_vol_21d, float(return_21d)])

    return np.array(rows, dtype=float)


def main() -> None:
    """Fetch data, build features, fit, and persist the model."""
    # Network-only dependency — imported lazily so module import stays offline.
    import yfinance as yf

    logger.info("Downloading ~%s of ^VIX and SPY daily closes…", _LOOKBACK_PERIOD)
    vix_df = yf.download("^VIX", period=_LOOKBACK_PERIOD, interval="1d", auto_adjust=False, progress=False)
    spy_df = yf.download("SPY", period=_LOOKBACK_PERIOD, interval="1d", auto_adjust=False, progress=False)

    if vix_df is None or spy_df is None or vix_df.empty or spy_df.empty:
        raise SystemExit("yfinance returned no data for ^VIX and/or SPY — aborting.")

    # Align on the common trading dates so the two series are index-matched.
    joined = vix_df[["Close"]].join(spy_df[["Close"]], how="inner", lsuffix="_vix", rsuffix="_spy").dropna()
    vix_closes = joined.iloc[:, 0].to_numpy(dtype=float)
    spy_closes = joined.iloc[:, 1].to_numpy(dtype=float)
    logger.info("Aligned %d daily observations.", len(vix_closes))

    features = build_feature_matrix(vix_closes, spy_closes)
    logger.info("Built feature matrix: %s", features.shape)
    if features.shape[0] < _MIN_FIT_ROWS:
        raise SystemExit(f"Only {features.shape[0]} feature rows (< {_MIN_FIT_ROWS}); fetch a longer history.")

    fitted = fit_gmm_model(features)
    logger.info("Component → regime mapping: %s", {k: v.value for k, v in fitted.component_to_regime.items()})

    save_gmm_model(fitted, DEFAULT_GMM_MODEL_PATH)
    logger.info("Done. Fitted GMM regime model written to %s", DEFAULT_GMM_MODEL_PATH)


if __name__ == "__main__":
    main()
