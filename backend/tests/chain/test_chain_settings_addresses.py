"""Externalized contract addresses (roadmap T2.3).

ChainSettings reads every contract address from an ``ARC_<FIELD>`` environment
variable, falling back to a hardcoded deployed-Arc-testnet default when the
variable is unset. These tests pin both halves of that contract:

  (a) when the env vars are UNSET, the in-code defaults are used (nothing breaks
      on a fresh clone with no .env);
  (b) when an env var IS set, the env value wins over the default.

Hermetic: every ChainSettings is constructed with ``_env_file=None`` so no
ambient ``.env`` on disk can leak in, and env vars are controlled via
``monkeypatch`` (which it cleans up). No network, no Arc RPC, no .env dependence.
"""

from __future__ import annotations

import pytest
from archimedes.chain.client import ChainSettings

# The in-code default addresses, mirrored here so the test fails loudly if a
# default is changed without the test being updated (a default change is a
# deploy-address change — worth a deliberate test edit).
EXPECTED_DEFAULTS = {
    "usdc_address": "0x3600000000000000000000000000000000000000",
    "stsla_address": "0xd514cd27baf762c650536765cde9b61c876abacd",
    "snvda_address": "0x805e75019a1291a598dfc134ad2519121a35fb11",
    "sspy_address": "0x6fea38dedea0c6bb66ce93e5383c34385d8b889f",
    "sbtc_address": "0x317e82be8f7cba6c162ab968fcf695d88e8e0359",
    "sgold_address": "0xf384562c8bdafce52400eb6839f195695f6fa276",
    "soil_address": "0x46cead4120f17a968ba1168f1a56563962cf3c4b",
    "snky_address": "0x445b8f0f827a0d384d1b8ccf18cbc6ec8a543376",
    "stsla_oracle_address": "0xe1c9f2b11be97097223a66a188fca541e07873a6",
    "snvda_oracle_address": "0xeb36acf88e739dd312de8278985262146a017374",
    "sspy_oracle_address": "0xd8161a8eeab7c7100e2863abe3d5f346b5ff9e52",
    "sbtc_oracle_address": "0x6cc5f621c4e3b46152e69e5c9873689cbb4a85e8",
    "sgold_oracle_address": "0x35fccde01ae8728c7a7cb83c3f59c701ebecc633",
    "soil_oracle_address": "0x79f354524fd09af16d841a2221af2b2b7bc432c8",
    "snky_oracle_address": "0xcd34a4103ad64a3cf729b1b1a58295ccc957fcee",
}

# Address fields whose in-code default is the empty string (deployment-specific —
# must be supplied via .env before the contract can be used).
EMPTY_DEFAULT_FIELDS = [
    "amm_router_address",
    "synthetic_factory_address",
    "vault_factory_address",
    "reasoning_trace_registry_address",
    "asset_registry_address",
    "strategy_registry_address",
]

# All ARC_*-prefixed env vars that ChainSettings reads, paired with the field
# each one overrides. The env-var name is the field upper-cased with the ARC_
# prefix (env_prefix="ARC_").
ENV_VAR_FOR_FIELD = {
    "usdc_address": "ARC_USDC_ADDRESS",
    "amm_router_address": "ARC_AMM_ROUTER_ADDRESS",
    "synthetic_factory_address": "ARC_SYNTHETIC_FACTORY_ADDRESS",
    "vault_factory_address": "ARC_VAULT_FACTORY_ADDRESS",
    "reasoning_trace_registry_address": "ARC_REASONING_TRACE_REGISTRY_ADDRESS",
    "asset_registry_address": "ARC_ASSET_REGISTRY_ADDRESS",
    "strategy_registry_address": "ARC_STRATEGY_REGISTRY_ADDRESS",
    "stsla_address": "ARC_STSLA_ADDRESS",
    "snvda_address": "ARC_SNVDA_ADDRESS",
    "sspy_address": "ARC_SSPY_ADDRESS",
    "sbtc_address": "ARC_SBTC_ADDRESS",
    "sgold_address": "ARC_SGOLD_ADDRESS",
    "soil_address": "ARC_SOIL_ADDRESS",
    "snky_address": "ARC_SNKY_ADDRESS",
    "stsla_oracle_address": "ARC_STSLA_ORACLE_ADDRESS",
    "snvda_oracle_address": "ARC_SNVDA_ORACLE_ADDRESS",
    "sspy_oracle_address": "ARC_SSPY_ORACLE_ADDRESS",
    "sbtc_oracle_address": "ARC_SBTC_ORACLE_ADDRESS",
    "sgold_oracle_address": "ARC_SGOLD_ORACLE_ADDRESS",
    "soil_oracle_address": "ARC_SOIL_ORACLE_ADDRESS",
    "snky_oracle_address": "ARC_SNKY_ORACLE_ADDRESS",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every ARC_* var so a developer's shell can't leak into the test.

    Combined with ``_env_file=None`` at construction, this guarantees the
    "defaults when unset" assertions see a truly empty override surface.
    """
    for env_var in ENV_VAR_FOR_FIELD.values():
        monkeypatch.delenv(env_var, raising=False)
    return monkeypatch


# ── (a) defaults are used when env is unset ───────────────────────────────────


class TestDefaultsWhenEnvUnset:
    def test_nonempty_defaults_match(self, clean_env):
        """Each non-empty address field falls back to its hardcoded default."""
        s = ChainSettings(_env_file=None)
        for field, expected in EXPECTED_DEFAULTS.items():
            assert getattr(s, field) == expected, f"{field} default mismatch"

    def test_empty_default_fields_are_empty(self, clean_env):
        """Deployment-specific fields default to the empty string when unset."""
        s = ChainSettings(_env_file=None)
        for field in EMPTY_DEFAULT_FIELDS:
            assert getattr(s, field) == "", f"{field} should default to ''"

    def test_synth_and_oracle_maps_use_defaults(self, clean_env):
        """The public synth_addresses / oracle_addresses maps reflect defaults."""
        s = ChainSettings(_env_file=None)
        assert s.synth_addresses["sTSLA"] == EXPECTED_DEFAULTS["stsla_address"]
        assert s.synth_addresses["sSPY"] == EXPECTED_DEFAULTS["sspy_address"]
        assert s.oracle_addresses["sTSLA"] == EXPECTED_DEFAULTS["stsla_oracle_address"]
        assert s.oracle_addresses["sNKY"] == EXPECTED_DEFAULTS["snky_oracle_address"]


# ── (b) env overrides win when set ────────────────────────────────────────────


class TestEnvOverrideWins:
    def test_each_field_overridable(self, clean_env):
        """Setting ARC_<FIELD> overrides that field's default, one at a time."""
        # Distinct sentinel per field so a cross-wired mapping can't pass.
        for i, (field, env_var) in enumerate(ENV_VAR_FOR_FIELD.items()):
            sentinel = f"0x{i:040x}"
            clean_env.setenv(env_var, sentinel)
            s = ChainSettings(_env_file=None)
            assert getattr(s, field) == sentinel, f"{env_var} did not override {field}"
            clean_env.delenv(env_var, raising=False)

    def test_override_flows_into_synth_map(self, clean_env):
        """An ARC_STSLA_ADDRESS override is visible through synth_addresses."""
        override = "0xAAAA000000000000000000000000000000000001"
        clean_env.setenv("ARC_STSLA_ADDRESS", override)
        s = ChainSettings(_env_file=None)
        assert s.stsla_address == override
        assert s.synth_addresses["sTSLA"] == override

    def test_override_flows_into_oracle_map(self, clean_env):
        """An ARC_SSPY_ORACLE_ADDRESS override is visible through oracle_addresses."""
        override = "0xBBBB000000000000000000000000000000000002"
        clean_env.setenv("ARC_SSPY_ORACLE_ADDRESS", override)
        s = ChainSettings(_env_file=None)
        assert s.sspy_oracle_address == override
        assert s.oracle_addresses["sSPY"] == override

    def test_empty_default_field_gets_value_from_env(self, clean_env):
        """A field that defaults to '' picks up a real address from its env var."""
        override = "0xCCCC000000000000000000000000000000000003"
        clean_env.setenv("ARC_AMM_ROUTER_ADDRESS", override)
        s = ChainSettings(_env_file=None)
        assert s.amm_router_address == override

    def test_unset_fields_keep_defaults_when_one_is_overridden(self, clean_env):
        """Overriding one field must not disturb the others' defaults."""
        clean_env.setenv("ARC_USDC_ADDRESS", "0xDDDD000000000000000000000000000000000004")
        s = ChainSettings(_env_file=None)
        assert s.usdc_address == "0xDDDD000000000000000000000000000000000004"
        # Neighbours untouched.
        assert s.stsla_address == EXPECTED_DEFAULTS["stsla_address"]
        assert s.sspy_oracle_address == EXPECTED_DEFAULTS["sspy_oracle_address"]
