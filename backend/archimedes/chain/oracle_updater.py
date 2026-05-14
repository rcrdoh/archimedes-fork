"""Oracle updater — fetches real-world prices and pushes them on-chain.

Implements IOracleUpdater from archimedes/interfaces/chain.py.
Uses yfinance for equity/ETF prices and CoinGecko for crypto.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from archimedes.chain.client import chain_client
from archimedes.chain.contracts import ContractLoader, get_contract_loader
from archimedes.models.asset import AssetPrice, MarketSnapshot

logger = logging.getLogger(__name__)

# Symbol → yfinance ticker mapping
YFINANCE_MAP = {
    "sTSLA": "TSLA",
    "sNVDA": "NVDA",
    "sSPY": "SPY",
    "sGOLD": "GC=F",  # Gold futures
    "sOIL": "CL=F",   # WTI crude oil futures
    "sNKY": "^N225",  # Nikkei 225
    "^GSPC": "^GSPC",  # S&P 500 index
    "^VIX": "^VIX",    # VIX index
}

# Symbol → CoinGecko ID
CRYPTO_MAP = {
    "sBTC": "bitcoin",
}


class OracleUpdater:
    """Fetches market prices and pushes them to on-chain PriceOracle contracts."""

    def __init__(self, loader: ContractLoader | None = None):
        self.loader = loader or get_contract_loader()
        self._price_cache: dict[str, AssetPrice] = {}

    async def fetch_prices(self) -> list[AssetPrice]:
        """Fetch current prices for all synthetic assets via yfinance + CoinGecko."""
        prices: list[AssetPrice] = []
        now = datetime.now(timezone.utc)

        # Fetch equity/ETF/futures prices via yfinance (in thread pool — yfinance is sync)
        equity_symbols = {k: v for k, v in YFINANCE_MAP.items() if k.startswith("s")}
        equity_prices = await asyncio.to_thread(self._fetch_yfinance, equity_symbols, now)
        prices.extend(equity_prices)

        # Fetch crypto prices via CoinGecko API
        crypto_prices = await self._fetch_crypto(now)
        prices.extend(crypto_prices)

        # Cache
        for p in prices:
            self._price_cache[p.symbol] = p

        logger.info(f"Fetched {len(prices)} prices")
        return prices

    async def push_prices_on_chain(self, prices: list[AssetPrice]) -> str | None:
        """Call PriceOracle.setPrice() for each asset on Arc."""
        account = chain_client.settings.owner_account
        if not account:
            logger.warning("No owner account configured — skipping on-chain price push")
            return None

        nonce = await chain_client.w3.eth.get_transaction_count(account.address)
        tx_hashes: list[str] = []

        for price in prices:
            try:
                oracle = self.loader.oracle_for(price.symbol)
                # Price in USD with 6 decimals (matching PriceOracle.sol convention)
                price_int = int(price.price_usd * 1e6)

                tx = await oracle.functions.setPrice(price_int).build_transaction(
                    {
                        "from": account.address,
                        "nonce": nonce,
                        "chainId": chain_client.settings.chain_id,
                        "gas": 100_000,
                        "gasPrice": await chain_client.w3.eth.gas_price,
                    }
                )
                signed = account.sign_transaction(tx)
                tx_hash = await chain_client.w3.eth.send_raw_transaction(signed.raw_transaction)
                tx_hashes.append(tx_hash.hex())
                nonce += 1
                logger.info(f"Pushed {price.symbol} price {price.price_usd:.2f} → tx {tx_hash.hex()[:16]}...")
            except Exception as e:
                logger.error(f"Failed to push price for {price.symbol}: {e}")

        return tx_hashes[0] if tx_hashes else None

    async def fetch_market_snapshot(self) -> MarketSnapshot:
        """Fetch a full market snapshot with prices + regime signals."""
        prices = await self.fetch_prices()
        price_map = {p.symbol: p.price_usd for p in prices}
        now = datetime.now(timezone.utc)

        # Fetch regime signals
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

    def _fetch_yfinance(
        self, symbols: dict[str, str], timestamp: datetime
    ) -> list[AssetPrice]:
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
                    # Get the latest close price
                    if len(symbols) == 1:
                        price = float(data["Close"].iloc[-1])
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
            import aiohttp

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
        except ImportError:
            logger.warning("aiohttp not installed — skipping crypto prices")
        return results

    async def _fetch_yfinance_single(self, symbol: str) -> float | None:
        """Fetch a single yfinance price (e.g. VIX)."""
        try:
            import yfinance as yf

            data = await asyncio.to_thread(yf.download, symbol, period="1d", interval="1m", progress=False)
            if not data.empty:
                return float(data["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"Failed to fetch {symbol}: {e}")
        return None

    def _fetch_sp500_moving_averages(self) -> dict[str, float]:
        """Fetch S&P 500 50-day and 200-day moving averages."""
        try:
            import yfinance as yf
            import pandas as pd

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
