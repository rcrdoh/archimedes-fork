"""Trace-hash tamper detection (#738 behavior a).

Target: backend/archimedes/models/trace.py — ReasoningTrace.compute_hash()

The reasoning-trace hash is the on-chain integrity anchor: anyone can recompute
keccak256 over the canonical content and compare against the value committed to
the ReasoningTraceRegistry. The load-bearing property is *tamper evidence* — if
any hashed field changes, the hash MUST change; if a non-hashed field (e.g. the
on-chain tx hash, added after the fact) changes, the hash MUST NOT change (so a
committed hash stays valid through the reveal phase).

Hermetic: pure in-memory dataclass + keccak; no chain, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from archimedes.models.trace import DecisionType, ReasoningTrace


def _trace(**overrides) -> ReasoningTrace:
    base = {
        "id": "trace-001",
        "vault_address": "0xVault00000000000000000000000000000000abcd",
        "decision_type": DecisionType.REBALANCE,
        "trigger": "strategy_signal_drift",
        "timestamp": datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
        "market_context": {"regime": "risk_on"},
        "portfolio_before": {"aum_usdc": 1000.0},
        "reasoning": "Momentum positive; rebalance into sSPY.",
        "confidence": 0.8,
        "trades_executed": [{"symbol": "sSPY", "direction": "buy", "amount": 100.0}],
        "strategies_referenced": ["faber_001"],
        "consulted_paper_hashes": ["arxiv:0001:deadbeef"],
    }
    base.update(overrides)
    return ReasoningTrace(**base)


class TestComputeHashDeterminism:
    def test_same_content_same_hash(self):
        h1 = _trace().compute_hash()
        h2 = _trace().compute_hash()
        assert h1 == h2
        # keccak256 hex is 32 bytes → 64 hex chars (+ "0x").
        assert len(h1.removeprefix("0x")) == 64

    def test_compute_hash_sets_trace_hash_attr(self):
        t = _trace()
        assert t.trace_hash == ""
        h = t.compute_hash()
        assert t.trace_hash == h


class TestComputeHashTamperEvidence:
    @pytest.mark.parametrize(
        ("field", "mutated"),
        [
            ("reasoning", "TAMPERED — sell everything."),
            ("confidence", 0.2),
            ("trigger", "manual_override"),
            ("vault_address", "0xATTACKER000000000000000000000000000000ff"),
            ("market_context", {"regime": "crisis"}),
            ("trades_executed", [{"symbol": "sBTC", "direction": "sell", "amount": 9999.0}]),
            ("strategies_referenced", ["evil_999"]),
            ("consulted_paper_hashes", ["arxiv:9999:cafebabe"]),
        ],
    )
    def test_mutating_a_hashed_field_changes_the_hash(self, field, mutated):
        original = _trace().compute_hash()
        tampered = _trace(**{field: mutated}).compute_hash()
        assert tampered != original, f"Mutating hashed field {field!r} must change the trace hash"

    def test_timestamp_is_part_of_the_hash(self):
        a = _trace(timestamp=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)).compute_hash()
        b = _trace(timestamp=datetime(2026, 6, 28, 12, 0, 1, tzinfo=UTC)).compute_hash()
        assert a != b

    def test_non_hashed_fields_do_not_change_the_hash(self):
        """The on-chain anchoring fields added AFTER the commit (arc_tx_hash,
        commit/reveal tx hashes + block numbers, trade tx/block) are intentionally
        OUTSIDE _HASH_FIELDS so the committed hash survives the reveal phase.
        Setting them must NOT move the hash.

        (Note: portfolio_after IS in _HASH_FIELDS, so it is deliberately excluded
        here — it is part of the canonical hashed content.)"""
        baseline = _trace()
        baseline_hash = baseline.compute_hash()

        annotated = _trace()
        annotated.arc_tx_hash = "0xANCHOR"
        annotated.commit_tx_hash = "0xCOMMIT"
        annotated.commit_block_number = 100
        annotated.reveal_tx_hash = "0xREVEAL"
        annotated.reveal_block_number = 102
        annotated.trade_tx_hash = "0xTRADE"
        annotated.trade_block_number = 101
        annotated.expected_outcome = "Outperform buy-and-hold"

        assert annotated.compute_hash() == baseline_hash

    def test_portfolio_after_is_part_of_the_hash(self):
        """portfolio_after IS in _HASH_FIELDS — changing it changes the hash.

        This documents the actual canonical set and guards against silently
        dropping portfolio_after from the hash (which would let a settled
        portfolio be edited without detection)."""
        a = _trace(portfolio_after={"tx_hashes": []}).compute_hash()
        b = _trace(portfolio_after={"tx_hashes": ["0xTRADE"]}).compute_hash()
        assert a != b

    def test_recompute_after_mutation_detects_tamper(self):
        """End-to-end: commit a hash, then mutate a hashed field — recomputing
        yields a different value, which is exactly how on-chain verifyTrace
        would catch a tampered off-chain record."""
        t = _trace()
        committed = t.compute_hash()
        # Adversary edits the persisted reasoning after the fact.
        t.reasoning = "Approved by the fund manager (forged)."
        assert t.compute_hash() != committed
