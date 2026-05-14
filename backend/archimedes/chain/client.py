"""Shared AsyncWeb3 client singleton for Arc chain interactions.

Connects to Arc testnet RPC, loads agent account from env vars.
All contract calls route through this client.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount
from pydantic_settings import BaseSettings
from web3 import AsyncWeb3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.providers.async_rpc import AsyncHTTPProvider


class ChainSettings(BaseSettings):
    """On-chain connection settings — loaded from .env or environment variables."""

    # RPC
    arc_rpc_url: str = "https://rpc.testnet.arc.network"
    chain_id: int =  13068200  # Arc testnet chain ID (update if different)

    # Agent account (the address that calls rebalance, publishes traces, etc.)
    agent_private_key: str = ""
    agent_address: str = ""  # Will be derived from private key if empty

    # Owner account (for admin operations like oracle price updates)
    owner_private_key: str = ""

    # Contract addresses — set these after deploying via Deploy.s.sol
    usdc_address: str = "0x3600000000000000000000000000000000000000"
    amm_router_address: str = ""
    synthetic_factory_address: str = ""
    vault_factory_address: str = ""
    reasoning_trace_registry_address: str = ""
    asset_registry_address: str = ""

    # Individual synthetic token addresses
    stsla_address: str = ""
    snvda_address: str = ""
    sspy_address: str = ""
    sbtc_address: str = ""
    sgold_address: str = ""

    # Individual oracle addresses
    stsla_oracle_address: str = ""
    snvda_oracle_address: str = ""
    sspy_oracle_address: str = ""
    sbtc_oracle_address: str = ""
    sgold_oracle_address: str = ""

    # Paths
    abi_dir: str = str(
        Path(__file__).resolve().parents[3] / "contracts" / "abis"
    )

    model_config = {"env_prefix": "ARC_", "env_file": ".env", "extra": "ignore"}

    @property
    def agent_account(self) -> LocalAccount | None:
        if not self.agent_private_key:
            return None
        return Account.from_key(self.agent_private_key)

    @property
    def owner_account(self) -> LocalAccount | None:
        if not self.owner_private_key:
            return None
        return Account.from_key(self.owner_private_key)

    @property
    def synth_addresses(self) -> dict[str, str]:
        return {
            "sTSLA": self.stsla_address,
            "sNVDA": self.snvda_address,
            "sSPY": self.sspy_address,
            "sBTC": self.sbtc_address,
            "sGOLD": self.sgold_address,
        }

    @property
    def oracle_addresses(self) -> dict[str, str]:
        return {
            "sTSLA": self.stsla_oracle_address,
            "sNVDA": self.snvda_oracle_address,
            "sSPY": self.sspy_oracle_address,
            "sBTC": self.sbtc_oracle_address,
            "sGOLD": self.sgold_oracle_address,
        }


class ChainClient:
    """Singleton Web3 client for all on-chain interactions."""

    def __init__(self, settings: ChainSettings | None = None):
        self.settings = settings or ChainSettings()
        self.w3 = AsyncWeb3(AsyncHTTPProvider(self.settings.arc_rpc_url))

        # Arc uses POA consensus — add the middleware
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    async def is_connected(self) -> bool:
        try:
            return await self.w3.is_connected()
        except Exception:
            return False

    async def get_chain_id(self) -> int:
        return await self.w3.eth.chain_id

    async def get_block_number(self) -> int:
        return await self.w3.eth.block_number

    async def get_native_balance(self, address: str) -> int:
        return await self.w3.eth.get_balance(address)

    def to_checksum(self, address: str) -> str:
        return self.w3.to_checksum_address(address)

    def to_wei(self, value: float, unit: str = "ether") -> int:
        return self.w3.to_wei(value, unit)

    def from_wei(self, value: int, unit: str = "ether") -> float:
        return self.w3.from_wei(value, unit)


@lru_cache(maxsize=1)
def get_chain_client() -> ChainClient:
    """Get or create the singleton chain client."""
    return ChainClient()


# Module-level convenience
chain_client = get_chain_client()
