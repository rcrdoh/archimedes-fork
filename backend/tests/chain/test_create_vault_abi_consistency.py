"""Regression test: createVault ABI signature stays in lockstep across the repo.

Targets #652 — PR #646/#650 demonstrated that contracts/abis/VaultFactory.json's
createVault signature and the abi_function="createVault(...)" strings used by
Circle-signer call sites can drift independently of each other. This test
catches the "edit one side, forget the other" class of drift.

Out of scope (see issue #588): whether contracts/abis/VaultFactory.json itself
matches the *live deployed* bytecode on Arc testnet. That requires an RPC call
and is a separate, non-hermetic concern.

Hermetic: pure file/JSON reads, no network, no Arc RPC, no Circle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ABI_PATH = REPO_ROOT / "contracts" / "abis" / "VaultFactory.json"

# Call sites that submit createVault via Circle's execute_contract, identified
# by an explicit abi_function="createVault(...)" signature string.
CALL_SITES = [
    REPO_ROOT / "backend" / "archimedes" / "chain" / "executor.py",
    REPO_ROOT / "backend" / "archimedes" / "scripts" / "bootstrap_vaults.py",
]

_ABI_FUNCTION_RE = re.compile(r'abi_function="(createVault\([^)]*\))"')


def _canonical_create_vault_signature() -> str:
    """Derive createVault's canonical signature from the deployed-ABI artifact."""
    abi = json.loads(ABI_PATH.read_text())
    (create_vault,) = (e for e in abi if e.get("type") == "function" and e.get("name") == "createVault")
    types = [inp["type"] for inp in create_vault["inputs"]]
    return f"createVault({','.join(types)})"


def test_abi_defines_exactly_one_create_vault_function():
    """Sanity: the unpack in _canonical_create_vault_signature found exactly one."""
    assert _canonical_create_vault_signature().startswith("createVault(")


def test_call_sites_match_abi_signature():
    """Every abi_function="createVault(...)" string matches the ABI signature."""
    canonical = _canonical_create_vault_signature()

    for path in CALL_SITES:
        source = path.read_text()
        matches = _ABI_FUNCTION_RE.findall(source)
        assert matches, f'No abi_function="createVault(...)" found in {path.relative_to(REPO_ROOT)}'
        for sig in matches:
            assert sig == canonical, (
                f"{path.relative_to(REPO_ROOT)} uses abi_function={sig!r}, but "
                f"contracts/abis/VaultFactory.json's createVault signature is {canonical!r}"
            )
