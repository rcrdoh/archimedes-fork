"""Tests for seed_backtests_from_artifacts — current-state selection + fallback.

These are hermetic: every DB / provider / mapper boundary is patched, so no
Postgres, Redis, or analytics-engine import is required. The focus is the
*selection* logic added for issue #462 — seed only the latest artifact per
strategy, with fallback to an older run when the newest one is broken.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from archimedes.scripts import seed_backtests_from_artifacts as seed_mod


class _FakeStrategy:
    def __init__(self, sid: str, title: str):
        self.id = sid
        self.paper_title = title


def _write_artifact(dir_path: Path, run_id: str, title: str) -> Path:
    p = dir_path / f"{run_id}.json"
    p.write_text(
        json.dumps({"run_id": run_id, "strategy": {"paper_title": title}}),
        encoding="utf-8",
    )
    return p


@contextmanager
def _fake_session():
    yield MagicMock()


def _run_seed(tmp_path: Path, strategies: list[_FakeStrategy], *, insert_mock, validate_side_effect):
    """Invoke seed_from_artifacts with all boundaries patched."""
    provider = MagicMock()
    provider.list_strategies.return_value = strategies

    with (
        patch.object(seed_mod, "init_db"),
        patch.object(seed_mod, "default_provider", return_value=provider),
        patch.object(seed_mod, "get_session", _fake_session),
        patch.object(seed_mod, "AnalyticsArtifactModel") as model_cls,
        patch.object(seed_mod, "map_artifact_to_backtest_result", return_value=({}, "SPY")),
        patch.object(seed_mod, "canonical_artifact_hash", return_value="hash"),
        patch.object(seed_mod, "insert_backtest_if_missing", insert_mock),
    ):
        model_cls.model_validate.side_effect = validate_side_effect
        return seed_mod.seed_from_artifacts(tmp_path)


def test_seeds_only_latest_run_per_strategy(tmp_path):
    # Three timestamped runs for the same strategy — only the newest should seed.
    _write_artifact(tmp_path, "20260518T062814Z", "Buy-and-Hold Baseline")
    _write_artifact(tmp_path, "20260518T062844Z", "Buy-and-Hold Baseline")
    _write_artifact(tmp_path, "20260518T223800Z", "Buy-and-Hold Baseline")  # newest

    strat = _FakeStrategy("strat-bah-id", "Buy-and-Hold Baseline")
    insert_mock = MagicMock(return_value=(MagicMock(), True))

    summary = _run_seed(
        tmp_path,
        [strat],
        insert_mock=insert_mock,
        validate_side_effect=lambda payload: MagicMock(run_id=payload["run_id"]),
    )

    assert summary == {"inserted": 1, "skipped": 0, "failed": 0}
    assert insert_mock.call_count == 1
    assert insert_mock.call_args.kwargs["run_id"] == "20260518T223800Z"


def test_falls_back_to_older_run_when_newest_broken(tmp_path):
    _write_artifact(tmp_path, "20260518T090000Z", "Time Series Momentum")  # older, good
    _write_artifact(tmp_path, "20260518T100000Z", "Time Series Momentum")  # newest, broken

    strat = _FakeStrategy("strat-tsm-id", "Time Series Momentum")
    insert_mock = MagicMock(return_value=(MagicMock(), True))

    def _validate(payload):
        if payload["run_id"] == "20260518T100000Z":
            raise ValueError("corrupt artifact")
        return MagicMock(run_id=payload["run_id"])

    summary = _run_seed(tmp_path, [strat], insert_mock=insert_mock, validate_side_effect=_validate)

    assert summary == {"inserted": 1, "skipped": 0, "failed": 0}
    assert insert_mock.call_count == 1
    # fell back from the broken newest run to the older good one
    assert insert_mock.call_args.kwargs["run_id"] == "20260518T090000Z"


def test_strategy_failed_when_all_runs_broken(tmp_path):
    _write_artifact(tmp_path, "20260518T090000Z", "Time Series Momentum")
    _write_artifact(tmp_path, "20260518T100000Z", "Time Series Momentum")

    strat = _FakeStrategy("strat-tsm-id", "Time Series Momentum")
    insert_mock = MagicMock(return_value=(MagicMock(), True))

    def _always_broken(payload):
        raise ValueError("corrupt artifact")

    summary = _run_seed(tmp_path, [strat], insert_mock=insert_mock, validate_side_effect=_always_broken)

    assert summary == {"inserted": 0, "skipped": 0, "failed": 1}
    insert_mock.assert_not_called()


def test_unmatched_strategy_counted_failed_once(tmp_path):
    # No provider strategy matches this title; the whole group is one failure.
    _write_artifact(tmp_path, "20260518T223800Z", "Unknown Paper")
    _write_artifact(tmp_path, "20260518T223801Z", "Unknown Paper")

    insert_mock = MagicMock(return_value=(MagicMock(), True))

    summary = _run_seed(
        tmp_path,
        [],
        insert_mock=insert_mock,
        validate_side_effect=lambda payload: MagicMock(run_id=payload["run_id"]),
    )

    assert summary == {"inserted": 0, "skipped": 0, "failed": 1}
    insert_mock.assert_not_called()


def test_unreadable_artifact_is_skipped_not_fatal(tmp_path):
    # A corrupt JSON file must not abort seeding of the valid strategy.
    (tmp_path / "20260518T120000Z.json").write_text("{ not valid json", encoding="utf-8")
    _write_artifact(tmp_path, "20260518T223800Z", "Buy-and-Hold Baseline")

    strat = _FakeStrategy("strat-bah-id", "Buy-and-Hold Baseline")
    insert_mock = MagicMock(return_value=(MagicMock(), True))

    summary = _run_seed(
        tmp_path,
        [strat],
        insert_mock=insert_mock,
        validate_side_effect=lambda payload: MagicMock(run_id=payload["run_id"]),
    )

    assert summary == {"inserted": 1, "skipped": 0, "failed": 0}
    assert insert_mock.call_args.kwargs["run_id"] == "20260518T223800Z"


def test_already_present_run_counts_as_skipped(tmp_path):
    # insert_backtest_if_missing returning was_inserted=False → skipped, not failed.
    _write_artifact(tmp_path, "20260518T223800Z", "Buy-and-Hold Baseline")

    strat = _FakeStrategy("strat-bah-id", "Buy-and-Hold Baseline")
    insert_mock = MagicMock(return_value=(MagicMock(), False))

    summary = _run_seed(
        tmp_path,
        [strat],
        insert_mock=insert_mock,
        validate_side_effect=lambda payload: MagicMock(run_id=payload["run_id"]),
    )

    assert summary == {"inserted": 0, "skipped": 1, "failed": 0}
