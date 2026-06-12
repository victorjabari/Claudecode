"""Feature engineering: prices → indicator matrix.

NOTE (Phase 0): feature definitions are carried over from quantum_alpha_v5.py
unchanged, including the `.info`-derived static columns and inconsistent
shifting. Phase 1 deletes the static columns and settles the shift convention.
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
    args: Tuple[str, pd.DataFrame, Dict]
) -> Tuple[str, Optional[pd.DataFrame]]:
    """Top-level function for multiprocessing (picklable)."""
    ticker, prices, info = args
    try:
        return ticker, compute_features(ticker, prices, info)
    except Exception:
        return ticker, None


def compute_features(
    ticker: str, prices: pd.DataFrame, info: Dict
) -> Optional[pd.DataFrame]:
    """Pure function: prices → features. No side effects."""
    if len(prices) < 252:
        return None

    close = prices["Close"].astype(np.float64)
    high = prices["High"].astype(np.float64)
    low = prices["Low"].astype(np.float64)
    volume = prices["Volume"].astype(np.float64)
    ret = close.pct_change()

    feat = pd.DataFrame(index=prices.index)

    # --- Price vs moving averages ---
    for w in [10, 21, 50, 100, 200]:
        sma = close.rolling(w).mean()
        feat[f"price_sma_{w}"] = close / sma.shift(1)
        ema = close.ewm(span=w, adjust=False).mean()
        feat[f"price_ema_{w}"] = close / ema.shift(1)

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

    # --- Bollinger Bands ---
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    feat["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower + 1e-8)
    feat["bb_width"] = (bb_upper - bb_lower) / (sma20 + 1e-8)

    # --- Volume ---
    for w in [5, 21]:
        feat[f"rel_vol_{w}"] = volume / (volume.rolling(w).mean().shift(1) + 1)
    obv = (np.sign(ret.fillna(0)) * volume).cumsum()
    feat["obv_trend"] = obv / (obv.rolling(21).mean().shift(1) + 1e-8)

    # --- Price levels ---
    feat["dist_52w_high"] = close / close.rolling(252).max().shift(1) - 1
    feat["dist_52w_low"] = close / close.rolling(252).min().shift(1) - 1

    # --- Breakout ---
    feat["breakout_20d"] = (close > high.rolling(20).max().shift(1)).astype(np.float32)

    # --- Trend regime ---
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feat["golden_cross_dist"] = sma50.shift(1) / (sma200.shift(1) + 1e-8) - 1

    # --- Statistical moments ---
    feat["skew_21"] = ret.rolling(21).skew()
    feat["kurt_21"] = ret.rolling(21).kurt()
    for w in [21, 50]:
        m = close.rolling(w).mean().shift(1)
        s = close.rolling(w).std().shift(1)
        feat[f"zscore_{w}"] = (close - m) / (s + 1e-8)

    # --- Mean reversion signal ---
    feat["mean_rev_5"] = -(ret.rolling(5).sum())
    feat["mean_rev_21"] = -(ret.rolling(21).sum())

    # --- Fundamental features (static per fetch — Phase 1 deletes these:
    #     point-in-time-today snapshots are look-ahead as historical features
    #     and act as per-ticker fingerprints) ---
    feat["pe_ratio"] = _info_float(info, "trailingPE")
    feat["forward_pe"] = _info_float(info, "forwardPE")
    feat["pb_ratio"] = _info_float(info, "priceToBook")
    feat["revenue_growth"] = _info_float(info, "revenueGrowth")
    feat["earnings_growth"] = _info_float(info, "earningsGrowth")
    feat["profit_margin"] = _info_float(info, "profitMargins")
    feat["roe"] = _info_float(info, "returnOnEquity")
    feat["debt_to_equity"] = _info_float(info, "debtToEquity")
    feat["beta"] = _info_float(info, "beta", default=1.0)
    feat["dividend_yield"] = _info_float(info, "dividendYield")
    feat["peg_ratio"] = _info_float(info, "pegRatio")

    feat = feat.replace([np.inf, -np.inf], np.nan).dropna()
    feat = feat.astype(np.float32)

    return feat if len(feat) > 100 else None


def _info_float(info: Dict, key: str, default: float = 0.0) -> float:
    try:
        value = float(info.get(key))
        return value if np.isfinite(value) else default
    except (TypeError, ValueError):
        return default


class FeatureEngine:
    """Parallel feature computation with a serial fallback."""

    def __init__(self, config: Config):
        self.config = config

    def compute_all(self, stock_data: Dict[str, StockData]) -> Dict[str, pd.DataFrame]:
        t0 = time.perf_counter()
        args_list = [
            (ticker, sd.prices, sd.info) for ticker, sd in stock_data.items()
        ]

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
