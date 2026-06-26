"""Server-side paid-tier model gating (entitlement).

The Generate page's cost picker (``ui/src/data/modelPricing.json``) advertises
both free models (``works_now`` — non-Anthropic Bedrock Converse models such as
Nova Micro / GLM / DeepSeek) and "premium" Anthropic models
(``premium``/``works_now: false`` — the ``us.anthropic.*`` Claude family). Until
now nothing on the backend stopped a caller from requesting any model, so the
premium tier was a UI label with no teeth.

This module makes the gate real and server-authoritative:

  - A **free** model is always allowed.
  - A **premium** model requires entitlement. For the single-user MVP,
    entitlement = wallet-connected **AND** premium enabled via config
    (``PREMIUM_MODELS_ENABLED`` global flag, or an allowlisted-wallet list in
    ``PREMIUM_MODELS_ALLOWLIST``).

An explicit premium request from a non-entitled caller is **rejected** (HTTP
402 Payment Required) — never silently downgraded to the free default. Silent
downgrade would let a non-paying caller think they got premium output, and
would erode the "what model ran" provenance the passport relies on.

Classification mirrors ``ui/src/data/modelPricing.json``: premium = the
Anthropic Claude family on Bedrock (model id contains ``anthropic.``). Everything
else (Nova, GLM, DeepSeek, Qwen, Llama, Mistral, Kimi, gpt-oss, …) is free.
Keeping the rule provider-based — rather than enumerating exact ids — means a
new Anthropic inference-profile id is gated by default rather than slipping
through an allowlist that someone forgot to update.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

# Premium = Anthropic Claude on Bedrock. The id always carries the ``anthropic.``
# provider segment (e.g. ``us.anthropic.claude-haiku-4-5-20251001-v1:0`` or
# ``us.anthropic.claude-sonnet-4-6``). Match on that segment so the gate is
# closed-by-default for any future Anthropic profile id, not just the two the
# pricing snapshot happens to list today.
_PREMIUM_MARKER = "anthropic."


def is_premium_model(model_id: str) -> bool:
    """True when ``model_id`` is a premium (Anthropic) Bedrock model.

    Case-insensitive and tolerant of surrounding whitespace so a hand-typed or
    differently-cased id can't bypass the gate.
    """
    return _PREMIUM_MARKER in (model_id or "").strip().lower()


def _premium_globally_enabled() -> bool:
    """Whether the premium tier is switched on for everyone (single-user MVP)."""
    return os.getenv("PREMIUM_MODELS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _premium_allowlisted_wallets() -> set[str]:
    """Lowercased set of wallets entitled to premium, from ``PREMIUM_MODELS_ALLOWLIST``.

    Comma/space separated; empty when unset.
    """
    raw = os.getenv("PREMIUM_MODELS_ALLOWLIST", "")
    return {w.strip().lower() for w in raw.replace(",", " ").split() if w.strip()}


def is_entitled_to_premium(wallet: str | None) -> bool:
    """Whether ``wallet`` may invoke premium models.

    Entitlement for the single-user MVP is **wallet-connected AND** one of:
      - the global ``PREMIUM_MODELS_ENABLED`` flag is on, or
      - the wallet is in ``PREMIUM_MODELS_ALLOWLIST``.

    An anonymous caller (``wallet is None``) is never entitled — premium spend
    must be attributable to a verified wallet.
    """
    if not wallet:
        return False
    wallet_lc = wallet.strip().lower()
    if not wallet_lc:
        return False
    if _premium_globally_enabled():
        return True
    return wallet_lc in _premium_allowlisted_wallets()


def enforce_model_entitlement(model_id: str | None, wallet: str | None) -> None:
    """Reject a premium-model request from a non-entitled caller.

    Free models (``model_id`` is None/empty → use the configured default, or any
    non-Anthropic model) always pass. A premium model without entitlement raises
    HTTP 402 with a clear message — we reject rather than fall back to the free
    default, because an *explicit* premium request must not be silently
    downgraded.
    """
    if not model_id or not is_premium_model(model_id):
        return
    if is_entitled_to_premium(wallet):
        return
    raise HTTPException(
        status_code=402,
        detail=(
            f"Model '{model_id}' is a premium (Anthropic) model and requires an "
            "entitlement. Connect a wallet entitled to premium models, or pick a "
            "free model. The request was not downgraded."
        ),
    )
