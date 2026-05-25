"""Unit coverage for the KB-pipeline scheduling helpers.

Targets `_load_manifest`, `_count_new_papers_since`, and `needs_rerun`.
The blocking `main()` loop is intentionally not exercised — it's an
infinite `time.sleep` loop and is excluded by the `if __name__` guard.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from archimedes.services import kb_runner


@pytest.fixture
def tmp_artifact_dir(tmp_path, monkeypatch):
    """Point kb_runner.ARTIFACT_DIR at a fresh tmp directory for the test."""
    monkeypatch.setattr(kb_runner, "ARTIFACT_DIR", tmp_path)
    return tmp_path


class TestLoadManifest:
    def test_missing_manifest_returns_none(self, tmp_artifact_dir):
        assert kb_runner._load_manifest() is None

    def test_unreadable_manifest_returns_none(self, tmp_artifact_dir):
        (tmp_artifact_dir / "manifest.json").write_text("not-json")
        assert kb_runner._load_manifest() is None

    def test_valid_manifest_returns_parsed_dict(self, tmp_artifact_dir):
        payload = {"run_ts": "2026-05-20T12:00:00+00:00", "paper_count": 4242}
        (tmp_artifact_dir / "manifest.json").write_text(json.dumps(payload))
        assert kb_runner._load_manifest() == payload


class TestCountNewPapersSince:
    def test_none_timestamp_returns_zero(self):
        # Short-circuits before any DB import — safe to call without mocks
        assert kb_runner._count_new_papers_since(None) == 0

    def test_db_failure_returns_zero(self):
        # No DB available in unit test env → the broad except returns 0
        assert kb_runner._count_new_papers_since("2026-05-01T00:00:00+00:00") == 0


class TestNeedsRerun:
    def test_no_prior_run_triggers_rerun(self, tmp_artifact_dir):
        # No manifest at all → eligible to run
        assert kb_runner.needs_rerun() is True

    def test_new_paper_threshold_triggers_rerun(self, tmp_artifact_dir):
        (tmp_artifact_dir / "manifest.json").write_text(json.dumps({"run_ts": datetime.now(UTC).isoformat()}))
        with patch.object(kb_runner, "_count_new_papers_since", return_value=kb_runner.NEW_PAPER_THRESHOLD + 1):
            assert kb_runner.needs_rerun() is True

    def test_stale_run_triggers_rerun(self, tmp_artifact_dir):
        old_ts = (datetime.now(UTC) - timedelta(days=kb_runner.MAX_DAYS_SINCE_LAST + 1)).isoformat()
        (tmp_artifact_dir / "manifest.json").write_text(json.dumps({"run_ts": old_ts}))
        with patch.object(kb_runner, "_count_new_papers_since", return_value=0):
            assert kb_runner.needs_rerun() is True

    def test_recent_run_no_threshold_skips(self, tmp_artifact_dir):
        recent = datetime.now(UTC).isoformat()
        (tmp_artifact_dir / "manifest.json").write_text(json.dumps({"run_ts": recent}))
        with patch.object(kb_runner, "_count_new_papers_since", return_value=0):
            assert kb_runner.needs_rerun() is False

    def test_malformed_timestamp_triggers_rerun(self, tmp_artifact_dir):
        (tmp_artifact_dir / "manifest.json").write_text(json.dumps({"run_ts": "not-iso"}))
        with patch.object(kb_runner, "_count_new_papers_since", return_value=0):
            # ValueError path → treats as eligible-to-run
            assert kb_runner.needs_rerun() is True
