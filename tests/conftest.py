"""Shared test fixtures: synthetic OHLCV data (tests only — real runs use yfinance)."""

from typing import Dict, Optional

import numpy as np
import pandas as pd
import pytest

from quantum_alpha.config import Config
from quantum_alpha.data import StockData


def make_ohlcv(
    n_days: int = 900,
    seed: int = 0,
    start: str = "2021-01-04",
    mu: float = 0.0002,
    sigma: float = 0.015,
    momentum: float = 0.0,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Synthetic OHLCV frame shaped like the data layer's output.

    ``momentum`` > 0 plants a genuine, correctly-aligned signal: today's drift
    leans on the trailing 21-day mean return, so past-return features carry
    real information about forward returns.
    """
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start, periods=n_days)

    rets = np.zeros(n_days)
    shocks = rng.normal(mu, sigma, n_days)
    for t in range(n_days):
        drift = 0.0
        if momentum > 0 and t >= 21:
            drift = momentum * rets[t - 21:t].mean()
        rets[t] = drift + shocks[t]

    close = start_price * np.exp(np.cumsum(rets))
    open_ = close * np.exp(rng.normal(0, 0.003, n_days))
    spread = np.abs(rng.normal(0, 0.008, n_days)) + 0.001
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = rng.integers(500_000, 5_000_000, n_days)

    df = pd.DataFrame(
        {
            "Open": open_.astype(np.float32),
            "High": high.astype(np.float32),
            "Low": low.astype(np.float32),
            "Close": close.astype(np.float32),
            "Volume": volume.astype(np.int64),
        },
        index=index,
    )
    df.index.freq = None   # real fetched data carries no freq; parquet drops it
    return df


def make_universe(
    n_tickers: int = 8,
    n_days: int = 900,
    seed: int = 0,
    momentum: float = 0.0,
    info: Optional[Dict] = None,
) -> Dict[str, StockData]:
    """Synthetic universe of StockData objects."""
    universe = {}
    sectors = ["Tech", "Health", "Energy", "Finance"]
    for i in range(n_tickers):
        ticker = f"SYN{i:02d}"
        prices = make_ohlcv(n_days=n_days, seed=seed + i, momentum=momentum)
        tinfo = dict(info or {})
        tinfo.setdefault("sector", sectors[i % len(sectors)])
        tinfo.setdefault("marketCap", 5e9 + i * 1e9)
        tinfo.setdefault("averageVolume", 2_000_000)
        universe[ticker] = StockData(
            ticker=ticker,
            prices=prices,
            info=tinfo,
            sector=tinfo["sector"],
            market_cap=tinfo["marketCap"],
        )
    return universe


@pytest.fixture
def fast_config(tmp_path) -> Config:
    """Small/fast Config for tests: tiny forests, serial features, tmp cache."""
    return Config(
        rf_n_estimators=30,
        rf_min_samples_leaf=20,
        gb_n_estimators=30,
        gb_min_samples_leaf=20,
        n_cv_folds=4,
        n_workers=1,
        cache_dir=str(tmp_path / "cache"),
        fetch_retries=0,
    )
