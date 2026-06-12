"""CLAUDE.md invariant 2 (behavioural half): static per-ticker features must
have NO out-of-sample predictive power.

A model trained on static-only features can only memorize each ticker's
realized mean return. On a temporally embargoed validation set of pure-noise
returns, that memorization must score OOF R² ≤ 0 (within noise) — and if it
ever scores clearly above zero, per-ticker constants are leaking realized
returns into X.
"""

import numpy as np
from sklearn.ensemble import RandomForestRegressor

from tests.conftest import make_ohlcv

HORIZON = 21


def _build_static_panel(n_tickers=12, n_days=700, n_static=5, seed=7):
    rng = np.random.default_rng(seed)
    X_rows, y_vals, dates = [], [], []
    for i in range(n_tickers):
        prices = make_ohlcv(n_days=n_days, seed=200 + i)   # pure noise returns
        close = prices["Close"].astype(np.float64)
        fwd = (close.shift(-HORIZON) / close - 1).dropna()
        static_row = rng.normal(size=n_static)             # ticker fingerprint
        for date, y in fwd.items():
            X_rows.append(static_row)
            y_vals.append(y)
            dates.append(date)
    X = np.asarray(X_rows)
    y = np.asarray(y_vals)
    dates = np.asarray(dates)
    return X, y, dates


def test_static_only_features_score_oof_r2_at_most_zero():
    X, y, dates = _build_static_panel()
    unique_dates = np.unique(dates)

    # Temporal split with an embargo of one full horizon between train and val
    # (forward-return labels overlap for HORIZON days).
    split = int(len(unique_dates) * 0.7)
    train_end = unique_dates[split]
    val_start = unique_dates[split + HORIZON]
    train_mask = dates <= train_end
    val_mask = dates >= val_start
    assert train_mask.sum() > 1000 and val_mask.sum() > 500

    model = RandomForestRegressor(
        n_estimators=100, max_depth=8, min_samples_leaf=20, random_state=0,
    )
    model.fit(X[train_mask], y[train_mask])

    r2_train = model.score(X[train_mask], y[train_mask])
    r2_val = model.score(X[val_mask], y[val_mask])

    # In-sample the fingerprints memorize (this is exactly why they are
    # banned); out of sample they must be worthless.
    assert r2_train > 0.0
    assert r2_val <= 0.02, (
        f"static-only features scored OOF R²={r2_val:.4f} > 0 — "
        f"per-ticker constants are leaking realized returns"
    )
