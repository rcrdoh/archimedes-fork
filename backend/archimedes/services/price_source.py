"""Pluggable off-chain price sources — Pyth Hermes (pull) + admin override.

North Star §10.5: the yfinance → Pyth Hermes source upgrade. Pyth's Hermes HTTP
API serves sub-second, ~5s-fresh prices with confidence intervals across
crypto / FX / metals / commodities / equities, keyed by the SAME feed IDs the
on-chain Pyth contract uses (live on Arc) — so it doubles as mainnet-ready
provenance. **Zero smart-contract change:** `PriceOracle.sol`'s `setPrice(uint256)`
interface is untouched; only *where* the off-chain price comes from changes.

This module adds the NEW primitives:
  • ``fetch_pyth_prices(symbols)`` — batch HTTP read from Hermes → ``AssetPrice``s,
    stamped with Pyth's own ``publish_time`` so downstream staleness gates work.
  • ``load_admin_prices()`` — a manual override map from env (last-resort / demo).
  • ``price_source_mode()`` — the ``PRICE_SOURCE`` env switch.
  • ``merge_fill(primary, fallback)`` — pure cascade combinator (fill gaps).

yfinance stays where it already lives (``oracle_updater._fetch_yfinance`` /
``asset_market_service``) and is the cascade's fallback for the symbols Pyth does
not cover cleanly (S&P 500 index, VIX, Nikkei, WTI-spot today). The call sites
compose: **Pyth → yfinance → admin**, gated by ``PRICE_SOURCE`` (default
``yfinance`` = current behavior, so a deploy changes nothing until the flag flips).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

import aiohttp

from archimedes.models.asset import AssetPrice

logger = logging.getLogger(__name__)

#: Hermes base URL (overridable via env for a self-hosted/region endpoint).
PYTH_HERMES_DEFAULT_URL = "https://hermes.pyth.network"

#: Synth symbol → Pyth price-feed id (verified live against the Hermes catalog,
#: 2026-06-30). Only the cleanly-mapped subset is here; symbols absent from this
#: map (sOIL = WTI futures, sNKY = Nikkei, ^GSPC = S&P 500 index, ^VIX) fall back
#: to yfinance via the cascade. Extend this map as Pyth coverage / our universe
#: grows. Feed ids are the canonical Pyth ids (no ``0x`` prefix needed for Hermes).
PYTH_FEED_IDS: dict[str, str] = {
    "sTSLA": "16dad506d7db8da01c87581c87ca897a012a153557d4d578c3b9c9e1bc0632f1",  # Equity.US.TSLA/USD
    "sNVDA": "b1073854ed24cbc755dc527418f52b7d271f6cc967bbf8d8129112b18860a593",  # Equity.US.NVDA/USD
    "sSPY": "19e09bb805456ada3979a7d1cbb4b6d63babc3a0f8e8a9509f68afa5c4c11cd5",  # Equity.US.SPY/USD
    "sGOLD": "765d2ba906dbc32ca17cc11f5310a89e9ee1f6420508c63861f2f8ba4ee34bb2",  # Metal.XAU/USD
    "sBTC": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",  # Crypto.BTC/USD
}


def price_source_mode() -> str:
    """The active price-source mode: 'yfinance' (default), 'cascade', or 'pyth_hermes'.

    - ``yfinance``    — unchanged legacy behavior (no Pyth).
    - ``cascade``     — Pyth for covered symbols, yfinance for the rest, admin override.
    - ``pyth_hermes`` — Pyth only for covered symbols (still admin-overridable); the
                        caller decides whether to also fall back to yfinance.
    """
    return os.getenv("PRICE_SOURCE", "yfinance").strip().lower()


def hermes_base_url() -> str:
    return os.getenv("PYTH_HERMES_URL", PYTH_HERMES_DEFAULT_URL).rstrip("/")


def _parse_hermes_price(entry: dict, symbol: str, fallback_ts: datetime) -> AssetPrice | None:
    """Map one Hermes ``parsed`` entry → AssetPrice. None if non-positive/garbled.

    Hermes returns price as an integer mantissa + exponent: value = price·10^expo.
    The observation is stamped with Pyth's ``publish_time`` (epoch seconds) so the
    downstream oracle staleness gate sees the TRUE upstream age — which is exactly
    how an off-hours, stale equity feed gets correctly rejected and falls back.
    """
    try:
        p = entry["price"]
        value = int(p["price"]) * (10 ** int(p["expo"]))
        if value <= 0:
            return None
        publish_time = int(p.get("publish_time", 0))
        ts = datetime.fromtimestamp(publish_time, tz=UTC) if publish_time > 0 else fallback_ts
        return AssetPrice(symbol=symbol, price_usd=float(value), timestamp=ts, source="pyth_hermes")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        logger.warning("Pyth parse failed for %s: %s", symbol, exc)
        return None


async def fetch_pyth_prices(
    symbols: list[str],
    *,
    base_url: str | None = None,
    session: aiohttp.ClientSession | None = None,
    timeout_s: float = 8.0,
) -> dict[str, AssetPrice]:
    """Batch-read latest Pyth prices for the mapped subset of ``symbols``.

    Returns ``{symbol: AssetPrice}`` for the symbols Pyth covers + successfully
    reads. Fail-safe: any HTTP/parse error returns ``{}`` so the cascade falls
    back. Never raises.
    """
    feed_to_symbol = {PYTH_FEED_IDS[s]: s for s in symbols if s in PYTH_FEED_IDS}
    if not feed_to_symbol:
        return {}

    base = (base_url or hermes_base_url()).rstrip("/")
    params = [("ids[]", fid) for fid in feed_to_symbol]
    now = datetime.now(UTC)

    own_session = session is None
    sess = session or aiohttp.ClientSession()
    try:
        async with sess.get(
            f"{base}/v2/updates/price/latest",
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                logger.warning("Pyth Hermes returned HTTP %s", resp.status)
                return {}
            payload = await resp.json()
    except Exception as exc:
        logger.warning("Pyth Hermes fetch failed: %s", exc)
        return {}
    finally:
        if own_session:
            await sess.close()

    out: dict[str, AssetPrice] = {}
    for entry in payload.get("parsed", []) or []:
        fid = str(entry.get("id", "")).removeprefix("0x")
        symbol = feed_to_symbol.get(fid)
        if not symbol:
            continue
        price = _parse_hermes_price(entry, symbol, now)
        if price is not None:
            out[symbol] = price
    return out


def load_admin_prices() -> dict[str, AssetPrice]:
    """Manual price overrides from ``ADMIN_PRICES_JSON`` (inline JSON or a file path).

    Shape: ``{"sSPY": 512.3, "sBTC": 61000}``. Last-resort / demo override; applies
    on top of whatever the cascade produced. Empty + non-fatal when unset/garbled.
    """
    raw = os.getenv("ADMIN_PRICES_JSON", "").strip()
    if not raw:
        return {}
    try:
        if raw.startswith("{"):
            mapping = json.loads(raw)
        elif os.path.isfile(raw):
            with open(raw) as fh:
                mapping = json.load(fh)
        else:
            return {}
        now = datetime.now(UTC)
        out: dict[str, AssetPrice] = {}
        for sym, val in mapping.items():
            try:
                out[sym] = AssetPrice(symbol=sym, price_usd=float(val), timestamp=now, source="admin")
            except (ValueError, TypeError):
                continue
        return out
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("ADMIN_PRICES_JSON unreadable: %s", exc)
        return {}


def merge_fill(primary: dict[str, AssetPrice], fallback: dict[str, AssetPrice]) -> dict[str, AssetPrice]:
    """Pure cascade combinator: ``primary`` wins; ``fallback`` fills only the gaps."""
    merged = dict(fallback)
    merged.update(primary)
    return merged
