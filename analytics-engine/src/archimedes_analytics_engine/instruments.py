from __future__ import annotations

OPERATION_TO_SYMBOL: dict[str, str] = {
    "SPY": "SPY",
    "NIKKEI": "^N225",
    "GOLD": "GC=F",
    "TREASURY": "TLT",
    "OIL": "CL=F",
}


def resolve_operations(operations: list[str]) -> list[str]:
    normalized = [op.upper() for op in operations]
    unsupported = [op for op in normalized if op not in OPERATION_TO_SYMBOL]
    if unsupported:
        raise ValueError(f"Unsupported operation(s): {', '.join(unsupported)}")
    return normalized
