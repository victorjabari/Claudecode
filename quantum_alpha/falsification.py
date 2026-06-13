"""Falsification tools: label permutation and feature lagging.

These are the adversarial checks that gate every result (CLAUDE.md invariant
6). The logic is here; tests/test_falsification.py and the integrity report
consume it.

Label permutation
-----------------
Shuffle the forward-return labels WITHIN each date (preserving each date's
cross-sectional label distribution, destroying the feature→label link). A
correct pipeline then has nothing to learn, so out-of-fold R² must collapse
to ≈ 0. If permuting the labels still "wins" (clearly positive R², or a
shuffled strategy that beats its benchmark), the pipeline is leaking — the
change that produced it must be reverted, not kept.

Feature lag
-----------
Shift every feature one extra day before labelling. If performance IMPROVES
under the extra lag, the original alignment was using information too late to
be tradable (a leak); correct alignment can only lose a little information,
never gain.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import Config
from .model import ReturnPredictor

log = logging.getLogger("quantum_alpha.falsification")


def permute_labels_within_date(y: pd.Series, seed: int = 0) -> pd.Series:
    """Permute label values within each date group.

    ``y`` is the panel target indexed by (date, ticker). Returns a Series with
    the same index whose values are shuffled among the tickers sharing each
    date, so the marginal per-date label distribution is untouched but no
    ticker keeps its own label.
    """
    rng = np.random.default_rng(seed)
    out = y.copy()
    dates = out.index.get_level_values("date")
    for _, pos in pd.Series(np.arange(len(out)), index=dates).groupby(level=0):
        idx = pos.values
        if len(idx) > 1:
            out.iloc[idx] = out.iloc[rng.permutation(idx)].values
    return out


def make_label_permuter(seed: int = 0):
    """A label_shuffler closure for ReturnPredictor.fit / Backtester.run."""
    return lambda y: permute_labels_within_date(y, seed=seed)


def lag_features(
    all_features: Dict[str, pd.DataFrame], k: int = 1
) -> Dict[str, pd.DataFrame]:
    """Shift every ticker's feature frame ``k`` rows later in time.

    The value formerly available at the close of day t now appears at day
    t+k, i.e. the model sees STALER information. Performance must not improve.
    """
    lagged = {}
    for ticker, feat in all_features.items():
        if feat is None or feat.empty:
            continue
        shifted = feat.shift(k).dropna()
        if len(shifted) > 100:
            lagged[ticker] = shifted
    return lagged


def permutation_oof_r2(
    all_features: Dict[str, pd.DataFrame],
    all_prices: Dict[str, pd.DataFrame],
    cutoff_date: datetime,
    config: Config,
    n_rounds: int = 1,
    base_seed: int = 1000,
) -> List[float]:
    """Out-of-fold R² over ``n_rounds`` independent label permutations."""
    r2s: List[float] = []
    for k in range(n_rounds):
        predictor = ReturnPredictor(config)
        predictor.fit(
            all_features, all_prices, cutoff_date,
            label_shuffler=make_label_permuter(seed=base_seed + k),
        )
        if predictor.oof_r2 is not None:
            r2s.append(predictor.oof_r2)
    return r2s


def real_oof_r2(
    all_features: Dict[str, pd.DataFrame],
    all_prices: Dict[str, pd.DataFrame],
    cutoff_date: datetime,
    config: Config,
) -> Optional[float]:
    """Out-of-fold R² with the true (unshuffled) labels."""
    predictor = ReturnPredictor(config)
    predictor.fit(all_features, all_prices, cutoff_date)
    return predictor.oof_r2
