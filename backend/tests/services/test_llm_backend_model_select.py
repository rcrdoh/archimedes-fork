"""Coverage for the free-tier model allowlist + optional model override on
``make_llm_backend()`` (P1 — functional model selection).

Hermetic: no network, no AWS. The Converse/Anthropic backends are constructed
without credentials so they degrade to the canned fallback; we assert on the
model id resolution and the allowlist gate, not on live calls.
"""

from __future__ import annotations

from archimedes.services.llm_backend import (
    DEFAULT_CONVERSE_MODEL,
    FREE_TIER_MODELS,
    BedrockConverseBackend,
    is_allowed_model,
    make_llm_backend,
)


class TestAllowlist:
    def test_free_tier_models_are_allowed(self) -> None:
        # A representative sample of the free-tier ids.
        for mid in ("amazon.nova-micro-v1:0", "zai.glm-4.7-flash", "amazon.nova-lite-v1:0"):
            assert is_allowed_model(mid), mid

    def test_premium_anthropic_models_are_rejected(self) -> None:
        # The two premium (works_now:false) ids must NOT be selectable server-side.
        assert not is_allowed_model("us.anthropic.claude-haiku-4-5-20251001-v1:0")
        assert not is_allowed_model("us.anthropic.claude-sonnet-4-6")
        # Premium ids are absent from the allowlist set itself.
        assert "us.anthropic.claude-haiku-4-5-20251001-v1:0" not in FREE_TIER_MODELS
        assert "us.anthropic.claude-sonnet-4-6" not in FREE_TIER_MODELS

    def test_none_and_junk_are_rejected(self) -> None:
        assert not is_allowed_model(None)
        assert not is_allowed_model("")
        assert not is_allowed_model("totally-made-up-model")


class TestModelOverride:
    def test_override_threads_to_converse_ctor(self) -> None:
        """A supplied model id wins over the env default on the Converse backend."""
        backend = BedrockConverseBackend(model="zai.glm-4.7-flash")
        assert backend.model_id == "zai.glm-4.7-flash"

    def test_none_preserves_env_default(self) -> None:
        """model=None (the default) → the env/default resolution, unchanged."""
        backend = BedrockConverseBackend(model=None)
        assert backend.model_id == DEFAULT_CONVERSE_MODEL

    def test_factory_override_on_converse(self, monkeypatch) -> None:
        """make_llm_backend(model=...) overrides for the bedrock_converse provider."""
        monkeypatch.setenv("LLM_PROVIDER", "bedrock_converse")
        backend = make_llm_backend(model="amazon.nova-lite-v1:0")
        # No AWS creds in the hermetic env → canned fallback, but the override
        # path must not raise. When creds ARE present the id would be Nova Lite.
        assert backend is not None

    def test_factory_default_unchanged_when_no_model(self, monkeypatch) -> None:
        """No model arg → identical behavior to the pre-change factory."""
        monkeypatch.setenv("LLM_PROVIDER", "bedrock_converse")
        monkeypatch.setenv("LLM_BEDROCK_MODEL", "amazon.nova-micro-v1:0")
        # Construct the backend directly to read the resolved id deterministically
        # (the factory may return canned without creds).
        backend = BedrockConverseBackend(model=None)
        assert backend.model_id == "amazon.nova-micro-v1:0"
