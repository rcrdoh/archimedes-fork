"""Hermetic tests for the library-PBO toolchain: pbo module, store generation
add-only law, date alignment, and the engine's dated daily-returns.

All synthetic/seeded — no network, no store files required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from archimedes_analytics_engine.engine import run_buy_and_hold
from archimedes_analytics_engine.pbo import compute_pbo

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from compute_library_pbo import build_aligned_matrix, cscv_diagnostics
from gen_daily_returns_store import _write_record, pending_specs, store_path

# ── compute_pbo behavior on synthetic matrices ─────────────────────────────────


def _persistent_skill_matrix(n: int = 8, t: int = 1600, seed: int = 7) -> dict[str, list[float]]:
    """Strategies with stable, well-separated means — IS-best stays OOS-best."""
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n):
        mu = 0.0005 * (i + 1)  # distinct persistent edges
        out[f"s{i:02d}"] = (mu + rng.normal(0.0, 0.0008, size=t)).tolist()
    return out


def _planted_overfit_matrix(n: int = 8, t: int = 1600, s: int = 16, seed: int = 7) -> dict[str, list[float]]:
    """Anti-persistent construction: per-block performance flips sign by block
    parity, opposite for the two strategy groups. Whatever wins in-sample loses
    out-of-sample by construction — the canonical overfit shape CSCV detects.
    """
    rng = np.random.default_rng(seed)
    rows_per_block = t // s
    out = {}
    for i in range(n):
        vals = []
        for b in range(s):
            sign = 1.0 if (b % 2 == i % 2) else -1.0
            vals.extend((sign * 0.002 + rng.normal(0.0, 0.0002, size=rows_per_block)).tolist())
        out[f"s{i:02d}"] = vals
    return out


def test_persistent_skill_gives_low_pbo() -> None:
    pbo = next(iter(compute_pbo(_persistent_skill_matrix()).values()))
    assert pbo < 0.2


def test_planted_overfit_gives_high_pbo() -> None:
    pbo = next(iter(compute_pbo(_planted_overfit_matrix()).values()))
    assert pbo > 0.5


def test_pbo_attaches_same_value_to_every_strategy() -> None:
    result = compute_pbo(_persistent_skill_matrix(n=4, t=800))
    assert len(set(result.values())) == 1
    assert set(result.keys()) == {f"s{i:02d}" for i in range(4)}


def test_pbo_degenerate_inputs_return_zero() -> None:
    assert compute_pbo({"only": [0.01] * 100}) == {"only": 0.0}
    # T < S partitions → rows_per_block == 0 → 0.0 for all
    short = {"a": [0.01] * 10, "b": [0.02] * 10}
    assert compute_pbo(short) == {"a": 0.0, "b": 0.0}


def test_regen_fixtures_uses_the_shared_pbo() -> None:
    """Guard against forking the formula: regen_fixtures must re-export the
    pbo-module function, not carry its own copy."""
    import regen_fixtures

    assert regen_fixtures.compute_pbo is compute_pbo


def test_diagnostics_pbo_matches_compute_pbo() -> None:
    for matrix in (_persistent_skill_matrix(), _planted_overfit_matrix()):
        expected = next(iter(compute_pbo(matrix).values()))
        diag = cscv_diagnostics(matrix)
        assert diag["pbo"] == expected
        assert sum(d["is_best_count"] for d in diag["per_strategy"].values()) == diag["n_splits"]


# ── date alignment ─────────────────────────────────────────────────────────────


def _record(stem: str, dates: list[str], returns: list[float]) -> dict:
    return {
        "stem": stem,
        "dates": dates,
        "daily_returns": returns,
        "n_obs": len(returns),
        "data_vintage": "2026-06-11",
    }


def test_build_aligned_matrix_inner_joins_calendars() -> None:
    rec_a = _record("a", ["2024-01-01", "2024-01-02", "2024-01-03"], [0.1, 0.2, 0.3])
    rec_b = _record("b", ["2024-01-02", "2024-01-03", "2024-01-04"], [1.1, 1.2, 1.3])
    joint, matrix = build_aligned_matrix([rec_a, rec_b])
    assert joint == ["2024-01-02", "2024-01-03"]
    assert matrix == {"a": [0.2, 0.3], "b": [1.1, 1.2]}


def test_build_aligned_matrix_empty_intersection_stops() -> None:
    rec_a = _record("a", ["2024-01-01"], [0.1])
    rec_b = _record("b", ["2024-06-01"], [0.2])
    with pytest.raises(SystemExit):
        build_aligned_matrix([rec_a, rec_b])


# ── store generation: add-only + idempotent ────────────────────────────────────


def test_pending_specs_skips_existing_store_files(tmp_path: Path) -> None:
    specs = [{"stem": "existing"}, {"stem": "missing"}]
    store_path("existing", tmp_path).write_text("{}", encoding="utf-8")
    pending, skipped = pending_specs(specs, tmp_path)
    assert [s["stem"] for s in pending] == ["missing"]
    assert skipped == ["existing"]
    # Idempotency: once every file exists, nothing is pending.
    store_path("missing", tmp_path).write_text("{}", encoding="utf-8")
    pending, skipped = pending_specs(specs, tmp_path)
    assert pending == []
    assert sorted(skipped) == ["existing", "missing"]


def test_write_record_refuses_overwrite(tmp_path: Path) -> None:
    record = _record("dup", ["2024-01-01"], [0.1])
    _write_record(record, tmp_path)
    assert json.loads(store_path("dup", tmp_path).read_text(encoding="utf-8"))["stem"] == "dup"
    with pytest.raises(SystemExit):
        _write_record(record, tmp_path)


# ── engine: dated daily returns ────────────────────────────────────────────────


def test_backtest_result_carries_aligned_iso_dates() -> None:
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    closes = [100, 102, 101, 105, 106, 107, 108, 109]
    prices = pd.DataFrame(
        {
            "Open": [c - 1 for c in closes],
            "High": [c + 1 for c in closes],
            "Low": [c - 2 for c in closes],
            "Close": closes,
            "Volume": [1000] * 8,
        },
        index=idx,
    )
    result = run_buy_and_hold(prices, initial_cash=10_000.0)
    assert len(result.daily_return_dates) == len(result.daily_returns)
    assert result.daily_return_dates == sorted(result.daily_return_dates)
    assert all(len(d) == 10 and d[4] == "-" and d[7] == "-" for d in result.daily_return_dates)
