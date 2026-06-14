"""Oracle updater — fetches real-world prices and pushes them on-chain.

Implements IOracleUpdater from archimedes/interfaces/chain.py.
Uses yfinance for equity/ETF prices and CoinGecko for crypto.
Pushes prices via Circle Developer Controlled Wallets API (the oracle owner
wallet is a Circle-managed wallet — no raw private key available).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from datetime import UTC, datetime

import aiohttp

from archimedes.models.asset import AssetPrice, MarketSnapshot

logger = logging.getLogger(__name__)

# Symbol → yfinance ticker mapping
YFINANCE_MAP = {
    "sTSLA": "TSLA",
    "sNVDA": "NVDA",
    "sSPY": "SPY",
    "sGOLD": "GC=F",  # Gold futures
    "sOIL": "CL=F",  # WTI crude oil futures
    "sNKY": "^N225",  # Nikkei 225
    "^GSPC": "^GSPC",  # S&P 500 index
    "^VIX": "^VIX",  # VIX index
}

# Symbol → CoinGecko ID
CRYPTO_MAP = {
    "sBTC": "bitcoin",
}

CIRCLE_API_BASE = "https://api.circle.com/v1/w3s"
CIRCLE_BLOCKCHAIN = "ARC-TESTNET"

# ─── Sanity bounds for on-chain pushes (audit #13 / issue #508) ───
# Max allowed move vs the last known good price, in basis points.
# Default mirrors PriceOracle.sol's maxDeviationBps (2000 bps = 20%) so the
# backend rejects a corrupted upstream price before spending a tx the
# contract would revert anyway. Override via ORACLE_MAX_DEVIATION_BPS.
DEFAULT_MAX_DEVIATION_BPS = 2000
# Max age of the upstream observation before we refuse to push it on-chain.
# Override via ORACLE_MAX_UPSTREAM_STALENESS_SECONDS.
DEFAULT_MAX_UPSTREAM_STALENESS_SECONDS = 900  # 15 minutes


def _encrypt_entity_secret(entity_secret_hex: str, public_key_pem: str) -> str:
    """Encrypt entity secret with Circle's RSA public key (OAEP/SHA-256).

    Circle requires a fresh ciphertext per request to prevent replay attacks.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    plaintext = bytes.fromhex(entity_secret_hex)
    ciphertext = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode()


class OracleUpdater:
    """Fetches market prices and pushes them to on-chain PriceOracle contracts."""

    def __init__(self) -> None:
        self._price_cache: dict[str, AssetPrice] = {}
        self._circle_public_key: str | None = None  # cached per instance lifetime

        # Circle credentials from env
        self._api_key: str = os.getenv("CIRCLE_API_KEY", "")
        self._entity_secret: str = os.getenv("CIRCLE_ENTITY_SECRET", "")
        self._wallet_id: str = os.getenv("WALLET_ID", "")

        # Sanity bounds (audit #13 / issue #508)
        self._max_deviation_bps: int = int(os.getenv("ORACLE_MAX_DEVIATION_BPS", str(DEFAULT_MAX_DEVIATION_BPS)))
        self._max_upstream_staleness_s: int = int(
            os.getenv("ORACLE_MAX_UPSTREAM_STALENESS_SECONDS", str(DEFAULT_MAX_UPSTREAM_STALENESS_SECONDS))
        )
        # Last price (6-dec int) we successfully submitted, per symbol —
        # fallback deviation reference when the on-chain read fails.
        self._last_pushed_price_int: dict[str, int] = {}

    # ─── Public API ──────────────────────────────────────────────

    async def fetch_prices(self) -> list[AssetPrice]:
        """Fetch current prices for all synthetic assets via yfinance + CoinGecko."""
        prices: list[AssetPrice] = []
        now = datetime.now(UTC)

        # Fetch equity/ETF/futures prices via yfinance (in thread pool — yfinance is sync)
        equity_symbols = {k: v for k, v in YFINANCE_MAP.items() if k.startswith("s")}
        equity_prices = await asyncio.to_thread(self._fetch_yfinance, equity_symbols, now)
        prices.extend(equity_prices)

        # Fetch crypto prices via CoinGecko API
        crypto_prices = await self._fetch_crypto(now)
        prices.extend(crypto_prices)

        for p in prices:
            self._price_cache[p.symbol] = p

        logger.info(f"Fetched {len(prices)} prices")
        return prices

    async def push_prices_on_chain(self, prices: list[AssetPrice]) -> str | None:
        """Call PriceOracle.setPrice() for each asset via Circle Wallets API."""
        if not self._api_key or not self._entity_secret or not self._wallet_id:
            logger.warning(
                "Circle credentials not configured "
                "(CIRCLE_API_KEY / CIRCLE_ENTITY_SECRET / WALLET_ID) — "
                "skipping on-chain price push"
            )
            return None

        from archimedes.chain.client import chain_client

        oracle_addresses = chain_client.settings.oracle_addresses
        tx_ids: list[str] = []

        async with aiohttp.ClientSession() as session:
            public_key = await self._get_circle_public_key(session)
            if not public_key:
                logger.error("Failed to fetch Circle public key — aborting price push")
                return None

            for price in prices:
                oracle_addr = oracle_addresses.get(price.symbol)
                if not oracle_addr:
                    logger.debug(f"No oracle address for {price.symbol} — skipping")
                    continue

                price_int = int(price.price_usd * 1e6)  # 6 decimals, matches PriceOracle.sol

                # Sanity gate (audit #13 / issue #508): refuse to push prices
                # that are non-positive, stale upstream, or deviate too far
                # from the last known good price.
                rejection = await self._validate_for_push(price, price_int)
                if rejection is not None:
                    logger.warning(f"Refusing to push {price.symbol} price {price.price_usd}: {rejection}")
                    continue

                try:
                    ciphertext = _encrypt_entity_secret(self._entity_secret, public_key)

                    payload = {
                        "idempotencyKey": str(uuid.uuid4()),
                        "walletId": self._wallet_id,
                        "contractAddress": oracle_addr,
                        "abiFunctionSignature": "setPrice(uint256)",
                        "abiParameters": [str(price_int)],
                        "feeLevel": "MEDIUM",
                        "blockchain": CIRCLE_BLOCKCHAIN,
                        "entitySecretCiphertext": ciphertext,
                    }

                    async with session.post(
                        f"{CIRCLE_API_BASE}/developer/transactions/contractExecution",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    ) as resp:
                        body = await resp.json()
                        if resp.status == 201:
                            tx_id = body["data"]["id"]
                            tx_ids.append(tx_id)
                            self._last_pushed_price_int[price.symbol] = price_int
                            logger.info(f"Pushed {price.symbol} price {price.price_usd:.2f} → Circle tx {tx_id}")
                        else:
                            logger.error(f"Circle API error for {price.symbol} ({resp.status}): {body}")
                except Exception:
                    logger.exception(f"Failed to push price for {price.symbol}")

        return tx_ids[0] if tx_ids else None

    async def fetch_market_snapshot(self) -> MarketSnapshot:
        """Fetch a full market snapshot with prices + regime signals."""
        prices = await self.fetch_prices()
        price_map = {p.symbol: p.price_usd for p in prices}
        now = datetime.now(UTC)

        vix = await self._fetch_yfinance_single("^VIX")
        sp500_data = await asyncio.to_thread(self._fetch_sp500_moving_averages)

        return MarketSnapshot(
            timestamp=now,
            prices=price_map,
            vix=vix,
            sp500_ma50=sp500_data.get("ma50"),
            sp500_ma200=sp500_data.get("ma200"),
        )

    def get_cached_price(self, symbol: str) -> AssetPrice | None:
        return self._price_cache.get(symbol)

    # ─── Private helpers ──────────────────────────────────────────

    async def _validate_for_push(self, price: AssetPrice, price_int: int) -> str | None:
        """Sanity-check a price before pushing on-chain (audit #13 / issue #508).

        Returns a human-readable rejection reason, or None when the price is
        safe to push. Checks, in order:

        1. Zero/non-positive guard — the 6-decimal int must be > 0 (the
           contract rejects zero; sub-microdollar floats truncate to 0).
        2. Upstream staleness — the observation must be younger than
           ``ORACLE_MAX_UPSTREAM_STALENESS_SECONDS`` (default 15 min).
        3. Deviation cap — the move vs the last known good price (on-chain
           read, falling back to the last successfully pushed value) must be
           within ``ORACLE_MAX_DEVIATION_BPS`` (default 2000 = 20%, mirroring
           PriceOracle.sol's maxDeviationBps). First-ever pushes with no
           reference are allowed.

        Single-source design (deferred multi-source to v2 per issue #508):
        Each symbol currently has exactly one upstream source (yfinance for
        equities/futures, CoinGecko for sBTC). Multi-source corroboration
        would require N independent feeds; that is a v2 enhancement documented
        in docs/design.md § Price Oracle. Today, we validate upstream
        freshness and deviation bounds against the last known good on-chain
        price, but do not require cross-source agreement. This is an
        intentional tradeoff: simplicity for v1 MVP, and the protocol is
        extensible should a second feed be added.
        """
        if price_int <= 0:
            return f"non-positive on-chain price ({price.price_usd} → {price_int})"

        observed = price.timestamp if price.timestamp.tzinfo else price.timestamp.replace(tzinfo=UTC)
        age_s = (datetime.now(UTC) - observed).total_seconds()
        if age_s > self._max_upstream_staleness_s:
            return f"stale upstream data ({age_s:.0f}s old > {self._max_upstream_staleness_s}s cap)"

        reference_int = await self._get_reference_price_int(price.symbol)
        if reference_int is not None:
            deviation_bps = abs(price_int - reference_int) * 10_000 / reference_int
            if deviation_bps > self._max_deviation_bps:
                return (
                    f"deviation {deviation_bps:.0f} bps vs last known price "
                    f"{reference_int / 1e6:.2f} exceeds {self._max_deviation_bps} bps cap"
                )

        return None

    async def _get_reference_price_int(self, symbol: str) -> int | None:
        """Last known good price (6-dec int): on-chain first, then last pushed.

        Returns None when no reference exists (first-ever push for a symbol).
        """
        try:
            from archimedes.chain.contracts import get_contract_loader

            onchain = await get_contract_loader().oracle_for(symbol).functions.price().call()
            if onchain and int(onchain) > 0:
                return int(onchain)
        except Exception as e:
            logger.warning(f"Could not read on-chain reference price for {symbol}: {e}")
        return self._last_pushed_price_int.get(symbol)

    async def _get_circle_public_key(self, session: aiohttp.ClientSession) -> str | None:
        """Fetch Circle's RSA public key (cached per instance)."""
        if self._circle_public_key:
            return self._circle_public_key
        try:
            async with session.get(
                f"{CIRCLE_API_BASE}/config/entity/publicKey",
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    self._circle_public_key = body["data"]["publicKey"]
                    return self._circle_public_key
                logger.error(f"Failed to fetch Circle public key: {resp.status}")
        except Exception:
            logger.exception("Error fetching Circle public key")
        return None

    def _fetch_yfinance(self, symbols: dict[str, str], timestamp: datetime) -> list[AssetPrice]:
        """Fetch prices from yfinance (sync — call via to_thread)."""
        try:
            import yfinance as yf

            tickers_str = " ".join(symbols.values())
            data = yf.download(tickers_str, period="1d", interval="1m", progress=False)

            results: list[AssetPrice] = []
            for synth_symbol, yf_ticker in symbols.items():
                try:
                    if data.empty:
                        continue
                    if len(symbols) == 1:
                        close = data["Close"]
                        # yfinance >=1.0 returns a 1-column DataFrame (MultiIndex
                        # columns) for single-ticker downloads; squeeze to a Series
                        # before taking the last value.
                        if hasattr(close, "columns"):
                            close = close.iloc[:, 0]
                        price = float(close.iloc[-1])
                    else:
                        close = data["Close"]
                        if yf_ticker in close.columns:
                            price = float(close[yf_ticker].dropna().iloc[-1])
                        else:
                            continue

                    results.append(
                        AssetPrice(
                            symbol=synth_symbol,
                            price_usd=price,
                            timestamp=timestamp,
                            source="yfinance",
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch {synth_symbol}: {e}")

            return results
        except ImportError:
            logger.warning("yfinance not installed — returning empty prices")
            return []

    async def _fetch_crypto(self, timestamp: datetime) -> list[AssetPrice]:
        """Fetch crypto prices from CoinGecko API."""
        results: list[AssetPrice] = []
        try:
            async with aiohttp.ClientSession() as session:
                for symbol, cg_id in CRYPTO_MAP.items():
                    try:
                        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                price = data[cg_id]["usd"]
                                results.append(
                                    AssetPrice(
                                        symbol=symbol,
                                        price_usd=price,
                                        timestamp=timestamp,
                                        source="coingecko",
                                    )
                                )
                    except Exception as e:
                        logger.warning(f"Failed to fetch {symbol} from CoinGecko: {e}")
        except Exception as e:
            logger.warning(f"Crypto fetch error: {e}")
        return results

    async def _fetch_yfinance_single(self, symbol: str) -> float | None:
        """Fetch a single yfinance price (e.g. VIX)."""
        try:
            import yfinance as yf

            data = await asyncio.to_thread(yf.download, symbol, period="1d", interval="1m", progress=False)
            if not data.empty:
                close = data["Close"]
                # yfinance >=1.0 returns a 1-column DataFrame for single-ticker
                # downloads; squeeze to a Series before taking the last value.
                if hasattr(close, "columns"):
                    close = close.iloc[:, 0]
                return float(close.iloc[-1])
        except Exception as e:
            logger.warning(f"Failed to fetch {symbol}: {e}")
        return None

    def _fetch_sp500_moving_averages(self) -> dict[str, float]:
        """Fetch S&P 500 50-day and 200-day moving averages."""
        try:
            import yfinance as yf

            spy = yf.Ticker("^GSPC")
            hist = spy.history(period="1y")
            if hist.empty:
                return {}

            return {
                "ma50": float(hist["Close"].rolling(50).mean().iloc[-1]),
                "ma200": float(hist["Close"].rolling(200).mean().iloc[-1]),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch S&P MA data: {e}")
            return {}
