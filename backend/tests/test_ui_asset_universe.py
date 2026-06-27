"""The GENERATE-page asset picker must match the deploy-eligible SSOT (#758).

``ui/src/data/assetUniverse.js`` is generated from the SSOT; these tests fail CI if it
drifts — e.g. a single-name equity is re-added, or a deploy-eligible asset is missing.
(Explore sources its assets from the backend ``/api/explore/assets`` endpoint, not this
file — that path is aligned to the SSOT separately by #764/#765.)
Hermetic: reads the committed file + in-memory SSOT, no DB / Redis / RPC / .env.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from archimedes.scripts.gen_ui_asset_universe import _OUTPUT_PATH, _tickers_in, expected_tickers
from archimedes.services.strategy_signal_evaluator import GLOBAL_ASSETS
from archimedes.universe import COMPLIANCE_FLAGGED_SINGLE_STOCKS


def _picker_path() -> Path:
    # Single-source the path from the generator's canonical _OUTPUT_PATH so the test target
    # stays in lockstep with what the generator writes (no duplicate repo-root math) (#758 review).
    return _OUTPUT_PATH


def test_picker_matches_deploy_eligible_ssot() -> None:
    got = _tickers_in(_picker_path().read_text(encoding="utf-8"))
    want = expected_tickers()
    assert got == want, (
        "asset picker drifted from the deploy-eligible SSOT — "
        f"only-in-picker={sorted(got - want)} only-in-ssot={sorted(want - got)}. "
        "Regenerate from repo root: PYTHONPATH=backend python -m archimedes.scripts.gen_ui_asset_universe"
    )


def test_picker_has_no_single_name_equities() -> None:
    # The compliance-held single stocks (by display symbol) must NOT appear in the picker.
    got = _tickers_in(_picker_path().read_text(encoding="utf-8"))
    flagged_display = {GLOBAL_ASSETS[s][1] for s in COMPLIANCE_FLAGGED_SINGLE_STOCKS if s in GLOBAL_ASSETS}
    leaked = got & flagged_display
    assert not leaked, f"single-name equities leaked into the asset picker: {sorted(leaked)}"


def test_tickers_in_rejects_cross_group_duplicate() -> None:
    # A ticker duplicated across two groups must fail loudly — a plain set would collapse it
    # and let --check/CI miss the drift while the UI renders duplicate chips (#758 review).
    js = (
        "export const ASSET_GROUPS = [\n"
        "  { id: 'a', label: 'A', assets: ['sBTC', 'sETH'] },\n"
        "  { id: 'b', label: 'B', assets: ['sETH', 'sSPY'] },\n"  # sETH duplicated
        "]\n"
    )
    with pytest.raises(SystemExit, match="duplicate ticker"):
        _tickers_in(js)


def test_tickers_in_is_quote_style_insensitive() -> None:
    # A formatter (prettier/eslint) rewriting the generated file to double quotes must not make
    # --check report false drift: both quote styles parse to the same ticker set (#758 review).
    single = "export const ASSET_GROUPS = [\n  { id: 'a', label: 'A', assets: ['sBTC', 'sETH'] },\n]\n"
    double = 'export const ASSET_GROUPS = [\n  { id: "a", label: "A", "assets": ["sBTC", "sETH"] },\n]\n'
    assert _tickers_in(single) == _tickers_in(double) == {"sBTC", "sETH"}
