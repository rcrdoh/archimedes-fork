"""Probability of Backtest Overfitting via CSCV (Bailey et al. 2014).

Single source for the analytics-engine side of the PBO math. This module is a
deliberate, line-for-line mirror of backend
``archimedes/services/rigor_evaluator.py::compute_pbo`` (Önder's lane) — the
two implementations share the algorithm and MUST NOT drift. The parity test at
``backend/tests/test_pbo_parity.py`` asserts equal outputs on the same
matrices; if you change one side, change the other and keep that test green.

Kept numpy-only (no scipy, no backtrader) so it is importable from the backend
test venv for the parity check.

Known limitations are documented on the backend docstring (library-level
coupling, coarse OOS rank at small N, trailing-bar truncation) and apply here
identically.
"""

from __future__ import annotations

import math
import warnings
from itertools import combinations

import numpy as np

_ANN = 252
_RF_DAILY = 0.05 / _ANN


def _sharpe_per_col(R: np.ndarray) -> np.ndarray:
    if R.shape[0] < 2:
        return np.zeros(R.shape[1])
    mu = R.mean(axis=0)
    sigma = R.std(axis=0, ddof=1)
    safe_sigma = np.where(sigma > 0, sigma, np.inf)
    return ((mu - _RF_DAILY) / safe_sigma) * math.sqrt(_ANN)


def _ascending_ranks(values: np.ndarray) -> np.ndarray:
    n = len(values)
    order = np.argsort(values)
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    return ranks


def compute_pbo(returns_matrix: dict[str, list[float]], s_partitions: int = 16) -> dict[str, float]:
    """Probability of Backtest Overfitting via CSCV (Bailey et al. 2014).

    Mirrors backend rigor_evaluator.compute_pbo. Returns {id: pbo} with the same
    library-level value attached to every member of the selection set.

    Alignment is the CALLER's job: all series must cover the same date range
    (this function truncates to the shortest length, which is only correct when
    row i means the same trading day in every series).
    """
    if len(returns_matrix) < 2:
        return dict.fromkeys(returns_matrix, 0.0)

    sorted_ids = sorted(returns_matrix.keys())
    N = len(sorted_ids)
    lengths = {sid: len(returns_matrix[sid]) for sid in sorted_ids}
    T = min(lengths.values())
    T_max = max(lengths.values())
    if T_max != T:
        # Truncating to the shortest series silently drops the most recent
        # (most forward-looking) OOS bars from longer series — exactly the bars
        # that matter most for detecting overfitting. Surface it so the caller
        # date-aligns rather than getting an optimistic PBO from misaligned data.
        discarded = {sid: lengths[sid] - T for sid in sorted_ids if lengths[sid] > T}
        warnings.warn(
            f"compute_pbo: series length mismatch (min={T}, max={T_max}); "
            f"trailing bars discarded per id: {discarded}. Pass date-aligned "
            f"series to suppress this warning.",
            stacklevel=2,
        )
    R = np.array([returns_matrix[sid][:T] for sid in sorted_ids], dtype=float).T  # (T, N)

    S = s_partitions if (s_partitions % 2 == 0 and s_partitions >= 2) else 16
    rows_per_block = T // S
    if rows_per_block < 1:
        return dict.fromkeys(sorted_ids, 0.0)

    blocks = [R[i * rows_per_block : (i + 1) * rows_per_block, :] for i in range(S)]
    half = S // 2
    lambdas: list[float] = []
    for is_indices in combinations(range(S), half):
        oos_indices = [i for i in range(S) if i not in is_indices]
        IS = np.vstack([blocks[i] for i in is_indices])
        OOS = np.vstack([blocks[i] for i in oos_indices])
        best_is_idx = int(np.argmax(_sharpe_per_col(IS)))
        oos_ranks = _ascending_ranks(_sharpe_per_col(OOS))
        omega = float(np.clip(oos_ranks[best_is_idx] / N, 1e-9, 1.0 - 1e-9))
        lambdas.append(math.log(omega / (1.0 - omega)))

    if not lambdas:
        return dict.fromkeys(sorted_ids, 0.0)
    pbo = round(sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas), 6)
    return dict.fromkeys(sorted_ids, pbo)
