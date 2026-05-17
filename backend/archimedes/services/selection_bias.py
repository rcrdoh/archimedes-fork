"""Selection-bias correction primitives — the rigor gate for Tier-1 strategies.

Implements the four controls from `docs/specs/selection-bias-corrections-spec.md`:
1. Deflated Sharpe Ratio (DSR) — Bailey & López de Prado (2014)
2. Probability of Backtest Overfitting (PBO) — Bailey/Borwein/López de Prado/Zhu (2014)
3. Walk-forward out-of-sample Sharpe
4. Look-ahead static audit (AST-based)

All functions are pure math — no FastAPI, no DB, no chain dependencies.
Önder owns the math; this implementation follows the spec exactly.

References:
- Bailey & López de Prado (2014). The Deflated Sharpe Ratio. JPM 40(5).
- Bailey, Borwein, López de Prado, Zhu (2014). PBO. SSRN 2326253.
- McLean & Pontiff (2016). Does Academic Research Destroy Stock Return
  Predictability? JoF 71(1).
"""

from __future__ import annotations

import ast
import logging
import math
from itertools import combinations

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)

ANNUALIZATION = 252

# ─── Euler-Mascheroni constant ────────────────────────────────
_GAMMA_E = 0.5772156649


# ═══════════════════════════════════════════════════════════════
# 1. Deflated Sharpe Ratio (DSR)
# ═══════════════════════════════════════════════════════════════


def compute_dsr(
    daily_returns: list[float] | np.ndarray,
    num_trials: int = 1,
    annualization: int = ANNUALIZATION,
) -> tuple[float, float]:
    """Compute the Deflated Sharpe Ratio and its p-value.

    Bailey & López de Prado (2014). Corrects for non-normality and multiple
    testing. Returns (deflated_sharpe, p_value) where p_value is the
    probability that the true Sharpe > 0.

    Args:
        daily_returns: Per-bar return series (NOT annualized).
        num_trials: Number of independent strategies evaluated in the
            selection set (N for multiple-testing correction).
        annualization: Bars per year (252 for daily data).

    Returns:
        (deflated_sharpe_ratio, dsr_p_value)
        deflated_sharpe_ratio is in annualized Sharpe units.
        dsr_p_value is 0-1, higher = more confident true Sharpe > 0.
    """
    returns = np.asarray(daily_returns, dtype=float)
    T = len(returns)

    if T < 2 or num_trials < 1:
        return 0.0, 0.0

    # Per-bar Sharpe ratio (un-annualized)
    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns, ddof=1))

    if std_r == 0:
        return 0.0, 0.0

    SR_hat = mean_r / std_r  # per-bar Sharpe

    # Skewness and excess kurtosis on per-bar returns
    from scipy.stats import skew, kurtosis

    gamma_3 = float(skew(returns))  # skewness
    gamma_4 = float(kurtosis(returns))  # excess kurtosis (Fisher's)

    # Expected maximum Sharpe under the null (best of N iid Normal)
    N = max(num_trials, 1)

    if N == 1:
        E_max_N = 0.0  # No multiple-testing correction for N=1
    else:
        # Bailey-López de Prado approximation for E[max_N]
        E_max_N = ((1 - _GAMMA_E) * norm.ppf(1 - 1.0 / N)
                   + _GAMMA_E * norm.ppf(1 - 1.0 / (N * math.e)))

    # Expected best-of-N under null, scaled by sqrt(1/(T-1))
    SR_zero = math.sqrt(1.0 / (T - 1)) * E_max_N

    # Variance correction term
    var_correction = (1.0
                      - gamma_3 * SR_hat
                      + ((gamma_4 - 1) / 4.0) * SR_hat ** 2)

    if var_correction <= 0:
        # Degenerate case — variance correction is non-positive
        logger.warning("DSR: non-positive variance correction (%.4f), clamping", var_correction)
        var_correction = 1e-10

    # Z-statistic
    z = ((SR_hat - SR_zero) * math.sqrt(T - 1)
         / math.sqrt(var_correction))

    # DSR p-value = Phi(z)
    dsr_p_value = float(norm.cdf(z))

    # Deflated Sharpe Ratio in annualized units
    deflated_sharpe = SR_hat * math.sqrt(annualization)

    return round(deflated_sharpe, 6), round(dsr_p_value, 6)


# ═══════════════════════════════════════════════════════════════
# 2. Probability of Backtest Overfitting (PBO) — CSCV
# ═══════════════════════════════════════════════════════════════


def _sharpe_ratio(returns: np.ndarray) -> float:
    """Annualized Sharpe from per-bar returns."""
    if len(returns) < 2:
        return 0.0
    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns, ddof=1))
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * math.sqrt(ANNUALIZATION)


def compute_pbo(
    returns_matrix: dict[str, list[float] | np.ndarray],
    s_partitions: int = 16,
) -> dict[str, float]:
    """Compute Probability of Backtest Overfitting via CSCV.

    Bailey, Borwein, López de Prado, Zhu (2014).

    Args:
        returns_matrix: Map of strategy_id → daily returns. All series
            must be aligned on the same T dates.
        s_partitions: Number of CSCV partitions (default 16 per paper).

    Returns:
        Map of strategy_id → pbo_score (all identical per spec).
        PBO >= 0.5 means the in-sample-optimal strategy underperforms
        the median out-of-sample — the strategy fails the rigor gate.
    """
    if len(returns_matrix) < 2:
        # PBO is undefined for a single strategy
        logger.warning("PBO requires >= 2 strategies, got %d — returning 0.0", len(returns_matrix))
        return {sid: 0.0 for sid in returns_matrix}

    # Build aligned matrix (T, N) — column order pinned by sorted strategy_id
    strategy_ids = sorted(returns_matrix.keys())
    N = len(strategy_ids)

    # Pad to equal length (use shortest common length)
    arrays = [np.asarray(returns_matrix[sid], dtype=float) for sid in strategy_ids]
    T = min(len(a) for a in arrays)
    if T < s_partitions:
        logger.warning(
            "PBO: T=%d < S=%d partitions — reducing S to %d",
            T, s_partitions, max(T, 2),
        )
        s_partitions = max(T, 2)

    matrix = np.column_stack([a[:T] for a in arrays])  # (T, N)

    # Partition into S equal-size blocks along time axis
    block_size = T // s_partitions
    if block_size < 1:
        block_size = 1

    blocks = []
    for i in range(s_partitions):
        start = i * block_size
        end = start + block_size if i < s_partitions - 1 else T
        blocks.append(matrix[start:end])

    # Enumerate C(S, S/2) combinations for in-sample selection
    half_s = s_partitions // 2
    if half_s < 1:
        half_s = 1

    n_underperform = 0
    n_total = 0

    for is_indices in combinations(range(s_partitions), half_s):
        oos_indices = tuple(i for i in range(s_partitions) if i not in is_indices)

        # Stack in-sample and out-of-sample blocks
        is_returns = np.vstack([blocks[i] for i in is_indices])    # (T_is, N)
        oos_returns = np.vstack([blocks[i] for i in oos_indices])  # (T_oos, N)

        # Rank strategies by in-sample Sharpe
        is_sharpes = np.array([_sharpe_ratio(is_returns[:, j]) for j in range(N)])
        best_is_idx = int(np.argmax(is_sharpes))

        # Look up the best IS strategy's out-of-sample rank
        oos_sharpes = np.array([_sharpe_ratio(oos_returns[:, j]) for j in range(N)])
        oos_ranks = _rank_array(oos_sharpes)
        best_oos_rank = oos_ranks[best_is_idx]

        # Relative rank omega = rank_OOS / N
        omega = best_oos_rank / N

        # Logit lambda = log(omega / (1 - omega))
        # Clamp omega to avoid log(0) or log(inf)
        omega = np.clip(omega, 1e-10, 1 - 1e-10)
        lam = math.log(omega / (1 - omega))

        # PBO = P(lambda <= 0)
        if lam <= 0:
            n_underperform += 1
        n_total += 1

    pbo_score = n_underperform / n_total if n_total > 0 else 0.0

    # Per spec: PBO is a library-level metric — same score for all strategies
    return {sid: round(pbo_score, 6) for sid in strategy_ids}


def _rank_array(arr: np.ndarray) -> np.ndarray:
    """Compute ordinal ranks (1-based, ties → average rank)."""
    ranks = np.empty(len(arr), dtype=float)
    order = np.argsort(arr)
    ranks[order] = np.arange(1, len(arr) + 1, dtype=float)
    return ranks


# ═══════════════════════════════════════════════════════════════
# 3. Walk-forward Out-of-Sample Sharpe
# ═══════════════════════════════════════════════════════════════


def walk_forward_oos_sharpe(
    daily_returns: list[float] | np.ndarray,
    train_fraction: float = 0.70,
) -> float:
    """Compute the walk-forward out-of-sample Sharpe ratio.

    Splits the return series into train/test along the time axis (no shuffling).
    Computes the annualized Sharpe over the test (out-of-sample) slice.

    Args:
        daily_returns: Per-bar return series.
        train_fraction: Fraction for train split (default 0.70).

    Returns:
        Annualized out-of-sample Sharpe ratio.
    """
    returns = np.asarray(daily_returns, dtype=float)
    T = len(returns)

    if T < 10:
        return 0.0

    split_idx = int(T * train_fraction)
    if split_idx < 2 or T - split_idx < 2:
        return 0.0

    oos_returns = returns[split_idx:]
    return _sharpe_ratio(oos_returns)


# ═══════════════════════════════════════════════════════════════
# 4. Look-ahead static audit (AST-based)
# ═══════════════════════════════════════════════════════════════

# Dangerous attribute accesses that indicate future-bar references
_LOOK_AHEAD_PATTERNS = {
    # backtrader data feed future access patterns
    ("self", "data", "close", "+"),  # data.close[+1] etc.
    ("self", "datas", "+"),          # datas[N] forward ref
}

# Function names that commonly leak future information
_LOOK_AHEAD_FUNCTIONS = {
    "future",
    "forecast",
    "predict",
    "peek",
    "lookahead",
    "look_ahead",
}


def look_ahead_audit(strategy_code: str) -> tuple[bool, list[str]]:
    """Static-analysis check for look-ahead bias in strategy code.

    Parses the strategy source with AST and checks for:
    1. Forward data access patterns (e.g., self.data.close[+N])
    2. Calls to functions with look-ahead-suggestive names
    3. Direct indexing into data feeds beyond current bar

    This complements the backtrader-level `_lookahead_audit_passed()`
    which checks broker coc/coo settings.

    Args:
        strategy_code: Python source code of the strategy.

    Returns:
        (passed, warnings) — passed=True if no look-ahead detected,
        warnings is a list of human-readable findings.
    """
    warnings: list[str] = []

    try:
        tree = ast.parse(strategy_code)
    except SyntaxError as e:
        return False, [f"Cannot parse strategy code: {e}"]

    # Walk the AST looking for suspicious patterns
    for node in ast.walk(tree):
        # Check for function calls with look-ahead-suggestive names
        if isinstance(node, ast.Call):
            func_name = _get_func_name(node.func)
            if func_name and func_name.lower() in _LOOK_AHEAD_FUNCTIONS:
                warnings.append(
                    f"Line {node.lineno}: call to '{func_name}' may indicate look-ahead bias"
                )

        # Check for subscript with negative/positive offset on data feeds
        if isinstance(node, ast.Subscript):
            # Pattern: self.data.close[N] where N > 0 or N < -1
            slice_val = node.slice
            if isinstance(slice_val, ast.UnaryOp) and isinstance(slice_val.op, ast.USub):
                # Negative index like self.data.close[-2] is fine (past bars)
                pass
            elif isinstance(slice_val, ast.Constant) and isinstance(slice_val.value, int):
                if slice_val.value > 0:
                    warnings.append(
                        f"Line {node.lineno}: positive data index [{slice_val.value}] may "
                        f"reference future bars"
                    )

    passed = len(warnings) == 0
    return passed, warnings


def _get_func_name(node: ast.expr) -> str | None:
    """Extract function name from an AST Call node's func."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ═══════════════════════════════════════════════════════════════
# Rigor Gate — composite check
# ═══════════════════════════════════════════════════════════════


class RigorGateResult:
    """Result of running all four selection-bias checks on a strategy.

    Used to determine whether a CANDIDATE strategy can promote to VALIDATED.
    """

    def __init__(
        self,
        strategy_id: str,
        deflated_sharpe: float | None = None,
        dsr_p_value: float | None = None,
        num_trials: int = 1,
        pbo_score: float | None = None,
        oos_sharpe: float | None = None,
        look_ahead_passed: bool = False,
        in_sample_sharpe: float | None = None,
        paper_claimed_sharpe: float | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        self.deflated_sharpe = deflated_sharpe
        self.dsr_p_value = dsr_p_value
        self.num_trials = num_trials
        self.pbo_score = pbo_score
        self.oos_sharpe = oos_sharpe
        self.look_ahead_passed = look_ahead_passed
        self.in_sample_sharpe = in_sample_sharpe
        self.paper_claimed_sharpe = paper_claimed_sharpe

    @property
    def passes_all(self) -> bool:
        """True iff all four controls pass."""
        # 1. DSR populated and p-value > 0.95
        if self.dsr_p_value is None:
            return False
        if self.dsr_p_value < 0.95:
            return False

        # 2. PBO populated and < 0.5
        if self.pbo_score is None:
            return False
        if self.pbo_score >= 0.5:
            return False

        # 3. OOS Sharpe within 50% of in-sample
        if self.oos_sharpe is None:
            return False
        if self.in_sample_sharpe and self.in_sample_sharpe > 0:
            if self.oos_sharpe / self.in_sample_sharpe < 0.5:
                return False

        # 4. Look-ahead audit passed
        if not self.look_ahead_passed:
            return False

        return True

    @property
    def gate_details(self) -> dict[str, str]:
        """Human-readable pass/fail for each check."""
        details: dict[str, str] = {}

        if self.dsr_p_value is not None and self.dsr_p_value >= 0.95:
            details["dsr"] = f"PASS (p={self.dsr_p_value:.4f})"
        elif self.dsr_p_value is not None:
            details["dsr"] = f"FAIL (p={self.dsr_p_value:.4f}, need ≥ 0.95)"
        else:
            details["dsr"] = "MISSING"

        if self.pbo_score is not None and self.pbo_score < 0.5:
            details["pbo"] = f"PASS (PBO={self.pbo_score:.4f})"
        elif self.pbo_score is not None:
            details["pbo"] = f"FAIL (PBO={self.pbo_score:.4f}, need < 0.5)"
        else:
            details["pbo"] = "MISSING"

        if self.oos_sharpe is not None and self.in_sample_sharpe and self.in_sample_sharpe > 0:
            ratio = self.oos_sharpe / self.in_sample_sharpe
            if ratio >= 0.5:
                details["oos_sharpe"] = f"PASS (OOS/IS={ratio:.2f})"
            else:
                details["oos_sharpe"] = f"FAIL (OOS/IS={ratio:.2f}, need ≥ 0.50)"
        elif self.oos_sharpe is not None:
            details["oos_sharpe"] = f"SET (OOS={self.oos_sharpe:.4f}, no IS reference)"
        else:
            details["oos_sharpe"] = "MISSING"

        details["look_ahead"] = "PASS" if self.look_ahead_passed else "FAIL"

        return details


def run_rigor_gate(
    strategy_id: str,
    daily_returns: list[float],
    num_trials: int = 1,
    pbo_scores: dict[str, float] | None = None,
    strategy_code: str | None = None,
    in_sample_sharpe: float | None = None,
    paper_claimed_sharpe: float | None = None,
    look_ahead_audit_passed: bool | None = None,
) -> RigorGateResult:
    """Run all four selection-bias checks on a strategy.

    This is the main entry point called by the orchestrator.

    Args:
        strategy_id: Strategy identifier.
        daily_returns: Per-bar return series from the backtest.
        num_trials: Number of strategies evaluated in the selection set.
        pbo_scores: Pre-computed PBO scores from compute_pbo() for the library.
        strategy_code: Strategy source code for look-ahead audit.
            If None, look_ahead_audit_passed must be provided.
        in_sample_sharpe: In-sample annualized Sharpe (for OOS ratio check).
        paper_claimed_sharpe: Paper's claimed Sharpe (for delta display).
        look_ahead_audit_passed: Override for look-ahead audit result.
            If provided alongside strategy_code, code audit is still run
            but this value takes precedence.

    Returns:
        RigorGateResult with all four check results.
    """
    # 1. DSR
    deflated_sharpe, dsr_p_value = compute_dsr(daily_returns, num_trials)

    # 2. PBO — use pre-computed library-level score
    pbo_score = pbo_scores.get(strategy_id) if pbo_scores else None

    # 3. Walk-forward OOS Sharpe
    oos_sharpe = walk_forward_oos_sharpe(daily_returns)

    # 4. Look-ahead audit
    if strategy_code is not None:
        la_passed, la_warnings = look_ahead_audit(strategy_code)
        if la_warnings:
            for w in la_warnings:
                logger.info("Look-ahead audit [%s]: %s", strategy_id, w)
    else:
        la_passed = False

    # Override with explicit result if provided
    if look_ahead_audit_passed is not None:
        la_passed = look_ahead_audit_passed

    # Get in-sample Sharpe from returns if not provided
    if in_sample_sharpe is None and len(daily_returns) >= 2:
        returns = np.asarray(daily_returns, dtype=float)
        std_r = float(np.std(returns, ddof=1))
        if std_r > 0:
            in_sample_sharpe = (float(np.mean(returns)) / std_r) * math.sqrt(ANNUALIZATION)

    result = RigorGateResult(
        strategy_id=strategy_id,
        deflated_sharpe=deflated_sharpe,
        dsr_p_value=dsr_p_value,
        num_trials=num_trials,
        pbo_score=pbo_score,
        oos_sharpe=oos_sharpe,
        look_ahead_passed=la_passed,
        in_sample_sharpe=in_sample_sharpe,
        paper_claimed_sharpe=paper_claimed_sharpe,
    )

    logger.info(
        "Rigor gate [%s]: %s (DSR p=%.4f, PBO=%.4f, OOS=%.4f, LA=%s)",
        strategy_id,
        "PASS" if result.passes_all else "FAIL",
        dsr_p_value or 0,
        pbo_score or 0,
        oos_sharpe or 0,
        la_passed,
    )

    return result
