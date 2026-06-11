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
}


def resolve_operations(operations: list[str]) -> list[str]:
    normalized = [op.upper() for op in operations]
    unsupported = [op for op in normalized if op not in OPERATION_TO_SYMBOL]
    if unsupported:
        raise ValueError(f"Unsupported operation(s): {', '.join(unsupported)}")
    return normalized
