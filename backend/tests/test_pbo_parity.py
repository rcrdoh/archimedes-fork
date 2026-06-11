"""Parity test: backend rigor_evaluator.compute_pbo ≡ analytics-engine pbo.compute_pbo.

The analytics engine carries a deliberate mirror of the backend CSCV PBO
(``analytics-engine/src/archimedes_analytics_engine/pbo.py``) so fixture/store
scripts can run without backend deps. The two implementations must never
drift — this test asserts exact-equal outputs on the same matrices.

Hermetic: the engine module is numpy-only (no backtrader/yfinance import), so
this works in the backend venv with a plain sys.path insert. No network, no DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from archimedes.services.rigor_evaluator import compute_pbo as backend_compute_pbo

_ENGINE_SRC = Path(__file__).resolve().parents[2] / "analytics-engine" / "src"
sys.path.insert(0, str(_ENGINE_SRC))

from archimedes_analytics_engine.pbo import compute_pbo as engine_compute_pbo  # noqa: E402


def _random_matrix(n: int, t: int, seed: int) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    return {f"s{i:02d}": rng.normal(0.0003, 0.01, size=t).tolist() for i in range(n)}


@pytest.mark.parametrize(
    ("n", "t", "seed"),
    [(4, 400, 1), (8, 1600, 2), (12, 1000, 3), (22, 2520, 4)],
)
def test_parity_on_random_matrices(n: int, t: int, seed: int) -> None:
    matrix = _random_matrix(n, t, seed)
    assert engine_compute_pbo(matrix) == backend_compute_pbo(matrix)


@pytest.mark.parametrize("s_partitions", [8, 12, 16])
def test_parity_across_partition_counts(s_partitions: int) -> None:
    matrix = _random_matrix(6, 960, seed=5)
    assert engine_compute_pbo(matrix, s_partitions=s_partitions) == backend_compute_pbo(
        matrix, s_partitions=s_partitions
    )


def test_parity_on_degenerate_inputs() -> None:
    single = {"only": [0.01] * 100}
    assert engine_compute_pbo(single) == backend_compute_pbo(single)
    short = {"a": [0.01] * 10, "b": [0.02] * 10}  # T < S → 0.0 path
    assert engine_compute_pbo(short) == backend_compute_pbo(short)


def test_parity_on_ragged_lengths() -> None:
    """Both sides truncate to the shortest series the same way."""
    rng = np.random.default_rng(6)
    matrix = {
        "a": rng.normal(0.0, 0.01, size=700).tolist(),
        "b": rng.normal(0.0, 0.01, size=650).tolist(),
        "c": rng.normal(0.0, 0.01, size=820).tolist(),
    }
    assert engine_compute_pbo(matrix) == backend_compute_pbo(matrix)
