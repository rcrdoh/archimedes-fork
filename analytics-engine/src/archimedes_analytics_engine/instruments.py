from __future__ import annotations

OPERATION_TO_SYMBOL: dict[str, str] = {
    "SPY": "SPY",
    "NIKKEI": "^N225",
    "GOLD": "GC=F",
    "TREASURY": "TLT",
    "OIL": "CL=F",
    # ETF legs for relative-value / pairs strategies (Gatev et al. 2006).
    "GLD": "GLD",  # SPDR Gold Shares — tradeable gold ETF leg
    "GDX": "GDX",  # VanEck Gold Miners ETF — co-moves with GLD, the divergent leg
    "IVV": "IVV",  # iShares Core S&P 500 — near-cointegrated with SPY (sanity-check pair)
    # Second-wave economic pairs (Phase 1.3): same Gatev distance method, new pairs.
    "KO": "KO",  # The Coca-Cola Company — consumer-staples beverage leg (KO/PEP pair)
    "PEP": "PEP",  # PepsiCo Inc. — same-industry substitute to KO (KO/PEP pair)
    "EWA": "EWA",  # iShares MSCI Australia ETF — commodity-exporter economy (EWA/EWC pair)
    "EWC": "EWC",  # iShares MSCI Canada ETF — commodity-exporter economy (EWA/EWC pair)
    "SLV": "SLV",  # iShares Silver Trust — silver leg of the gold/silver ratio (GLD/SLV pair)
    # ── Expanded investable universe (2026-06) ───────────────────────────────
    # Liquid, US-listed (synchronous-close) ETFs so cross-sectional / portfolio
    # strategies can be tested on a larger and/or more diversified universe than
    # the original 5 operations. All have ~2004+ history. See the universe
    # experiment in docs/specs/second-wave-universe-experiment.md for which
    # composition suits which strategy (and why bigger ≠ automatically better).
    # Broad equity building blocks.
    "QQQ": "QQQ",  # Invesco QQQ — US large-cap growth / tech
    "IWM": "IWM",  # iShares Russell 2000 — US small-cap
    "EFA": "EFA",  # iShares MSCI EAFE — developed ex-US equity
    "EEM": "EEM",  # iShares MSCI Emerging Markets equity
    # Fixed income + alternatives (low-correlation diversifiers for risk parity).
    "IEF": "IEF",  # iShares 7-10yr Treasury — intermediate duration (TLT = long duration)
    "DBC": "DBC",  # Invesco DB Commodity Index — broad commodities
    "VNQ": "VNQ",  # Vanguard Real Estate — US REITs
    # SPDR sector ETFs — a homogeneous cross-section for sector-rotation momentum.
    "XLB": "XLB",  # Materials
    "XLE": "XLE",  # Energy
    "XLF": "XLF",  # Financials
    "XLI": "XLI",  # Industrials
    "XLK": "XLK",  # Technology
    "XLP": "XLP",  # Consumer Staples
    "XLU": "XLU",  # Utilities
    "XLV": "XLV",  # Health Care
    "XLY": "XLY",  # Consumer Discretionary
}


def resolve_operations(operations: list[str]) -> list[str]:
    normalized = [op.upper() for op in operations]
    unsupported = [op for op in normalized if op not in OPERATION_TO_SYMBOL]
    if unsupported:
        raise ValueError(f"Unsupported operation(s): {', '.join(unsupported)}")
    return normalized
