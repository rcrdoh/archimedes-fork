from archimedes_analytics_engine.instruments import (
    OPERATION_TO_SYMBOL,
    resolve_operations,
)


def test_operations_include_required_assets() -> None:
    # The original five operation assets must always be present.
    assert {"SPY", "NIKKEI", "GOLD", "TREASURY", "OIL"} <= set(OPERATION_TO_SYMBOL.keys())


def test_operations_include_pairs_legs() -> None:
    # ETF legs added for the Gatev et al. (2006) relative-value pairs strategy.
    assert {"GLD", "GDX", "IVV"} <= set(OPERATION_TO_SYMBOL.keys())


def test_operations_include_second_wave_pair_legs() -> None:
    # Phase 1.3 economic pairs: KO/PEP, EWA/EWC, GLD/SLV (GLD already present above).
    assert {"KO", "PEP", "EWA", "EWC", "SLV"} <= set(OPERATION_TO_SYMBOL.keys())


def test_resolve_operations_rejects_unknown() -> None:
    try:
        resolve_operations(["SPY", "BAD"])
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "Unsupported operation" in str(exc)
