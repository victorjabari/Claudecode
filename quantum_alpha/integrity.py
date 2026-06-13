"""Measured statistical-integrity claims.

Every claim in the report's integrity section is GENERATED here from an actual
measurement (CLAUDE.md invariant 7), never hardcoded prose. Each check carries
its pass/fail and the number behind it. The label-permutation check is the
falsification GATE: if it fails, the report must not present backtest output
as meaningful (invariant 6).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import Config
from .falsification import (
    lag_features,
    permutation_oof_r2,
    real_oof_r2,
)
from .features import compute_features

log = logging.getLogger("quantum_alpha.integrity")

# Permuted labels carry no signal; OOF R² above this is treated as leakage.
PERMUTATION_R2_TOLERANCE = 0.02
# Lagging features an extra day may lose a little R²; it must not GAIN beyond this.
FEATURE_LAG_TOLERANCE = 0.02


@dataclass
class IntegrityCheck:
    name: str
    passed: bool
    measure: str           # the number behind the claim
    detail: str
    gating: bool = False   # a failed gating check invalidates backtest output

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def check_no_lookahead(sample_prices: pd.DataFrame, seed: int = 17) -> IntegrityCheck:
    """Perturb every row after t; features at ≤ t must be unchanged."""
    name = "No look-ahead (features at t ignore rows after t)"
    if sample_prices is None or len(sample_prices) < 400:
        return IntegrityCheck(name, False, "n/a",
                              "insufficient sample history to test")
    rng = np.random.default_rng(seed)
    t_pos = int(len(sample_prices) * 0.7)
    t = sample_prices.index[t_pos]

    base = compute_features(sample_prices)
    pert = sample_prices.copy()
    later = pert.index > t
    n = int(later.sum())
    factors = rng.uniform(0.5, 1.6, n).astype(np.float32)
    for col in ["Open", "High", "Low", "Close"]:
        pert.loc[later, col] = pert.loc[later, col].values * factors
    pert.loc[later, "Volume"] = rng.integers(1_000, 9_000_000, n)
    pert_feat = compute_features(pert)

    if base is None or pert_feat is None:
        return IntegrityCheck(name, False, "n/a", "feature computation failed")

    a, b = base.loc[:t], pert_feat.loc[:t]
    if not a.index.equals(b.index):
        return IntegrityCheck(name, False, "index mismatch",
                              "perturbation changed which ≤t rows survive")
    max_abs = float(np.nanmax(np.abs(a.values - b.values))) if len(a) else 0.0
    return IntegrityCheck(
        name, max_abs == 0.0, f"max|Δ|≤t = {max_abs:.2e}",
        f"perturbed all rows after {pd.Timestamp(t).date()}; "
        f"compared {len(a)} feature rows at ≤ t",
    )


def check_no_fingerprints(features: Dict[str, pd.DataFrame]) -> IntegrityCheck:
    """No feature is constant within a ticker (a per-ticker fingerprint)."""
    name = "No ticker fingerprints (no static per-ticker columns)"
    static_cols = set()
    n_checked = 0
    for feat in features.values():
        if feat is None or feat.empty:
            continue
        n_checked += 1
        stds = feat.std()
        static_cols |= set(stds[stds == 0].index)
    return IntegrityCheck(
        name, len(static_cols) == 0,
        f"{len(static_cols)} static cols across {n_checked} tickers",
        "static columns: " + (", ".join(sorted(static_cols)) or "none"),
    )


def check_cv_ordering(cv_fold_summary: List[Dict], embargo: int) -> IntegrityCheck:
    """Every fold: position(max train date) + embargo < position(min val date)."""
    name = f"Temporal CV with embargo ({embargo} trading days)"
    if not cv_fold_summary:
        return IntegrityCheck(name, False, "0 folds", "no CV folds recorded")
    gaps = [f["gap_trading_days"] for f in cv_fold_summary]
    all_ok = all(f["ordering_ok"] for f in cv_fold_summary)
    return IntegrityCheck(
        name, all_ok,
        f"min gap {min(gaps)} > embargo {embargo} across {len(cv_fold_summary)} folds",
        "every fold satisfies max(train)+embargo < min(val)" if all_ok
        else "a fold violates the embargo ordering",
    )


def check_costs(bt_results: Dict) -> IntegrityCheck:
    """Costs are applied to every traded dollar.

    The strategy may legitimately trade nothing (stay in cash), in which case
    $0 costs is correct, not a failure. The cost machinery is proven active by
    the equal-weight benchmark, which always trades — so the check passes when
    the rate is configured AND some sim that traded actually paid costs.
    """
    name = "Costs applied (bps/side on traded notional)"
    if "error" in bt_results:
        return IntegrityCheck(name, False, "no backtest", bt_results["error"])
    bps = bt_results.get("cost_bps_per_side", 0)
    costs = bt_results.get("total_costs", 0)
    turn = bt_results.get("turnover_annualized", 0)
    ew = bt_results.get("benchmarks", {}).get("equal_weight", {})
    ew_costs = ew.get("total_costs", 0) if "error" not in ew else 0
    machinery_active = bps >= 10.0 and (costs > 0 or ew_costs > 0)
    note = ("transaction costs charged on every traded dollar"
            if costs > 0 else
            "strategy traded nothing this run ($0 cost is correct); cost "
            "machinery verified via the equal-weight benchmark")
    return IntegrityCheck(
        name, machinery_active,
        f"{bps:.0f} bps/side, strategy ${costs:,.0f} / turnover {turn*100:.0f}%/yr, "
        f"EW ${ew_costs:,.0f}",
        note,
    )


def check_benchmarks(bt_results: Dict) -> IntegrityCheck:
    """SPY and equal-weight benchmarks present on identical dates."""
    name = "Benchmarks on identical dates (SPY + equal-weight)"
    if "error" in bt_results:
        return IntegrityCheck(name, False, "no backtest", bt_results["error"])
    bms = bt_results.get("benchmarks", {})
    ew_ok = "equal_weight" in bms and "error" not in bms["equal_weight"]
    spy_ok = "SPY" in bms and "error" not in bms.get("SPY", {"error": "missing"})
    present = [n for n, ok in [("equal_weight", ew_ok), ("SPY", spy_ok)] if ok]
    return IntegrityCheck(
        name, ew_ok,   # EW is mandatory; SPY may be unavailable offline
        f"present: {', '.join(present) or 'none'}",
        "equal-weight is the apples-to-apples survivor benchmark; "
        + ("SPY available" if spy_ok else "SPY unavailable this run"),
    )


def check_permutation_gate(
    perm_r2s: List[float], real_r2: Optional[float]
) -> IntegrityCheck:
    """GATE: permuted-label OOF R² must collapse to ≈ 0."""
    name = "Falsification gate: permuted-label OOF R² ≈ 0"
    if not perm_r2s:
        return IntegrityCheck(name, False, "not run",
                              "permutation test did not produce an R²",
                              gating=True)
    perm_max = max(perm_r2s)
    perm_mean = float(np.mean(perm_r2s))
    passed = perm_max < PERMUTATION_R2_TOLERANCE
    real_str = f"{real_r2:.4f}" if real_r2 is not None else "n/a"
    return IntegrityCheck(
        name, passed,
        f"perm R² max {perm_max:+.4f} (mean {perm_mean:+.4f}) "
        f"vs real {real_str}, tol {PERMUTATION_R2_TOLERANCE}",
        f"{len(perm_r2s)} permutation round(s); shuffled labels must not predict",
        gating=True,
    )


def check_feature_lag(
    real_r2: Optional[float], lagged_r2: Optional[float]
) -> IntegrityCheck:
    """Lagging features one extra day must not IMPROVE OOF R²."""
    name = "Feature-lag test (extra 1-day lag must not improve R²)"
    if real_r2 is None or lagged_r2 is None:
        return IntegrityCheck(name, False, "not run",
                              "could not compute both R² values")
    delta = lagged_r2 - real_r2
    passed = delta <= FEATURE_LAG_TOLERANCE
    return IntegrityCheck(
        name, passed,
        f"ΔR² (lagged − real) = {delta:+.4f}, tol {FEATURE_LAG_TOLERANCE}",
        f"real {real_r2:+.4f} → lagged {lagged_r2:+.4f}; improvement implies "
        f"the original alignment was leaking",
    )


def survivorship_caveat() -> IntegrityCheck:
    """Always-stated, non-gating disclosure (it is a property of the data)."""
    return IntegrityCheck(
        "Survivorship bias disclosed", True, "current S&P constituents only",
        "yfinance has no delisted tickers; the universe is today's survivors. "
        "The equal-weight benchmark shares this survivor set, so the "
        "strategy-vs-EW comparison nets the bias out partially.",
    )


def gate_passed(checks: List[IntegrityCheck]) -> bool:
    """True only if every gating check passed."""
    return all(c.passed for c in checks if c.gating)


def build_integrity_report(
    *,
    config: Config,
    features: Dict[str, pd.DataFrame],
    all_prices: Dict[str, pd.DataFrame],
    cutoff_date: datetime,
    cv_fold_summary: List[Dict],
    bt_results: Dict,
    run_permutation: bool = True,
    run_feature_lag: bool = True,
    permutation_rounds: int = 1,
) -> List[IntegrityCheck]:
    """Run every measurable integrity check and return the results in order.

    The expensive checks (permutation, feature-lag) each refit the model and
    can be disabled for quick scans; when disabled the gate is reported as
    "not run" and therefore FAILS, so quick scans are never mistaken for
    falsified-and-validated runs.
    """
    checks: List[IntegrityCheck] = []

    sample_prices = next(iter(all_prices.values()), None) if all_prices else None
    checks.append(check_no_lookahead(sample_prices))
    checks.append(check_no_fingerprints(features))
    checks.append(check_cv_ordering(cv_fold_summary,
                                    config.prediction_horizon_days))
    checks.append(check_costs(bt_results))
    checks.append(check_benchmarks(bt_results))

    real_r2 = None
    if run_permutation or run_feature_lag:
        log.info("Integrity: computing real-label OOF R² for falsification...")
        real_r2 = real_oof_r2(features, all_prices, cutoff_date, config)

    if run_permutation:
        log.info(f"Integrity: running {permutation_rounds} label permutation(s)...")
        perm_r2s = permutation_oof_r2(
            features, all_prices, cutoff_date, config,
            n_rounds=permutation_rounds,
        )
        checks.append(check_permutation_gate(perm_r2s, real_r2))
    else:
        checks.append(check_permutation_gate([], real_r2))

    if run_feature_lag:
        log.info("Integrity: running feature-lag test...")
        lagged_r2 = real_oof_r2(
            lag_features(features, k=1), all_prices, cutoff_date, config,
        )
        checks.append(check_feature_lag(real_r2, lagged_r2))

    checks.append(survivorship_caveat())
    return checks
