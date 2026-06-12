"""Feature invariants: no look-ahead, no static columns, no .info columns."""

import numpy as np
import pandas as pd

from quantum_alpha.features import compute_features
from tests.conftest import make_ohlcv

FORBIDDEN_INFO_COLUMNS = [
    "pe_ratio", "forward_pe", "pb_ratio", "revenue_growth", "earnings_growth",
    "profit_margin", "roe", "debt_to_equity", "beta", "dividend_yield",
    "peg_ratio",
]


def _perturb_after(prices: pd.DataFrame, t: pd.Timestamp, seed: int = 99) -> pd.DataFrame:
    """Garble every row strictly after t (prices and volume)."""
    rng = np.random.default_rng(seed)
    out = prices.copy()
    later = out.index > t
    n = int(later.sum())
    assert n > 0, "perturbation window is empty — pick an earlier t"
    factors = rng.uniform(0.5, 1.6, n).astype(np.float32)
    for col in ["Open", "High", "Low", "Close"]:
        out.loc[later, col] = out.loc[later, col].values * factors
    out.loc[later, "Volume"] = rng.integers(1_000, 9_000_000, n)
    return out


def test_no_lookahead_features_at_t_ignore_rows_after_t():
    """CLAUDE.md invariant 1 / required test (a).

    Convention: a feature at date t may use information up to and including
    the close of day t. Perturbing every row after t must leave all feature
    values at and before t bit-for-bit unchanged.
    """
    prices = make_ohlcv(n_days=600, seed=3)
    feats_full = compute_features(prices)
    assert feats_full is not None

    for t_pos in [320, 450, 580]:
        t = prices.index[t_pos]
        feats_pert = compute_features(_perturb_after(prices, t, seed=t_pos))
        assert feats_pert is not None

        upto_full = feats_full.loc[:t]
        upto_pert = feats_pert.loc[:t]
        # Same rows must survive dropna on both sides...
        assert upto_full.index.equals(upto_pert.index)
        # ...and every value at ≤ t must be identical.
        pd.testing.assert_frame_equal(upto_full, upto_pert)


def test_no_forbidden_info_columns():
    """The .info-derived columns removed in Phase 1 must never reappear."""
    feats = compute_features(make_ohlcv(n_days=400, seed=1))
    assert feats is not None
    present = [c for c in FORBIDDEN_INFO_COLUMNS if c in feats.columns]
    assert present == [], f".info-derived feature columns found: {present}"


def test_no_static_per_ticker_columns():
    """CLAUDE.md invariant 2 (structural half): no feature may be constant
    within a ticker's history — constants act as ticker fingerprints."""
    for seed in range(3):
        feats = compute_features(make_ohlcv(n_days=700, seed=seed))
        assert feats is not None
        stds = feats.std()
        static = list(stds[stds == 0].index)
        assert static == [], f"static (fingerprint) columns: {static}"
