"""Falsification suite: label permutation (the gate), feature-lag, integrity.

CLAUDE.md invariant 6 / required test (b): shuffling forward-return labels
within each date must destroy all predictive power.
"""

import numpy as np
import pandas as pd
import pytest

from quantum_alpha.falsification import (
    lag_features,
    permutation_oof_r2,
    permute_labels_within_date,
    real_oof_r2,
)
from quantum_alpha.features import FeatureEngine, compute_features
from quantum_alpha.integrity import (
    build_integrity_report,
    gate_passed,
)
from tests.conftest import make_universe


@pytest.fixture(scope="module")
def momentum_panel():
    """A universe with a genuine, correctly-aligned momentum signal, plus its
    features/prices/cutoff. Shared across the slower model-refit tests."""
    universe = make_universe(n_tickers=10, n_days=750, seed=31, momentum=3.0)
    features = {t: compute_features(sd.prices) for t, sd in universe.items()}
    prices = {t: sd.prices for t, sd in universe.items()}
    cutoff = max(p.index.max() for p in prices.values()) + pd.Timedelta(days=1)
    return universe, features, prices, cutoff


# ----------------------------------------------------------- permute helper
def test_permute_preserves_per_date_distribution():
    idx = pd.MultiIndex.from_product(
        [pd.bdate_range("2024-01-01", periods=20), [f"T{i}" for i in range(6)]],
        names=["date", "ticker"],
    )
    y = pd.Series(np.random.default_rng(0).normal(size=len(idx)), index=idx)
    shuffled = permute_labels_within_date(y, seed=1)

    assert shuffled.index.equals(y.index)
    for date in y.index.get_level_values("date").unique():
        a = np.sort(y.xs(date, level="date").values)
        b = np.sort(shuffled.xs(date, level="date").values)
        assert np.allclose(a, b)   # same multiset per date


# --------------------------------------------------- the falsification gate
@pytest.mark.slow
def test_permuted_labels_collapse_oof_r2(momentum_panel):
    """With a real signal the model learns something; once labels are
    permuted within each date, OOF R² must collapse to ≈ 0."""
    _, features, prices, cutoff = momentum_panel
    fast = _fast_cfg()

    real = real_oof_r2(features, prices, cutoff, fast)
    perm = permutation_oof_r2(features, prices, cutoff, fast, n_rounds=3)

    assert real is not None and perm
    assert max(perm) < 0.02, f"permuted R² did not collapse: {perm}"
    # The genuine signal should beat every permutation round.
    assert real > max(perm)


@pytest.mark.slow
def test_feature_lag_does_not_improve_r2(momentum_panel):
    """Lagging features one extra day must not IMPROVE OOF R²."""
    _, features, prices, cutoff = momentum_panel
    fast = _fast_cfg()

    real = real_oof_r2(features, prices, cutoff, fast)
    lagged = real_oof_r2(lag_features(features, k=1), prices, cutoff, fast)

    assert real is not None and lagged is not None
    assert lagged <= real + 0.02, (
        f"extra lag improved R² ({real:.4f} → {lagged:.4f}) — original "
        f"alignment was leaking"
    )


# --------------------------------------------------------- integrity report
@pytest.mark.slow
def test_integrity_report_passes_gate_on_clean_pipeline(momentum_panel):
    universe, features, prices, cutoff = momentum_panel
    fast = _fast_cfg()

    # Minimal bt_results stub exercising the cost/benchmark checks.
    bt_results = {
        "cost_bps_per_side": 10.0, "total_costs": 1234.0,
        "turnover_annualized": 1.5,
        "benchmarks": {
            "equal_weight": {"cagr": 0.1}, "SPY": {"cagr": 0.08},
        },
    }
    # Need a real cv_fold_summary → fit once.
    real_r2 = real_oof_r2(features, prices, cutoff, fast)  # noqa: F841

    checks = build_integrity_report(
        config=fast, features=features, all_prices=prices, cutoff_date=cutoff,
        cv_fold_summary=[{"gap_trading_days": 40, "embargo": 21,
                          "ordering_ok": True}],
        bt_results=bt_results,
        run_permutation=True, run_feature_lag=True, permutation_rounds=2,
    )
    by_name = {c.name: c for c in checks}

    # Gate present and passing.
    gate = [c for c in checks if c.gating]
    assert len(gate) == 1 and gate[0].passed
    assert gate_passed(checks)

    # Spot-check the non-gating measured claims.
    assert any("No look-ahead" in n and by_name[n].passed for n in by_name)
    assert any("fingerprint" in n.lower() and by_name[n].passed for n in by_name)
    assert any("Costs applied" in n and by_name[n].passed for n in by_name)


def test_gate_fails_when_falsification_not_run():
    """A quick scan that skips the permutation refit must NOT read as
    validated: the gate reports not-run and therefore fails."""
    fast = _fast_cfg()
    universe = make_universe(n_tickers=5, n_days=500, seed=9)
    features = {t: compute_features(sd.prices) for t, sd in universe.items()}
    prices = {t: sd.prices for t, sd in universe.items()}
    cutoff = max(p.index.max() for p in prices.values()) + pd.Timedelta(days=1)

    checks = build_integrity_report(
        config=fast, features=features, all_prices=prices, cutoff_date=cutoff,
        cv_fold_summary=[{"gap_trading_days": 40, "embargo": 21,
                          "ordering_ok": True}],
        bt_results={"error": "skipped"},
        run_permutation=False, run_feature_lag=False,
    )
    assert not gate_passed(checks)


def _fast_cfg():
    from quantum_alpha.config import Config
    return Config(
        rf_n_estimators=40, rf_min_samples_leaf=15,
        gb_n_estimators=40, gb_min_samples_leaf=15,
        n_cv_folds=4, n_workers=1,
    )
