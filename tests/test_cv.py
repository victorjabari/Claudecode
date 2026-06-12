"""Temporal CV correctness: pooled panel, purged walk-forward splits, embargo.

CLAUDE.md invariant 3 / required test (d): in every fold,
position(max train date) + embargo < position(min val date) on the panel's
trading-day grid.
"""

import numpy as np
import pandas as pd
import pytest

from quantum_alpha.features import FeatureEngine, compute_features
from quantum_alpha.model import (
    PurgedWalkForwardCV,
    ReturnPredictor,
    build_panel,
    cross_sectional_normalise,
)
from tests.conftest import make_universe

HORIZON = 21


@pytest.fixture(scope="module")
def panel_inputs():
    universe = make_universe(n_tickers=6, n_days=700, seed=11)
    features = {t: compute_features(sd.prices) for t, sd in universe.items()}
    prices = {t: sd.prices for t, sd in universe.items()}
    cutoff = max(p.index.max() for p in prices.values()) + pd.Timedelta(days=1)
    return features, prices, cutoff


# ------------------------------------------------------------------- panel
def test_panel_is_date_sorted_multiindex(panel_inputs):
    features, prices, cutoff = panel_inputs
    panel = build_panel(features, prices, HORIZON, cutoff)
    assert panel is not None
    assert list(panel.X.index.names) == ["date", "ticker"]
    dates = panel.dates
    assert dates.is_monotonic_increasing
    assert panel.X.index.equals(panel.y.index)


def test_panel_labels_match_manual_computation(panel_inputs):
    features, prices, cutoff = panel_inputs
    panel = build_panel(features, prices, HORIZON, cutoff)
    ticker = "SYN00"
    close = prices[ticker]["Close"].astype(np.float64)

    rows = panel.y.xs(ticker, level="ticker")
    for t in rows.index[[0, len(rows) // 2, -1]]:
        pos = close.index.get_loc(t)
        expected = close.iloc[pos + HORIZON] / close.iloc[pos] - 1
        assert rows.loc[t] == pytest.approx(expected, rel=1e-10)


def test_panel_label_windows_end_before_cutoff(panel_inputs):
    features, prices, _ = panel_inputs
    some_dates = prices["SYN00"].index
    cutoff = some_dates[len(some_dates) // 2]   # mid-series cutoff
    panel = build_panel(features, prices, HORIZON, cutoff)
    assert panel is not None
    assert (panel.label_end < pd.Timestamp(cutoff)).all()


def test_cross_sectional_normalise_zero_mean_unit_std(panel_inputs):
    features, prices, cutoff = panel_inputs
    panel = build_panel(features, prices, HORIZON, cutoff)
    Xn = cross_sectional_normalise(panel.X)

    col = "ret_21d"
    by_date = Xn[col].groupby(level="date")
    means = by_date.mean()
    stds = by_date.std()
    assert np.allclose(means.values, 0.0, atol=1e-9)
    assert np.allclose(stds.dropna().values, 1.0, atol=1e-6)


# ---------------------------------------------------------------- ordering
def test_every_fold_satisfies_embargoed_ordering(panel_inputs):
    """Required test (d): max(train) + embargo < min(val), in positions."""
    features, prices, cutoff = panel_inputs
    panel = build_panel(features, prices, HORIZON, cutoff)
    sample_dates = panel.dates

    unique_dates = pd.DatetimeIndex(sample_dates.unique()).sort_values()
    pos = {d: i for i, d in enumerate(unique_dates)}

    cv = PurgedWalkForwardCV(n_splits=5, embargo=HORIZON)
    folds = list(cv.split(sample_dates))
    assert len(folds) >= 4

    for train_idx, val_idx in folds:
        train_dates = sample_dates[train_idx]
        val_dates = sample_dates[val_idx]
        assert pos[train_dates.max()] + HORIZON < pos[val_dates.min()], (
            f"embargo violated: train ends {train_dates.max().date()}, "
            f"val starts {val_dates.min().date()}"
        )
        # train and val never share a sample
        assert len(np.intersect1d(train_idx, val_idx)) == 0


def test_folds_walk_forward_and_grow():
    dates = pd.bdate_range("2020-01-01", periods=500)
    sample_dates = pd.DatetimeIndex(np.repeat(dates, 3))
    cv = PurgedWalkForwardCV(n_splits=5, embargo=21)

    folds = list(cv.split(sample_dates))
    assert len(folds) == 5
    prev_train_len = 0
    prev_val_start = None
    for train_idx, val_idx in folds:
        assert len(train_idx) > prev_train_len      # expanding train window
        prev_train_len = len(train_idx)
        val_start = sample_dates[val_idx].min()
        if prev_val_start is not None:
            assert val_start > prev_val_start       # forward-marching folds
        prev_val_start = val_start


# -------------------------------------------------------------- integration
def test_predictor_fit_records_clean_folds_and_sane_r2(fast_config):
    """Integration + leak canary: on pure-noise returns the purged OOF R²
    must sit at ≈ 0. A clearly positive value means temporal leakage."""
    universe = make_universe(n_tickers=8, n_days=700, seed=5)   # momentum=0
    engine = FeatureEngine(fast_config)
    features = engine.compute_all(universe)
    prices = {t: sd.prices for t, sd in universe.items()}
    cutoff = max(p.index.max() for p in prices.values()) + pd.Timedelta(days=1)

    predictor = ReturnPredictor(fast_config)
    predictor.fit(features, prices, cutoff)

    assert predictor.is_fitted
    assert predictor.cv_fold_summary, "no CV folds recorded"
    assert all(f["ordering_ok"] for f in predictor.cv_fold_summary)
    assert all(
        f["gap_trading_days"] > f["embargo"] for f in predictor.cv_fold_summary
    )

    assert predictor.oof_r2 is not None
    assert predictor.oof_r2 < 0.05, (
        f"OOF R²={predictor.oof_r2:.4f} on pure-noise labels — leakage"
    )

    preds = predictor.predict_batch(features)
    assert set(preds) == set(features)
    for p in preds.values():
        assert p["ci_low"] <= p["expected_return"] <= p["ci_high"]
        assert 0.0 <= p["confidence"] <= 1.0
