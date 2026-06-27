"""``docs/asset-universe.md`` is generated from the SSOT and must stay in sync (#757).

Hermetic: in-memory render vs the committed file, plus a subprocess invocation of the real
``--check`` CLI — no DB / Redis / RPC / .env.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from archimedes.universe import (
    COMPLIANCE_FLAGGED_SINGLE_STOCKS,
    ON_CHAIN_SYNTHS,
    chainlink_covered_synths,
)


def _repo_root() -> Path:
    import archimedes  # backend/archimedes/__init__.py → parents: archimedes, backend, <repo>

    return Path(archimedes.__file__).resolve().parents[2]


def _doc_path() -> Path:
    return _repo_root() / "docs" / "asset-universe.md"


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    # Hermetic subprocess env: do NOT inherit the developer's .env (DATABASE_URL etc. that
    # only resolve inside docker compose) — just what the stdlib generator needs to import
    # archimedes and find the SSOT (CLAUDE.md subprocess-test convention). Deliberately does
    # NOT set PYTHONUTF8: the CLI forces UTF-8 stdio itself, and the drift test below proves it
    # in a hostile C locale (#757 review — the CLI must be robust when run as documented).
    env = {
        "HOME": os.environ.get("HOME", "/tmp"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_repo_root() / "backend"),
    }
    if extra:
        env.update(extra)
    return env


def test_asset_universe_doc_is_in_sync() -> None:
    # A SSOT edit that forgets to regenerate the doc fails CI here.
    from archimedes.scripts.gen_asset_universe_doc import render_doc

    committed = _doc_path().read_text(encoding="utf-8")
    assert committed == render_doc(), (
        "docs/asset-universe.md is stale vs the SSOT — regenerate with "
        "`PYTHONPATH=backend python scripts/gen_asset_universe_doc.py`."
    )


def test_on_chain_table_has_exactly_one_row_per_synth() -> None:
    # The on-chain TABLE must have exactly one row per deploy-eligible synth, with a BARE
    # symbol in the first cell so the #757 acceptance regex (^\|\s*s[A-Z]) counts exactly
    # these rows. The compliance list renders symbols inline-backticked (not `| sXXX` rows),
    # so it won't match — guarding a symbol appearing only in prose / the compliance list.
    text = _doc_path().read_text(encoding="utf-8")
    # Mirror the #757 acceptance regex `^\|\s*s[A-Z]` — an UPPERCASE letter after the leading
    # `s` (so the `| symbol |` header, "sy…", is excluded; every synth is `s` + uppercase).
    rows = re.findall(r"^\|\s*(s[A-Z][A-Za-z0-9]*)\s*\|", text, flags=re.MULTILINE)
    assert set(rows) == set(ON_CHAIN_SYNTHS), (
        f"on-chain table rows != SSOT. only-in-table={sorted(set(rows) - set(ON_CHAIN_SYNTHS))} "
        f"only-in-ssot={sorted(set(ON_CHAIN_SYNTHS) - set(rows))}"
    )
    assert len(rows) == len(set(rows)) == len(ON_CHAIN_SYNTHS), "duplicate or missing table rows"


def test_compliance_held_singles_are_listed() -> None:
    # Every compliance-held single stock must be documented (inline-backticked list).
    text = _doc_path().read_text(encoding="utf-8")
    for sym in COMPLIANCE_FLAGGED_SINGLE_STOCKS:
        assert f"`{sym}`" in text, f"compliance-flagged {sym} missing from docs/asset-universe.md"


def test_chainlink_covered_column_is_machine_greppable() -> None:
    # #757 requires a machine-greppable `chainlink_covered` column rendering true/false, so the
    # documented `grep -c 'true *|'` verification works and the true/false split matches the SSOT.
    text = _doc_path().read_text(encoding="utf-8")
    n_true = text.count("| true |")
    n_false = text.count("| false |")
    assert n_true == len(chainlink_covered_synths()), f"true rows ({n_true}) != covered count"
    assert n_false == len(ON_CHAIN_SYNTHS) - len(chainlink_covered_synths()), (
        f"false rows ({n_false}) != not-covered count"
    )
    # mirror the issue's `grep -c 'true *|'` line count exactly
    grep_true = sum(1 for line in text.splitlines() if re.search(r"\btrue *\|", line))
    assert grep_true == len(chainlink_covered_synths())


def test_parity_invariant_states_disjointness() -> None:
    # #757: the parity story must state on-chain ∩ compliance-held = ∅ explicitly, not just
    # that backtest-only symbols are compliance-flagged.
    text = _doc_path().read_text(encoding="utf-8")
    assert "on-chain ∩ compliance-held = ∅" in text


def test_check_cli_reports_in_sync_via_subprocess() -> None:
    # Exercise the REAL --check CLI contract (exit 0 + 'in sync' message) through the
    # #757-documented `scripts/gen_asset_universe_doc.py` wrapper, not just render_doc()
    # in-process (#757 review).
    proc = subprocess.run(
        [sys.executable, "scripts/gen_asset_universe_doc.py", "--check"],
        cwd=str(_repo_root()),
        env=_clean_env(),
        capture_output=True,
        encoding="utf-8",  # decode the child's UTF-8 stdio regardless of the parent's locale
    )
    assert proc.returncode == 0, f"--check should pass on the committed doc; stderr=\n{proc.stderr}"
    assert "in sync" in proc.stdout.lower()


def test_check_cli_detects_drift_via_subprocess(tmp_path: Path) -> None:
    # --check must exit 1 AND print a diff when the doc drifts (#757 review). Point the CLI at
    # a tampered TEMP copy via ASSET_UNIVERSE_DOC_PATH so the committed doc is never mutated.
    # Force a hostile ASCII locale (LC_ALL=C, UTF-8 mode + C-locale coercion OFF) so the diff —
    # which contains the doc's non-ASCII `✅` — exercises the CLI's OWN UTF-8 stdio reconfigure,
    # not any env help. Without it this would raise UnicodeEncodeError.
    from archimedes.scripts.gen_asset_universe_doc import render_doc

    drifted = tmp_path / "asset-universe.md"
    drifted.write_text(render_doc() + "| sFAKE | Fake | crypto | $1.00 | 6 | true | live ✅ |\n", encoding="utf-8")
    hostile = {
        "ASSET_UNIVERSE_DOC_PATH": str(drifted),
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
    }
    proc = subprocess.run(
        [sys.executable, "scripts/gen_asset_universe_doc.py", "--check"],
        cwd=str(_repo_root()),
        env=_clean_env(hostile),
        capture_output=True,
        encoding="utf-8",  # decode the child's UTF-8 stdio regardless of the parent's locale
    )
    assert proc.returncode == 1, "drift must fail --check"
    assert "sFAKE" in proc.stderr, "the drift diff should be printed to stderr"
    assert "UnicodeEncodeError" not in proc.stderr, "the CLI must force UTF-8 stdio in a C locale"
