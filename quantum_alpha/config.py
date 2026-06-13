"""Configuration. Every tunable in one place; no magic numbers buried in logic.

Config is FROZEN: build a new instance with the values you want
(e.g. ``Config(prediction_horizon_days=42)``). Never mutate class attributes —
dataclass defaults are baked into __init__ at class-creation time, so a
class-attribute write after definition silently does nothing for existing
construction paths (the old ``--horizon`` CLI bug).
"""

import os
from dataclasses import dataclass
from typing import Tuple

N_CORES = os.cpu_count() or 4
# Reserve 2 cores for OS + background.
WORKER_CORES = max(1, min(N_CORES - 2, 8))


@dataclass(frozen=True)
class Config:
    # --- Signal thresholds ---
    min_expected_return: float = 0.05        # 5% min predicted return
    confidence_threshold: float = 0.40       # model agreement threshold

    # --- Universe filters (applied to real data) ---
    min_market_cap: float = 2_000_000_000    # $2B minimum (liquid mid+large cap)
    min_avg_volume: float = 500_000          # 500k shares/day
    min_price: float = 5.0
    max_price: float = 10_000.0
    max_universe_size: int = 150

    # --- Portfolio construction ---
    max_position_size: float = 0.10
    max_sector_exposure: float = 0.30
    max_positions: int = 20
    min_positions: int = 3
    risk_free_rate: float = 0.045            # ~4.5% T-bill
    min_weight_threshold: float = 0.02
    cash_reserve: float = 0.05               # 5% cash buffer

    # --- Prediction ---
    prediction_horizon_days: int = 21        # 1 month, in trading days
    lookback_days: int = 756                 # 3 years of history
    ml_train_window: int = 504               # 2 years training

    # --- Backtest ---
    rebalance_frequency_days: int = 21
    backtest_retrain_frequency: int = 63
    transaction_cost_bps: float = 10.0       # per side, on traded notional
    trading_days_per_year: int = 252

    # --- ML ---
    n_cv_folds: int = 5
    rf_n_estimators: int = 300
    rf_max_depth: int = 8
    rf_min_samples_leaf: int = 50
    gb_n_estimators: int = 200
    gb_max_depth: int = 4
    gb_learning_rate: float = 0.03
    gb_min_samples_leaf: int = 50
    gb_subsample: float = 0.75
    random_seed: int = 42

    # --- Uncertainty ---
    bootstrap_percentiles: Tuple[float, float] = (10.0, 90.0)  # 80% interval
    n_bootstrap_samples: int = 100

    # --- Workers ---
    n_workers: int = WORKER_CORES

    # --- Data fetch / cache ---
    yfinance_batch_size: int = 50            # tickers per yfinance batch call
    cache_dir: str = "data/cache"
    cache_max_age_hours: float = 24.0        # skip the network when fresher
    fetch_retries: int = 4
    fetch_backoff_base: float = 2.0          # 2s, 4s, 8s, 16s
