"""Feature engineering: prices → indicator matrix. Price/volume-derived ONLY.

Information convention (decided in Phase 1, enforced by tests/test_features.py):

    A feature value at date t may use information up to and including the
    CLOSE of trading day t, and nothing after. Labels are forward returns
    close[t] → close[t+h], so everything known at the close where the trade
    is placed is fair game. The no-look-ahead test perturbs rows after t and
    asserts features at t are unchanged.

    Rolling baselines therefore include day t by default. A baseline excludes
    day t (``.shift(1)``) only where the feature's meaning requires comparing
    today against a PRIOR window: breakouts vs the prior 20-day high,
    distance from the prior 52-week high/low, and relative volume vs the
    prior average. Those shifts are semantic, not leak protection.

yfinance ``.info`` snapshot fields are FORBIDDEN here (CLAUDE.md invariants
1 and 2): they are point-in-time TODAY (look-ahead as historical features)
and constant per ticker (fingerprints that let tree models identify the
ticker and memorize its realized return).
"""

import gc
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .config import Config
from .data import StockData

log = logging.getLogger("quantum_alpha.features")


def _compute_features_for_stock(
    args: Tuple[str, pd.DataFrame]
) -> Tuple[str, Optional[pd.DataFrame]]:
    """Top-level function for multiprocessing (picklable)."""
    ticker, prices = args
    try:
        return ticker, compute_features(prices)
    except Exception:
        return ticker, None


def compute_features(prices: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Pure function: OHLCV → features. No side effects, no external inputs."""
    if len(prices) < 252:
        return None

    close = prices["Close"].astype(np.float64)
    high = prices["High"].astype(np.float64)
    low = prices["Low"].astype(np.float64)
    volume = prices["Volume"].astype(np.float64)
    ret = close.pct_change()

    feat = pd.DataFrame(index=prices.index)

    # --- Price vs moving averages (window includes day t per convention) ---
    for w in [10, 21, 50, 100, 200]:
        feat[f"price_sma_{w}"] = close / close.rolling(w).mean()
        feat[f"price_ema_{w}"] = close / close.ewm(span=w, adjust=False).mean()

    # --- Momentum ---
    for p in [5, 10, 21, 42, 63, 126, 252]:
        feat[f"ret_{p}d"] = close.pct_change(p)

    # Skip-month momentum (Jegadeesh-Titman)
    feat["mom_12_1"] = close.pct_change(252).shift(21)
    feat["mom_6_1"] = close.pct_change(126).shift(21)
    feat["mom_3_1"] = close.pct_change(63).shift(21)

    # --- Volatility ---
    for w in [10, 21, 63]:
        feat[f"vol_{w}d"] = ret.rolling(w).std() * np.sqrt(252)
    feat["vol_ratio"] = feat["vol_21d"] / (feat["vol_63d"] + 1e-8)

    hl_vol = np.log(high / low)
    feat["parkinson_vol_21"] = hl_vol.rolling(21).mean() * np.sqrt(252 / (4 * np.log(2)))

    # --- RSI ---
    for p in [7, 14, 21]:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(p).mean()
        loss = (-delta.clip(upper=0)).rolling(p).mean()
        rs = gain / (loss + 1e-8)
        feat[f"rsi_{p}"] = 100 - 100 / (1 + rs)

    # --- MACD ---
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    feat["macd_hist"] = macd - signal_line
    feat["macd_hist_norm"] = feat["macd_hist"] / (close + 1e-8)

    # --- Bollinger Bands (window includes day t) ---
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    feat["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower + 1e-8)
    feat["bb_width"] = (bb_upper - bb_lower) / (sma20 + 1e-8)

    # --- Volume (baseline = PRIOR window, excludes today: "is today's
    #     volume elevated vs the recent past?") ---
    for w in [5, 21]:
        feat[f"rel_vol_{w}"] = volume / (volume.rolling(w).mean().shift(1) + 1)
    obv = (np.sign(ret.fillna(0)) * volume).cumsum()
    feat["obv_trend"] = obv / (obv.rolling(21).mean().shift(1) + 1e-8)

    # --- Price levels (baseline = PRIOR 52w window: distance from a prior
    #     extreme, so a new high/low registers as > 0 / < 0) ---
    feat["dist_52w_high"] = close / close.rolling(252).max().shift(1) - 1
    feat["dist_52w_low"] = close / close.rolling(252).min().shift(1) - 1

    # --- Breakout (vs PRIOR 20-day high — including today's own high would
    #     make the comparison trivial) ---
    feat["breakout_20d"] = (close > high.rolling(20).max().shift(1)).astype(np.float32)

    # --- Trend regime (window includes day t) ---
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feat["golden_cross_dist"] = sma50 / (sma200 + 1e-8) - 1

    # --- Statistical moments (window includes day t) ---
    feat["skew_21"] = ret.rolling(21).skew()
    feat["kurt_21"] = ret.rolling(21).kurt()
    for w in [21, 50]:
        m = close.rolling(w).mean()
        s = close.rolling(w).std()
        feat[f"zscore_{w}"] = (close - m) / (s + 1e-8)

    # --- Mean reversion signal ---
    feat["mean_rev_5"] = -(ret.rolling(5).sum())
    feat["mean_rev_21"] = -(ret.rolling(21).sum())

    feat = feat.replace([np.inf, -np.inf], np.nan).dropna()
    feat = feat.astype(np.float32)

    return feat if len(feat) > 100 else None


class FeatureEngine:
    """Parallel feature computation with a serial fallback."""

    def __init__(self, config: Config):
        self.config = config

    def compute_all(self, stock_data: Dict[str, StockData]) -> Dict[str, pd.DataFrame]:
        t0 = time.perf_counter()
        args_list = [(ticker, sd.prices) for ticker, sd in stock_data.items()]

        results: Dict[str, pd.DataFrame] = {}
        if self.config.n_workers > 1 and len(args_list) > 4:
            try:
                with ProcessPoolExecutor(max_workers=self.config.n_workers) as pool:
                    futures = {
                        pool.submit(_compute_features_for_stock, args): args[0]
                        for args in args_list
                    }
                    for future in as_completed(futures):
                        ticker, feat = future.result()
                        if feat is not None:
                            results[ticker] = feat
            except (OSError, RuntimeError) as exc:
                log.warning(f"Process pool unavailable ({exc}) — computing serially")
                results = {}

        if not results:
            for args in args_list:
                ticker, feat = _compute_features_for_stock(args)
                if feat is not None:
                    results[ticker] = feat

        elapsed = time.perf_counter() - t0
        log.info(f"Features computed for {len(results)} stocks in {elapsed:.1f}s")
        gc.collect()
        return results
