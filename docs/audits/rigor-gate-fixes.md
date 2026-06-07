# Rigor Gate — Required Fixes

## HIGH: DSR threshold inconsistency (fusion vs curated path)

`backend/archimedes/services/fusion_evaluator.py:423`

Fusion path uses `dsr > 0.0` (p ≈ 0.5); curated path uses `dsr_p_value >= 0.95`.
A generated strategy with z=0.5 (p=0.69) is admitted Tier-1 by fusion but fails the API gate.

```python
# fusion_evaluator.py apply_rigor_gate()
- dsr_pass = dsr is not None and dsr > 0.0
+ dsr_pass = dsr_p_value is not None and dsr_p_value >= 0.95
```

Also update `passing` to use `dsr_p_value` directly:
```python
- passing = metrics.sharpe_ratio > 0.0 and dsr_pass and look_ahead_clean and (pbo_score is None or pbo_score < 0.5)
+ passing = dsr_pass and look_ahead_clean and (pbo_score is None or pbo_score < 0.5)
```

---

## MEDIUM: Synthetic-returns fallback creates circular DSR validation

`backend/archimedes/api/selection_bias_routes.py:114-121`

When no real backtest data exists, synthetic returns are seeded from `stub_sharpe` then
passed through DSR. Gate trivially passes because the data was constructed to hit that Sharpe.

```python
# selection_bias_routes.py evaluate_rigor_gate()
- for s in strategies:
-     if (s.id not in returns_by_strategy or len(returns_by_strategy[s.id]) < 10) and s.stub_sharpe is not None:
-         returns_by_strategy[s.id] = _synthetic_returns_from_stub(sharpe=s.stub_sharpe, ...)
```

Strategies with no real backtest data should report all gate fields as MISSING, not synthesize a passing series.

---

## MEDIUM: Kelly fraction uses full in-sample returns

`backend/archimedes/api/strategies_routes.py:578-581`

`real_sharpe` and `real_cagr` are full-period IS metrics. Kelly fraction shown to users is inflated vs OOS edge.

```python
# strategies_routes.py
- mu_ann = s.real_cagr if s.real_cagr is not None else 0.08
- vol_ann = abs(mu_ann / sr) if sr != 0 else 0.20
+ sr_oos = s.real_oos_sharpe if s.real_oos_sharpe is not None else sr
+ vol_ann = abs(mu_ann / sr) if sr != 0 else 0.20   # vol unchanged
+ full_kelly = mu_ann / max(vol_ann**2, 1e-6)        # keep; shrink via sr_oos
+ base_kelly = min(0.5 * (sr_oos / max(sr, 1e-6)) * full_kelly, 0.5)
```

---

## MEDIUM: Look-ahead audit passes pandas `.iloc[-1]` / `.tail(1)`

`backend/archimedes/services/rigor_evaluator.py:593-595`

The `USub` branch hits bare `pass` — all negative subscripts are silently allowed.
Safe for backtrader (where `[-N]` = N bars ago), but would not catch `df.iloc[-1]` in
pandas-based strategy code.

```python
# look_ahead_audit(), ast.Subscript handling
  if isinstance(slice_val, ast.UnaryOp) and isinstance(slice_val.op, ast.USub):
-     pass
+     # Safe in backtrader; potentially future data in pandas context.
+     warnings.append(
+         f"Line {node.lineno}: negative index — verify this is backtrader "
+         f"(bars-ago) not pandas (last-row) access."
+     )
```

---

## LOW: Artifact records `slippage_bps: 0` while 10 bps tx cost covers that role

`backend/archimedes/services/portfolio_backtester.py:476`

```python
- "slippage_bps": 0,
+ "slippage_bps": tx_cost_bps,   # proportional cost covers spread + commissions
```

---

## LOW: CPCV always MISSING — never passed to run_rigor_gate

`backend/archimedes/api/selection_bias_routes.py:165-174`

`cv_returns_matrix` is never constructed and never passed to `run_rigor_gate`.
CPCV shows as MISSING on every strategy in the UI. Either wire it or remove the claim.

Short-term: update pitch/UI copy to say "three statistical primitives" (DSR + PBO + OOS Sharpe)
until CPCV is wired from real rolling-window re-backtests.
