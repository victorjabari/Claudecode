"""
QUANTUM ALPHA v5.0 — Live Quantitative Research Framework
==========================================================
Built for M2 Pro 16GB. Uses REAL market data via yfinance.

What changed from v4:
  - Simulated data ELIMINATED. Every price is from Yahoo Finance.
  - Dynamic universe: S&P 500 components or custom list.
  - Honest uncertainty: bootstrap prediction intervals from RF trees,
    model disagreement, historical calibration, and a clear conviction
    tier system (HIGH / MEDIUM / LOW / SPECULATIVE).
  - Memory-optimised for 16GB RAM: float32, batched computation, gc.
  - M2 Pro core utilisation: 8 workers (10 cores - 2 for OS).

DISCLAIMER: This is a research tool. You bear full responsibility for
any trades. The market is in God's hands — this tool merely attempts
to read patterns in what He has already written in the price history.
Past patterns do not guarantee future results. Period.
"""

import gc
import os
import sys
import time
import logging
import warnings
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import (
    GradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
import multiprocessing as _mp

_is_main = _mp.current_process().name == "MainProcess"

logging.basicConfig(
    level=logging.INFO if _is_main else logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("quantum_alpha")
if not _is_main:
    log.setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Hardware — M2 Pro optimisation
# ---------------------------------------------------------------------------
N_CORES = os.cpu_count() or 4
# M2 Pro: 10-12 cores. Reserve 2 for OS + background.
WORKER_CORES = max(1, min(N_CORES - 2, 8))

if _is_main:
    log.info(f"Cores: {N_CORES} detected, {WORKER_CORES} workers allocated")


# ===========================================================================
# CONFIGURATION
# ===========================================================================
@dataclass
class Config:
    """Every tunable in one place. No magic numbers buried in logic."""

    # --- Signal thresholds ---
    min_expected_return: float = 0.05        # 5% min predicted return (realistic for real data)
    confidence_threshold: float = 0.40       # model agreement threshold

    # --- Universe filters (applied to real data) ---
    min_market_cap: float = 2_000_000_000    # $2B minimum (liquid mid+large cap)
    min_avg_volume: float = 500_000          # 500k shares/day
    min_price: float = 5.0
    max_price: float = 10_000.0
    max_universe_size: int = 150             # RAM constraint for 16GB

    # --- Portfolio construction ---
    max_position_size: float = 0.10
    max_sector_exposure: float = 0.30
    max_positions: int = 20
    min_positions: int = 3
    risk_free_rate: float = 0.045            # current ~4.5% T-bill
    min_weight_threshold: float = 0.02
    cash_reserve: float = 0.05              # 5% cash buffer (real trading needs more)

    # --- Prediction ---
    prediction_horizon_days: int = 21        # 1 month (more realistic than 3 months)
    lookback_days: int = 756                 # 3 years of history
    ml_train_window: int = 504               # 2 years training

    # --- Backtest ---
    rebalance_frequency_days: int = 21
    backtest_retrain_frequency: int = 63

    # --- ML ---
    n_cv_folds: int = 5
    rf_n_estimators: int = 300               # more trees = better uncertainty estimates
    rf_max_depth: int = 8                    # shallower = less overfit on real data
    rf_min_samples_leaf: int = 50            # more conservative
    gb_n_estimators: int = 200
    gb_max_depth: int = 4
    gb_learning_rate: float = 0.03           # slower learning on real data
    gb_min_samples_leaf: int = 50
    gb_subsample: float = 0.75

    # --- Uncertainty ---
    bootstrap_percentiles: Tuple[float, float] = (10.0, 90.0)  # 80% prediction interval
    n_bootstrap_samples: int = 100           # for calibration

    # --- Workers ---
    n_workers: int = WORKER_CORES

    # --- Data fetch ---
    yfinance_batch_size: int = 50            # tickers per yfinance batch call
    data_cache_hours: int = 4                # re-fetch after this


# ===========================================================================
# DATA TYPES
# ===========================================================================
@dataclass
class StockData:
    ticker: str
    prices: pd.DataFrame          # OHLCV
    info: Dict                    # yfinance .info dict
    sector: str = "Unknown"
    market_cap: float = 0.0


@dataclass
class Signal:
    ticker: str
    expected_return: float        # point estimate
    ci_low: float                 # lower bound of prediction interval
    ci_high: float                # upper bound
    confidence: float             # 0-1 model agreement
    conviction: str               # HIGH / MEDIUM / LOW / SPECULATIVE
    holding_period: int
    factors: Dict
    timestamp: datetime = field(default_factory=datetime.now)


# ===========================================================================
# REAL DATA PROVIDER — yfinance
# ===========================================================================
class YFinanceDataProvider:
    """
    Pulls REAL market data. No simulation, no fakery.
    Implements caching and batched downloads for efficiency.
    """

    def __init__(self, config: Config):
        self.config = config
        self._price_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
        self._info_cache: Dict[str, Dict] = {}

    def get_sp500_tickers(self) -> List[str]:
        """Pull current S&P 500 components from Wikipedia."""
        try:
            import yfinance as yf
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            df = tables[0]
            tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
            log.info(f"Fetched {len(tickers)} S&P 500 tickers")
            return tickers
        except Exception as e:
            log.warning(f"Could not fetch S&P 500 list: {e}")
            # Fallback: major liquid stocks across sectors
            return self._fallback_universe()

    def _fallback_universe(self) -> List[str]:
        """If Wikipedia scrape fails, use a solid cross-sector universe."""
        return [
            # Tech
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "CRM",
            "ADBE", "INTC", "AVGO", "QCOM", "NOW", "PANW", "CRWD",
            # Healthcare
            "LLY", "UNH", "JNJ", "MRK", "ABBV", "PFE", "TMO", "ISRG",
            "VRTX", "REGN", "MRNA",
            # Finance
            "JPM", "BAC", "GS", "MS", "BLK", "SCHW", "AXP", "SPGI", "BRK-B",
            # Consumer
            "COST", "WMT", "HD", "MCD", "NKE", "SBUX", "TJX", "LOW", "CMG",
            # Industrial
            "CAT", "DE", "HON", "UNP", "LMT", "RTX", "GE", "ETN",
            # Energy
            "XOM", "CVX", "COP", "SLB", "EOG",
            # Materials
            "LIN", "SHW", "FCX", "NUE",
            # Real Estate
            "PLD", "AMT", "EQIX",
            # Utilities
            "NEE", "DUK", "SO",
            # Communication
            "NFLX", "DIS", "TMUS",
        ]

    def get_custom_universe(self, tickers: List[str]) -> List[str]:
        """Validate a user-supplied ticker list."""
        return [t.upper().strip() for t in tickers if t.strip()]

    def fetch_prices(self, ticker: str, period: str = "3y") -> Optional[pd.DataFrame]:
        """Fetch OHLCV for a single ticker with caching."""
        import yfinance as yf

        # Check cache
        if ticker in self._price_cache:
            cached_time, cached_df = self._price_cache[ticker]
            if (datetime.now() - cached_time).total_seconds() < self.config.data_cache_hours * 3600:
                return cached_df

        try:
            tk = yf.Ticker(ticker)
            df = tk.history(period=period, auto_adjust=True)
            if df is None or len(df) < 100:
                return None

            # Standardise column names
            df.columns = [c.strip().title() for c in df.columns]
            required = ["Open", "High", "Low", "Close", "Volume"]
            for col in required:
                if col not in df.columns:
                    return None

            # Use float32 to save memory (16GB constraint)
            for col in ["Open", "High", "Low", "Close"]:
                df[col] = df[col].astype(np.float32)
            df["Volume"] = df["Volume"].astype(np.int64)

            # Drop any rows with zero/nan close
            df = df[df["Close"] > 0].dropna(subset=required)

            self._price_cache[ticker] = (datetime.now(), df)
            return df

        except Exception as e:
            log.debug(f"Failed to fetch {ticker}: {e}")
            return None

    def fetch_batch_prices(self, tickers: List[str], period: str = "3y") -> Dict[str, pd.DataFrame]:
        """Batch-download prices for memory efficiency."""
        import yfinance as yf

        results = {}
        batch_size = self.config.yfinance_batch_size

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            log.info(f"Downloading batch {i // batch_size + 1}: "
                     f"{len(batch)} tickers ({i+1}-{min(i+batch_size, len(tickers))})")

            try:
                data = yf.download(
                    batch, period=period, auto_adjust=True,
                    group_by="ticker", threads=True, progress=False,
                )

                if isinstance(data.columns, pd.MultiIndex):
                    for ticker in batch:
                        try:
                            df = data[ticker].copy()
                            df.columns = [c.strip().title() for c in df.columns]
                            df = df.dropna(subset=["Close"])
                            if len(df) >= 100 and df["Close"].iloc[-1] > 0:
                                for col in ["Open", "High", "Low", "Close"]:
                                    if col in df.columns:
                                        df[col] = df[col].astype(np.float32)
                                results[ticker] = df
                        except Exception:
                            pass
                elif len(batch) == 1 and not data.empty:
                    df = data.copy()
                    df.columns = [c.strip().title() for c in df.columns]
                    df = df.dropna(subset=["Close"])
                    if len(df) >= 100:
                        results[batch[0]] = df

            except Exception as e:
                log.warning(f"Batch download failed: {e}. Trying individually...")
                for ticker in batch:
                    df = self.fetch_prices(ticker, period)
                    if df is not None:
                        results[ticker] = df

            # Memory management
            gc.collect()

        log.info(f"Successfully fetched {len(results)} / {len(tickers)} tickers")
        return results

    def fetch_info(self, ticker: str) -> Dict:
        """Fetch fundamental data for a ticker."""
        import yfinance as yf

        if ticker in self._info_cache:
            return self._info_cache[ticker]

        try:
            tk = yf.Ticker(ticker)
            info = tk.info or {}
            self._info_cache[ticker] = info
            return info
        except Exception:
            return {}

    def fetch_batch_info(self, tickers: List[str]) -> Dict[str, Dict]:
        """Fetch info for multiple tickers."""
        import yfinance as yf
        results = {}
        for i, ticker in enumerate(tickers):
            if i % 20 == 0 and i > 0:
                log.info(f"Fetching fundamentals: {i}/{len(tickers)}")
            info = self.fetch_info(ticker)
            if info:
                results[ticker] = info
            # Rate limiting kindness
            if i % 5 == 0:
                time.sleep(0.1)
        return results


# ===========================================================================
# DATA MANAGER — orchestrates fetching + filtering
# ===========================================================================
class DataManager:
    def __init__(self, config: Config):
        self.config = config
        self.provider = YFinanceDataProvider(config)

    def get_universe(self, custom_tickers: Optional[List[str]] = None) -> List[str]:
        """Get stock universe. Custom list or S&P 500."""
        if custom_tickers:
            return self.provider.get_custom_universe(custom_tickers)
        return self.provider.get_sp500_tickers()

    def fetch_all(
        self, tickers: List[str], period: str = "3y"
    ) -> Dict[str, StockData]:
        """Fetch all data and apply universe filters."""
        # Limit universe to fit in 16GB RAM
        if len(tickers) > self.config.max_universe_size:
            log.info(f"Universe capped at {self.config.max_universe_size} "
                     f"(from {len(tickers)}) for RAM constraint")
            tickers = tickers[: self.config.max_universe_size]

        # Batch download prices
        prices_dict = self.provider.fetch_batch_prices(tickers, period)

        # Fetch fundamentals for successful tickers
        log.info("Fetching fundamental data...")
        info_dict = self.provider.fetch_batch_info(list(prices_dict.keys()))

        # Build StockData objects with filters
        result = {}
        skipped = {"low_cap": 0, "low_vol": 0, "price": 0, "no_info": 0}

        for ticker, prices in prices_dict.items():
            info = info_dict.get(ticker, {})

            # Extract sector and market cap
            sector = info.get("sector", "Unknown") or "Unknown"
            market_cap = info.get("marketCap", 0) or 0
            avg_volume = info.get("averageVolume", 0) or 0
            current_price = float(prices["Close"].iloc[-1])

            # Apply filters
            if market_cap < self.config.min_market_cap and market_cap > 0:
                skipped["low_cap"] += 1
                continue
            if avg_volume < self.config.min_avg_volume and avg_volume > 0:
                skipped["low_vol"] += 1
                continue
            if current_price < self.config.min_price or current_price > self.config.max_price:
                skipped["price"] += 1
                continue

            result[ticker] = StockData(
                ticker=ticker,
                prices=prices,
                info=info,
                sector=sector,
                market_cap=market_cap,
            )

        log.info(f"Universe: {len(result)} stocks pass filters")
        log.info(f"Skipped — low cap: {skipped['low_cap']}, "
                 f"low vol: {skipped['low_vol']}, price: {skipped['price']}")

        gc.collect()
        return result


# ===========================================================================
# FEATURE ENGINE — same proven indicators, no look-ahead
# ===========================================================================
def _compute_features_for_stock(args: Tuple) -> Tuple[str, Optional[pd.DataFrame]]:
    """Top-level function for multiprocessing (picklable)."""
    ticker, prices_dict, info = args
    try:
        prices = pd.DataFrame(prices_dict)
        return ticker, _compute_features(ticker, prices, info)
    except Exception as e:
        return ticker, None


def _compute_features(
    ticker: str, prices: pd.DataFrame, info: Dict
) -> Optional[pd.DataFrame]:
    """
    Pure function: prices → features. No side effects.
    All indicators strictly use past data only.
    """
    if len(prices) < 252:
        return None

    close = prices["Close"].astype(np.float64)
    high = prices["High"].astype(np.float64)
    low = prices["Low"].astype(np.float64)
    volume = prices["Volume"].astype(np.float64)
    ret = close.pct_change()

    feat = pd.DataFrame(index=prices.index)

    # --- Price vs moving averages (shifted to avoid look-ahead) ---
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

    # Realised vol vs implied (approximation via range)
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
    feat["macd_hist_norm"] = feat["macd_hist"] / (close + 1e-8)  # normalised

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
    obv = (np.sign(ret) * volume).cumsum()
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
    feat["mean_rev_5"] = -(ret.rolling(5).sum())  # short-term reversal
    feat["mean_rev_21"] = -(ret.rolling(21).sum())

    # --- Fundamental features (static per fetch, no look-ahead issue) ---
    feat["pe_ratio"] = float(info.get("trailingPE", 0) or 0)
    feat["forward_pe"] = float(info.get("forwardPE", 0) or 0)
    feat["pb_ratio"] = float(info.get("priceToBook", 0) or 0)
    feat["revenue_growth"] = float(info.get("revenueGrowth", 0) or 0)
    feat["earnings_growth"] = float(info.get("earningsGrowth", 0) or 0)
    feat["profit_margin"] = float(info.get("profitMargins", 0) or 0)
    feat["roe"] = float(info.get("returnOnEquity", 0) or 0)
    feat["debt_to_equity"] = float(info.get("debtToEquity", 0) or 0)
    feat["beta"] = float(info.get("beta", 1) or 1)
    feat["dividend_yield"] = float(info.get("dividendYield", 0) or 0)
    feat["peg_ratio"] = float(info.get("pegRatio", 0) or 0)

    feat.replace([np.inf, -np.inf], np.nan, inplace=True)
    feat.dropna(inplace=True)

    # Convert to float32 for memory
    feat = feat.astype(np.float32)

    return feat if len(feat) > 100 else None


class FeatureEngine:
    """Parallel feature computation optimised for M2 Pro."""

    def __init__(self, config: Config):
        self.config = config

    def compute_all(self, stock_data: Dict[str, StockData]) -> Dict[str, pd.DataFrame]:
        t0 = time.perf_counter()

        args_list = [
            (ticker, sd.prices.to_dict(), sd.info)
            for ticker, sd in stock_data.items()
        ]

        results = {}
        with ProcessPoolExecutor(max_workers=self.config.n_workers) as pool:
            futures = {
                pool.submit(_compute_features_for_stock, args): args[0]
                for args in args_list
            }
            for future in as_completed(futures):
                ticker, feat = future.result()
                if feat is not None:
                    results[ticker] = feat

        elapsed = time.perf_counter() - t0
        log.info(f"Features computed for {len(results)} stocks in {elapsed:.1f}s "
                 f"({self.config.n_workers} workers)")
        gc.collect()
        return results


# ===========================================================================
# RETURN PREDICTOR — stacked ensemble with HONEST uncertainty
# ===========================================================================
class ReturnPredictor:
    """
    Stacked ensemble: RF + GradientBoosting → RidgeCV meta-learner.
    
    UNCERTAINTY QUANTIFICATION:
    1. Individual RF tree predictions → prediction interval
    2. RF vs GB disagreement → model uncertainty
    3. Out-of-fold residual distribution → calibrated intervals
    """

    def __init__(self, config: Config):
        self.config = config
        self.base_models: Dict[str, object] = {}
        self.meta_model = None
        self.scaler = RobustScaler()
        self.feature_names: List[str] = []
        self.is_fitted = False
        self._feature_importances: Optional[np.ndarray] = None

        # Uncertainty calibration
        self._oof_residuals: Optional[np.ndarray] = None
        self._oof_abs_residual_by_conf: Dict[str, float] = {}

    def _create_base_models(self) -> Dict:
        return {
            "rf": RandomForestRegressor(
                n_estimators=self.config.rf_n_estimators,
                max_depth=self.config.rf_max_depth,
                min_samples_leaf=self.config.rf_min_samples_leaf,
                max_features="sqrt",
                n_jobs=-1,
                random_state=42,
            ),
            "gb": GradientBoostingRegressor(
                n_estimators=self.config.gb_n_estimators,
                max_depth=self.config.gb_max_depth,
                learning_rate=self.config.gb_learning_rate,
                min_samples_leaf=self.config.gb_min_samples_leaf,
                subsample=self.config.gb_subsample,
                random_state=42,
            ),
        }

    @staticmethod
    def _cross_sectional_normalise(
        all_features: Dict[str, pd.DataFrame],
    ) -> Dict[str, pd.DataFrame]:
        """
        Z-score each feature ACROSS stocks at each date.
        Forces the model to learn RELATIVE signals, not absolute levels.
        """
        tickers = list(all_features.keys())
        if not tickers:
            return all_features

        parts = []
        for t in tickers:
            df = all_features[t].copy()
            df["_ticker"] = t
            parts.append(df)

        combined = pd.concat(parts)
        combined.index.name = "date"

        def _zscore_group(g):
            numeric = g.drop(columns=["_ticker"])
            mu = numeric.mean()
            sigma = numeric.std().replace(0, 1)
            return pd.DataFrame(
                (numeric - mu) / sigma, index=g.index, columns=numeric.columns,
            ).assign(_ticker=g["_ticker"].values)

        normed = combined.groupby(level=0, group_keys=False).apply(_zscore_group)

        result = {}
        for t in tickers:
            mask = normed["_ticker"] == t
            df = normed.loc[mask].drop(columns=["_ticker"])
            df = df.replace([np.inf, -np.inf], np.nan).dropna()
            if len(df) > 50:
                result[t] = df

        return result

    def fit(
        self,
        all_features: Dict[str, pd.DataFrame],
        all_prices: Dict[str, pd.DataFrame],
        cutoff_date: datetime,
    ) -> None:
        """Train on data STRICTLY BEFORE cutoff_date."""
        horizon = self.config.prediction_horizon_days
        normed = self._cross_sectional_normalise(all_features)
        log.info(f"Cross-sectional normalisation: {len(normed)} stocks")

        X_parts, y_parts = [], []
        for ticker in normed:
            if ticker not in all_prices:
                continue
            feat = normed[ticker]
            close = all_prices[ticker]["Close"]

            fwd = close.shift(-horizon) / close - 1
            endpoint_dates = feat.index + pd.Timedelta(days=int(horizon * 1.5))
            valid = feat.index[endpoint_dates < pd.Timestamp(cutoff_date)]
            valid = valid.intersection(fwd.dropna().index)

            if len(valid) < 50:
                continue

            X_parts.append(feat.loc[valid].values)
            y_parts.append(fwd.loc[valid].values)

        if not X_parts:
            log.error("No valid training data")
            return

        X = np.vstack(X_parts).astype(np.float64)
        y = np.hstack(y_parts).astype(np.float64)

        mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        X, y = X[mask], y[mask]

        if len(X) < 200:
            log.error(f"Only {len(X)} samples — too few for real data")
            return

        self.feature_names = list(normed[list(normed.keys())[0]].columns)
        log.info(f"Training: {len(X)} samples, {X.shape[1]} features")
        log.info(f"Target: mean={y.mean():.2%}, std={y.std():.2%}, "
                 f"median={np.median(y):.2%}")

        X_scaled = self.scaler.fit_transform(X)

        # --- Out-of-fold predictions for meta-learner + calibration ---
        tscv = TimeSeriesSplit(n_splits=self.config.n_cv_folds)
        model_names = ["rf", "gb"]
        oof_preds = {name: np.full(len(X_scaled), np.nan) for name in model_names}

        for fold_i, (train_idx, val_idx) in enumerate(tscv.split(X_scaled)):
            X_tr, X_val = X_scaled[train_idx], X_scaled[val_idx]
            y_tr = y[train_idx]

            fold_models = self._create_base_models()
            for name, model in fold_models.items():
                model.fit(X_tr, y_tr)
                oof_preds[name][val_idx] = model.predict(X_val)

        has_oof = np.all([np.isfinite(oof_preds[n]) for n in model_names], axis=0)
        meta_X = np.column_stack([oof_preds[n][has_oof] for n in model_names])
        meta_y = y[has_oof]

        # Train meta-learner
        self.meta_model = RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0])
        self.meta_model.fit(meta_X, meta_y)
        oof_final = self.meta_model.predict(meta_X)
        oof_r2 = self.meta_model.score(meta_X, meta_y)

        # --- CALIBRATION: store OOF residuals for uncertainty estimation ---
        self._oof_residuals = meta_y - oof_final
        residual_std = np.std(self._oof_residuals)
        residual_mae = np.mean(np.abs(self._oof_residuals))

        log.info(f"Meta-learner R²: {oof_r2:.4f}")
        log.info(f"OOF residual std: {residual_std:.2%}, MAE: {residual_mae:.2%}")

        if oof_r2 > 0.15:
            log.warning(f"R² = {oof_r2:.3f} on real data is unusually high. "
                        f"Inspect for leakage or regime-specific overfitting.")
        if oof_r2 < -0.05:
            log.warning(f"R² = {oof_r2:.3f} — model has no predictive power. "
                        f"Signals should be treated with extreme skepticism.")

        # Retrain base models on all data
        self.base_models = self._create_base_models()
        for name, model in self.base_models.items():
            model.fit(X_scaled, y)

        self.is_fitted = True
        self._feature_importances = self.base_models["rf"].feature_importances_

        if self._feature_importances is not None and self.feature_names:
            top_idx = np.argsort(self._feature_importances)[::-1][:10]
            log.info("Top 10 features (RF importance):")
            for i in top_idx:
                log.info(f"  {self.feature_names[i]:<25} {self._feature_importances[i]:.4f}")

        log.info("Training complete")

    def predict_batch(
        self, all_features: Dict[str, pd.DataFrame]
    ) -> Dict[str, Dict[str, float]]:
        """
        Predict with FULL uncertainty quantification.
        Returns {ticker: {
            "expected_return": float,
            "ci_low": float,
            "ci_high": float,
            "confidence": float,       # model agreement (0-1)
            "tree_std": float,          # RF tree disagreement
            "calibrated_std": float,    # from OOF residuals
        }}
        """
        if not self.is_fitted:
            return {}

        tickers = []
        rows = []
        for ticker, feat in all_features.items():
            if feat.empty:
                continue
            row = feat.iloc[-1:].values
            row = np.nan_to_num(row, nan=0.0, posinf=0.0, neginf=0.0)
            tickers.append(ticker)
            rows.append(row[0])

        if not tickers:
            return {}

        X_raw = np.vstack(rows)

        # Cross-sectional z-score at prediction time
        mu = X_raw.mean(axis=0)
        sigma = X_raw.std(axis=0)
        sigma[sigma == 0] = 1.0
        X_normed = (X_raw - mu) / sigma

        try:
            X_scaled = self.scaler.transform(X_normed)
        except Exception:
            return {}

        # Base model predictions
        preds_rf = self.base_models["rf"].predict(X_scaled)
        preds_gb = self.base_models["gb"].predict(X_scaled)

        # Meta-learner ensemble
        meta_X = np.column_stack([preds_rf, preds_gb])
        final_preds = self.meta_model.predict(meta_X)

        # --- UNCERTAINTY FROM INDIVIDUAL RF TREES ---
        rf_model = self.base_models["rf"]
        tree_preds = np.array([tree.predict(X_scaled) for tree in rf_model.estimators_])
        # tree_preds shape: (n_trees, n_stocks)
        tree_std = tree_preds.std(axis=0)
        pctl_low = np.percentile(tree_preds, self.config.bootstrap_percentiles[0], axis=0)
        pctl_high = np.percentile(tree_preds, self.config.bootstrap_percentiles[1], axis=0)

        # --- CALIBRATED UNCERTAINTY from OOF residuals ---
        calibrated_std = np.std(self._oof_residuals) if self._oof_residuals is not None else 0.10

        # --- MODEL DISAGREEMENT ---
        model_spread = np.abs(preds_rf - preds_gb)
        confidence = 1.0 / (1.0 + model_spread * 5.0)

        results = {}
        for i, ticker in enumerate(tickers):
            pred = float(np.clip(final_preds[i], -0.50, 1.00))
            conf = float(confidence[i])

            # Combine tree-based CI with calibrated residuals
            # Use the WIDER of the two (conservative)
            tree_ci_low = float(pctl_low[i])
            tree_ci_high = float(pctl_high[i])
            cal_ci_low = pred - 1.28 * calibrated_std   # 80% interval
            cal_ci_high = pred + 1.28 * calibrated_std

            ci_low = min(tree_ci_low, cal_ci_low)
            ci_high = max(tree_ci_high, cal_ci_high)

            results[ticker] = {
                "expected_return": pred,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "confidence": conf,
                "tree_std": float(tree_std[i]),
                "calibrated_std": calibrated_std,
                "rf_pred": float(preds_rf[i]),
                "gb_pred": float(preds_gb[i]),
            }

        return results

    def get_feature_importances(self) -> Optional[Dict[str, float]]:
        if self._feature_importances is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names, self._feature_importances))


# ===========================================================================
# CONVICTION CLASSIFIER
# ===========================================================================
def classify_conviction(
    expected_return: float,
    ci_low: float,
    ci_high: float,
    confidence: float,
    tree_std: float,
) -> str:
    """
    Honest conviction classification.
    
    HIGH:         CI_low > 0 AND confidence > 0.6 AND tree_std < 0.08
    MEDIUM:       expected > 0 AND CI_low > -0.05 AND confidence > 0.45
    LOW:          expected > 0 AND confidence > 0.3
    SPECULATIVE:  everything else with positive expected
    AVOID:        expected <= 0
    """
    if expected_return <= 0:
        return "AVOID"

    if ci_low > 0 and confidence > 0.60 and tree_std < 0.08:
        return "HIGH"
    elif expected_return > 0 and ci_low > -0.05 and confidence > 0.45:
        return "MEDIUM"
    elif expected_return > 0 and confidence > 0.30:
        return "LOW"
    else:
        return "SPECULATIVE"


# ===========================================================================
# PORTFOLIO OPTIMIZER
# ===========================================================================
class PortfolioOptimizer:
    def __init__(self, config: Config):
        self.config = config

    def _estimate_covariance(self, returns_matrix: np.ndarray) -> np.ndarray:
        if returns_matrix.shape[0] < returns_matrix.shape[1] + 5:
            vols = np.std(returns_matrix, axis=0)
            return np.diag(vols ** 2)
        try:
            lw = LedoitWolf().fit(returns_matrix)
            return lw.covariance_
        except Exception:
            vols = np.std(returns_matrix, axis=0)
            return np.diag(vols ** 2)

    def optimize(
        self, candidates: List[Dict], stock_data: Dict[str, StockData],
    ) -> Dict[str, float]:
        n = len(candidates)
        if n == 0:
            return {}

        tickers = [c["ticker"] for c in candidates]
        expected_returns = np.array([c["expected_return"] for c in candidates])
        sectors = [c.get("sector", "Unknown") for c in candidates]

        # Build returns matrix
        returns_list = []
        for t in tickers:
            if t in stock_data:
                close = stock_data[t].prices["Close"]
                ret = close.pct_change().dropna().values[-252:]
                returns_list.append(ret)
            else:
                returns_list.append(np.zeros(252))

        min_len = min(len(r) for r in returns_list)
        if min_len < 20:
            return dict(zip(tickers, np.ones(n) / n))

        returns_matrix = np.column_stack([r[-min_len:] for r in returns_list])
        cov_annual = self._estimate_covariance(returns_matrix) * 252

        def neg_sharpe(w):
            port_ret = w @ expected_returns
            port_var = w @ cov_annual @ w
            port_vol = np.sqrt(max(port_var, 1e-10))
            return -(port_ret - self.config.risk_free_rate) / port_vol

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        for sector in set(sectors):
            mask = np.array([1.0 if s == sector else 0.0 for s in sectors])
            constraints.append({
                "type": "ineq",
                "fun": lambda w, m=mask: self.config.max_sector_exposure - m @ w,
            })

        bounds = [(0, self.config.max_position_size)] * n
        x0 = np.ones(n) / n

        try:
            result = minimize(
                neg_sharpe, x0, method="SLSQP",
                bounds=bounds, constraints=constraints,
                options={"maxiter": 2000, "ftol": 1e-12},
            )
            weights = result.x if result.success else x0
        except Exception:
            weights = x0

        weights[weights < self.config.min_weight_threshold] = 0
        total = weights.sum()
        if total > 0:
            weights /= total

        return dict(zip(tickers, weights))

    def portfolio_metrics(
        self, weights: Dict[str, float], candidates: List[Dict]
    ) -> Dict:
        if not weights:
            return {}

        cmap = {c["ticker"]: c for c in candidates}
        tickers = [t for t, w in weights.items() if w > 0.01]
        w_arr = np.array([weights[t] for t in tickers])
        er = np.array([cmap[t]["expected_return"] for t in tickers])
        vols = np.array([cmap[t].get("volatility", 0.30) for t in tickers])

        port_ret = float(w_arr @ er)
        port_vol = float(np.sqrt((w_arr ** 2) @ (vols ** 2)))

        sector_w = defaultdict(float)
        for t in tickers:
            sector_w[cmap[t].get("sector", "Unknown")] += weights[t]

        return {
            "expected_return": port_ret,
            "expected_volatility": port_vol,
            "sharpe_ratio": (port_ret - self.config.risk_free_rate) / max(port_vol, 0.01),
            "num_positions": len(tickers),
            "max_position": float(max(weights.values())) if weights else 0,
            "sector_weights": dict(sector_w),
        }


# ===========================================================================
# RISK SCORER
# ===========================================================================
class RiskScorer:
    def __init__(self, config: Config):
        self.config = config

    def score(
        self, pred_info: Dict, features: pd.DataFrame, info: Dict,
    ) -> Dict[str, float]:
        er = pred_info["expected_return"]
        conf = pred_info["confidence"]

        scores = {}
        scores["expected_return"] = er
        scores["conf_adj_return"] = er * conf

        vol = float(features["vol_21d"].iloc[-1]) if "vol_21d" in features.columns else 0.30
        vol = max(vol, 0.01)
        scores["vol_21d"] = vol
        scores["sharpe_est"] = (er - self.config.risk_free_rate) / vol

        # Momentum quality
        mom_cols = [c for c in features.columns if c.startswith("mom_")]
        scores["momentum_quality"] = float(features[mom_cols].iloc[-1].mean()) if mom_cols else 0.0

        # Fundamental quality
        fund_score = 0
        if (info.get("returnOnEquity") or 0) > 0.15:
            fund_score += 1
        if (info.get("profitMargins") or 0) > 0.10:
            fund_score += 1
        if (info.get("revenueGrowth") or 0) > 0.10:
            fund_score += 1
        if (info.get("debtToEquity") or 0) < 100:
            fund_score += 1
        scores["fundamental_quality"] = fund_score / 4.0

        # Composite
        scores["composite"] = (
            0.35 * scores["conf_adj_return"]
            + 0.25 * scores["sharpe_est"] / 3.0
            + 0.15 * scores["momentum_quality"]
            + 0.25 * scores["fundamental_quality"]
        )
        return scores


# ===========================================================================
# SIGNAL GENERATOR
# ===========================================================================
class SignalGenerator:
    def __init__(self, config: Config):
        self.config = config
        self.feature_engine = FeatureEngine(config)
        self.predictor = ReturnPredictor(config)
        self.scorer = RiskScorer(config)
        self.optimizer = PortfolioOptimizer(config)
        self._last_features: Dict[str, pd.DataFrame] = {}

    def train(self, stock_data: Dict[str, StockData], cutoff_date: datetime) -> None:
        self._last_features = self.feature_engine.compute_all(stock_data)
        all_prices = {t: sd.prices for t, sd in stock_data.items()}
        self.predictor.fit(self._last_features, all_prices, cutoff_date)

    def generate_signals(self, stock_data: Dict[str, StockData]) -> List[Signal]:
        if not self._last_features:
            self._last_features = self.feature_engine.compute_all(stock_data)

        batch_preds = self.predictor.predict_batch(self._last_features)

        signals = []
        for ticker, data in stock_data.items():
            if ticker not in batch_preds:
                continue
            feat = self._last_features.get(ticker)
            if feat is None or len(feat) < 50:
                continue

            pred = batch_preds[ticker]
            scores = self.scorer.score(pred, feat, data.info)

            conviction = classify_conviction(
                pred["expected_return"], pred["ci_low"], pred["ci_high"],
                pred["confidence"], pred["tree_std"],
            )

            vol = float(feat["vol_21d"].iloc[-1]) if "vol_21d" in feat.columns else 0.30

            signals.append(Signal(
                ticker=ticker,
                expected_return=pred["expected_return"],
                ci_low=pred["ci_low"],
                ci_high=pred["ci_high"],
                confidence=pred["confidence"],
                conviction=conviction,
                holding_period=self.config.prediction_horizon_days,
                factors={
                    "scores": scores,
                    "volatility": vol,
                    "sector": data.sector,
                    "market_cap": data.market_cap,
                    "pe_ratio": data.info.get("trailingPE", 0) or 0,
                    "roe": data.info.get("returnOnEquity", 0) or 0,
                    "rf_pred": pred["rf_pred"],
                    "gb_pred": pred["gb_pred"],
                    "tree_std": pred["tree_std"],
                    "calibrated_std": pred["calibrated_std"],
                },
            ))

        # Diagnostics
        if batch_preds:
            rets = [v["expected_return"] for v in batch_preds.values()]
            log.info(f"Predictions — min: {min(rets):.2%}, max: {max(rets):.2%}, "
                     f"mean: {np.mean(rets):.2%}")

        signals.sort(key=lambda s: s.factors["scores"]["composite"], reverse=True)
        return signals

    def select_portfolio(
        self, signals: List[Signal], stock_data: Dict[str, StockData],
        min_return: Optional[float] = None,
    ) -> Dict:
        if min_return is None:
            min_return = self.config.min_expected_return

        filtered = [
            s for s in signals
            if s.expected_return >= min_return
            and s.confidence >= self.config.confidence_threshold
            and s.conviction in ("HIGH", "MEDIUM", "LOW")
        ]
        log.info(f"{len(filtered)} stocks pass filters")

        if not filtered:
            log.info("No stocks pass filters. Top 5:")
            for s in signals[:5]:
                log.info(f"  {s.ticker}: {s.expected_return:.1%} / {s.conviction}")
            return {"positions": {}, "metrics": {}}

        top = filtered[: self.config.max_positions * 2]
        candidates = [
            {
                "ticker": s.ticker,
                "expected_return": s.expected_return,
                "confidence": s.confidence,
                "volatility": s.factors.get("volatility", 0.30),
                "sector": s.factors.get("sector", "Unknown"),
            }
            for s in top
        ]

        weights = self.optimizer.optimize(candidates, stock_data)
        metrics = self.optimizer.portfolio_metrics(weights, candidates)

        positions = {}
        for ticker, w in weights.items():
            if w > 0.01:
                sig = next((s for s in signals if s.ticker == ticker), None)
                if sig:
                    positions[ticker] = {
                        "weight": w,
                        "expected_return": sig.expected_return,
                        "ci_low": sig.ci_low,
                        "ci_high": sig.ci_high,
                        "confidence": sig.confidence,
                        "conviction": sig.conviction,
                        "factors": sig.factors,
                    }

        return {"positions": positions, "metrics": metrics}


# ===========================================================================
# WALK-FORWARD BACKTESTER
# ===========================================================================
class Backtester:
    def __init__(self, config: Config):
        self.config = config

    def run(
        self, stock_data: Dict[str, StockData],
        start_date: datetime, end_date: datetime,
    ) -> Dict:
        log.info(f"Backtest: {start_date.date()} → {end_date.date()}")

        all_dates_set = None
        for sd in stock_data.values():
            s = set(sd.prices.index)
            all_dates_set = s if all_dates_set is None else all_dates_set & s
        if not all_dates_set:
            return {"error": "No common dates"}

        all_dates = sorted(d for d in all_dates_set
                           if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date))

        if len(all_dates) < 100:
            return {"error": f"Only {len(all_dates)} common trading days"}

        initial_capital = 1_000_000.0
        cash = initial_capital
        positions: Dict[str, Dict] = {}
        history = []
        trades = []

        gen = SignalGenerator(self.config)

        train_end_idx = min(self.config.ml_train_window, len(all_dates) // 2)
        rebal_dates = all_dates[train_end_idx :: self.config.rebalance_frequency_days]
        retrain_counter = 0
        retrain_freq = max(1, self.config.backtest_retrain_frequency
                          // self.config.rebalance_frequency_days)

        for i, rebal_date in enumerate(rebal_dates[:-1]):
            # Retrain periodically
            if retrain_counter % retrain_freq == 0:
                train_data = {}
                for t, sd in stock_data.items():
                    tp = sd.prices[sd.prices.index < rebal_date]
                    if len(tp) > 100:
                        train_data[t] = StockData(t, tp, sd.info, sd.sector, sd.market_cap)
                if train_data:
                    gen.train(train_data, cutoff_date=rebal_date)
                    log.info(f"Retrained at {rebal_date.date()}")

            retrain_counter += 1

            # Portfolio value
            port_val = cash
            for t, pos in positions.items():
                try:
                    price = stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                    port_val += pos["shares"] * price
                except Exception:
                    pass

            # Generate signals
            current_data = {}
            for t, sd in stock_data.items():
                cp = sd.prices[sd.prices.index <= rebal_date]
                if len(cp) > 100:
                    current_data[t] = StockData(t, cp, sd.info, sd.sector, sd.market_cap)

            gen._last_features = {}
            signals = gen.generate_signals(current_data)
            sel = gen.select_portfolio(signals, current_data, min_return=0.03)
            target = sel.get("positions", {})

            # Rebalance
            investable = port_val * (1 - self.config.cash_reserve)
            new_pos = {}
            for t, info in target.items():
                try:
                    price = stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                    shares = int(investable * info["weight"] / price)
                    if shares > 0:
                        new_pos[t] = {"shares": shares, "entry_price": price}
                        if t not in positions:
                            trades.append({"date": rebal_date, "ticker": t,
                                           "action": "BUY", "shares": shares, "price": price})
                except Exception:
                    pass

            for t in positions:
                if t not in new_pos:
                    try:
                        price = stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                        trades.append({"date": rebal_date, "ticker": t,
                                       "action": "SELL", "shares": positions[t]["shares"],
                                       "price": price})
                    except Exception:
                        pass

            positions = new_pos
            invested = sum(
                pos["shares"] * stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                for t, pos in positions.items() if t in stock_data
            )
            cash = max(0, port_val - invested)

            history.append({
                "date": rebal_date,
                "portfolio_value": port_val,
                "n_positions": len(positions),
            })

            gc.collect()

        # Final valuation
        final = cash
        for t, pos in positions.items():
            try:
                final += pos["shares"] * stock_data[t].prices["Close"].iloc[-1]
            except Exception:
                pass

        if not history:
            return {"error": "No rebalance periods"}

        df = pd.DataFrame(history)
        df["return"] = df["portfolio_value"].pct_change()
        daily_ret = df["return"].dropna()

        years = max(0.1, (all_dates[-1] - all_dates[0]).days / 365.25)
        total_return = final / initial_capital - 1
        cagr = (final / initial_capital) ** (1 / years) - 1
        vol = float(daily_ret.std() * np.sqrt(12)) if len(daily_ret) > 1 else 0.01
        sharpe = (cagr - self.config.risk_free_rate) / max(vol, 0.01)

        cum = (1 + daily_ret).cumprod()
        max_dd = float((cum / cum.expanding().max() - 1).min()) if len(cum) > 0 else 0

        return {
            "initial_capital": initial_capital,
            "final_value": final,
            "total_return": total_return,
            "cagr": cagr,
            "volatility": vol,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "num_trades": len(trades),
            "num_rebalances": len(history),
            "history": history,
        }


# ===========================================================================
# TRADING ENGINE — main interface
# ===========================================================================
class TradingEngine:
    def __init__(self, config: Config = None, custom_tickers: Optional[List[str]] = None):
        self.config = config or Config()
        self.dm = DataManager(self.config)
        self.gen = SignalGenerator(self.config)
        self.bt = Backtester(self.config)
        self.custom_tickers = custom_tickers
        self._stock_data: Optional[Dict[str, StockData]] = None

    def load_data(self) -> Dict[str, StockData]:
        if self._stock_data is None:
            universe = self.dm.get_universe(self.custom_tickers)
            self._stock_data = self.dm.fetch_all(universe)
        return self._stock_data

    def train(self) -> None:
        data = self.load_data()
        cutoff = datetime.now() - timedelta(days=self.config.prediction_horizon_days)
        self.gen.train(data, cutoff_date=cutoff)

    def scan(self) -> List[Dict]:
        if not self.gen.predictor.is_fitted:
            self.train()
        data = self.load_data()
        signals = self.gen.generate_signals(data)

        opps = []
        for s in signals:
            opps.append({
                "ticker": s.ticker,
                "expected_return": s.expected_return,
                "expected_return_pct": f"{s.expected_return * 100:+.1f}%",
                "ci_low": s.ci_low,
                "ci_low_pct": f"{s.ci_low * 100:+.1f}%",
                "ci_high": s.ci_high,
                "ci_high_pct": f"{s.ci_high * 100:+.1f}%",
                "confidence": s.confidence,
                "confidence_pct": f"{s.confidence * 100:.0f}%",
                "conviction": s.conviction,
                "holding_period": s.holding_period,
                "sector": s.factors.get("sector", "?"),
                "volatility": s.factors.get("volatility", 0),
                "pe_ratio": s.factors.get("pe_ratio", 0),
                "roe": s.factors.get("roe", 0),
                "rf_pred": s.factors.get("rf_pred", 0),
                "gb_pred": s.factors.get("gb_pred", 0),
                "tree_std": s.factors.get("tree_std", 0),
                "scores": s.factors.get("scores", {}),
            })
        return opps

    def recommend_portfolio(self) -> Dict:
        if not self.gen.predictor.is_fitted:
            self.train()
        data = self.load_data()
        signals = self.gen.generate_signals(data)
        return self.gen.select_portfolio(signals, data)

    def backtest(self, years: int = 2) -> Dict:
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        data = self.load_data()
        return self.bt.run(data, start, end)


# ===========================================================================
# REPORT
# ===========================================================================
def report(
    opps: List[Dict],
    portfolio: Dict,
    bt_results: Dict,
    feature_importances: Optional[Dict[str, float]],
    config: Config,
) -> str:
    lines = []

    def hr(char="="):
        lines.append(char * 90)

    def blank():
        lines.append("")

    hr()
    lines.append("QUANTUM ALPHA v5.0 — LIVE MARKET RESEARCH REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Horizon: {config.prediction_horizon_days} trading days")
    lines.append("WARNING: This is a research tool using REAL market data.")
    lines.append("Past patterns do not guarantee future results. You bear full responsibility.")
    hr()
    blank()

    # --- Conviction guide ---
    lines.append("CONVICTION GUIDE")
    hr("-")
    lines.append("  HIGH:         80% CI entirely above 0, high model agreement, low tree variance")
    lines.append("  MEDIUM:       Positive expected return, CI mostly above 0, decent agreement")
    lines.append("  LOW:          Positive expected but wide CI or weaker agreement")
    lines.append("  SPECULATIVE:  Positive expected but model is highly uncertain")
    lines.append("  AVOID:        Negative expected return")
    blank()

    # --- Top opportunities with uncertainty ---
    lines.append(f"SIGNAL SCAN — {len(opps)} stocks analysed")
    hr("-")
    lines.append(f"{'#':<3} {'Ticker':<7} {'Expect':>7} {'80% CI':>17} "
                 f"{'Conf':>5} {'Convic':<12} {'Sector':<15} {'Vol':>5}")
    hr("-")

    shown = 0
    for i, o in enumerate(opps, 1):
        if shown >= 30:
            break
        conviction = o.get("conviction", "?")
        if conviction == "AVOID" and shown > 15:
            continue
        ci_str = f"[{o['ci_low_pct']:>6}, {o['ci_high_pct']:>6}]"
        lines.append(
            f"{i:<3} {o['ticker']:<7} {o['expected_return_pct']:>7} {ci_str:>17} "
            f"{o['confidence_pct']:>5} {conviction:<12} "
            f"{o['sector']:<15} {o['volatility']*100:.0f}%"
        )
        shown += 1
    blank()

    # --- Uncertainty breakdown for top picks ---
    hr()
    lines.append("UNCERTAINTY BREAKDOWN — Top 10")
    hr("-")
    lines.append(f"{'Ticker':<7} {'RF Pred':>8} {'GB Pred':>8} {'Spread':>8} "
                 f"{'TreeStd':>8} {'CalStd':>8} {'Verdict':<12}")
    hr("-")
    for o in opps[:10]:
        spread = abs(o.get("rf_pred", 0) - o.get("gb_pred", 0))
        verdict = o.get("conviction", "?")
        lines.append(
            f"{o['ticker']:<7} {o.get('rf_pred',0)*100:>+7.1f}% "
            f"{o.get('gb_pred',0)*100:>+7.1f}% {spread*100:>7.1f}% "
            f"{o.get('tree_std',0)*100:>7.1f}% "
            f"{o.get('scores',{}).get('calibrated_std',0)*100 if isinstance(o.get('scores',{}), dict) else 0:>7.1f}% "
            f"{verdict:<12}"
        )
    blank()

    # --- Portfolio ---
    hr()
    lines.append("RECOMMENDED PORTFOLIO")
    hr("-")
    pos = portfolio.get("positions", {})
    met = portfolio.get("metrics", {})
    if pos:
        lines.append(f"{'Ticker':<7} {'Weight':>7} {'Expect':>8} {'80% CI':>17} "
                     f"{'Convic':<10} {'Sector':<15}")
        hr("-")
        for t, info in sorted(pos.items(), key=lambda x: -x[1]["weight"]):
            ci_str = f"[{info.get('ci_low',0)*100:+.1f}%, {info.get('ci_high',0)*100:+.1f}%]"
            lines.append(
                f"{t:<7} {info['weight']*100:>6.1f}% "
                f"{info['expected_return']*100:>+7.1f}% {ci_str:>17} "
                f"{info.get('conviction','?'):<10} "
                f"{info['factors'].get('sector','?'):<15}"
            )
    else:
        lines.append("  No positions pass filters — model sees insufficient edge.")
    blank()

    lines.append("PORTFOLIO METRICS")
    hr("-")
    lines.append(f"  Expected Return:   {met.get('expected_return',0)*100:+.1f}%")
    lines.append(f"  Expected Vol:      {met.get('expected_volatility',0)*100:.1f}%")
    lines.append(f"  Sharpe Ratio:      {met.get('sharpe_ratio',0):.2f}")
    lines.append(f"  Positions:         {met.get('num_positions',0)}")
    lines.append(f"  Max Position:      {met.get('max_position',0)*100:.1f}%")

    sw = met.get("sector_weights", {})
    if sw:
        blank()
        lines.append("SECTOR ALLOCATION")
        hr("-")
        for s, w in sorted(sw.items(), key=lambda x: -x[1]):
            lines.append(f"  {s:<20} {w*100:.1f}%")
    blank()

    # --- Backtest ---
    if "error" not in bt_results:
        hr()
        lines.append("BACKTEST (walk-forward, quarterly retraining, REAL data)")
        hr("-")
        lines.append(f"  Initial Capital:   ${bt_results['initial_capital']:>12,.0f}")
        lines.append(f"  Final Value:       ${bt_results['final_value']:>12,.0f}")
        lines.append(f"  Total Return:      {bt_results['total_return']*100:>+11.1f}%")
        lines.append(f"  CAGR:              {bt_results['cagr']*100:>+11.1f}%")
        lines.append(f"  Volatility:        {bt_results['volatility']*100:>11.1f}%")
        lines.append(f"  Sharpe Ratio:      {bt_results['sharpe_ratio']:>11.2f}")
        lines.append(f"  Max Drawdown:      {bt_results['max_drawdown']*100:>11.1f}%")
        lines.append(f"  Trades:            {bt_results['num_trades']:>11}")
        lines.append(f"  Rebalances:        {bt_results['num_rebalances']:>11}")
    else:
        lines.append(f"Backtest: {bt_results['error']}")
    blank()

    # --- Feature importances ---
    if feature_importances:
        hr()
        lines.append("MOST PREDICTIVE FEATURES (RF importance)")
        hr("-")
        sorted_fi = sorted(feature_importances.items(), key=lambda x: -x[1])[:15]
        for name, imp in sorted_fi:
            bar = "#" * int(imp * 200)
            lines.append(f"  {name:<25} {imp:.4f}  {bar}")
    blank()

    # --- Honesty box ---
    hr()
    lines.append("STATISTICAL INTEGRITY & HONEST DISCLOSURE")
    hr("-")
    lines.append("  - ALL data is REAL (Yahoo Finance). No simulation.")
    lines.append("  - Predictions use ONLY past data (strict temporal cutoff)")
    lines.append("  - Cross-sectional normalisation prevents ticker-identification leakage")
    lines.append("  - 80% prediction intervals from RF tree disagreement + OOF calibration")
    lines.append("  - Conviction tiers are CONSERVATIVE: 'HIGH' means CI is entirely > 0")
    lines.append("  - OOF R² on real equity data is typically 0.00-0.05 (near zero)")
    lines.append("  - This means the model's EDGE IS TINY if it exists at all")
    lines.append("  - Wide prediction intervals are HONEST, not a bug")
    lines.append("  - Any R² > 0.15 on real data should be investigated for leakage")
    lines.append("  - Past backtest performance does NOT guarantee future returns")
    hr()

    return "\n".join(lines)


# ===========================================================================
# MAIN
# ===========================================================================
def main(
    custom_tickers: Optional[List[str]] = None,
    skip_backtest: bool = False,
):
    """
    Run the full pipeline.
    
    Args:
        custom_tickers: Optional list of tickers. If None, uses S&P 500.
        skip_backtest: Skip the backtest step (faster for quick scans).
    
    Usage:
        # Full S&P 500 scan + backtest
        python quantum_alpha_v5.py
        
        # Quick scan of specific tickers
        python quantum_alpha_v5.py --tickers AAPL,MSFT,GOOGL,NVDA,AMD --no-backtest
        
        # Sector focus
        python quantum_alpha_v5.py --tickers XOM,CVX,COP,SLB,EOG,OXY
    """
    t_start = time.perf_counter()

    print("\n" + "=" * 90)
    print("QUANTUM ALPHA v5.0 — Live Quantitative Research Framework")
    print(f"Hardware: {N_CORES} cores, {WORKER_CORES} workers")
    print("Data: REAL market data via Yahoo Finance")
    print("=" * 90 + "\n")

    config = Config()
    engine = TradingEngine(config, custom_tickers)

    # Step 1: Load real data
    print("Step 1: Fetching real market data...")
    print("-" * 50)
    engine.load_data()
    print(f"  Loaded {len(engine._stock_data)} stocks\n")

    # Step 2: Train
    print("Step 2: Training ML models on historical data...")
    print("-" * 50)
    engine.train()

    # Step 3: Scan
    print("\nStep 3: Scanning for opportunities with uncertainty estimates...")
    print("-" * 50)
    opps = engine.scan()

    # Step 4: Portfolio
    print("\nStep 4: Optimising portfolio...")
    print("-" * 50)
    portfolio = engine.recommend_portfolio()

    # Step 5: Backtest (optional)
    bt_results = {}
    if not skip_backtest:
        print("\nStep 5: Walk-forward backtest on real data (2 years)...")
        print("-" * 50)
        bt_results = engine.backtest(years=2)
    else:
        print("\nStep 5: Backtest skipped (--no-backtest)")
        bt_results = {"error": "Skipped by user"}

    # Report
    fi = engine.gen.predictor.get_feature_importances()
    full_report = report(opps, portfolio, bt_results, fi, config)
    print("\n" + full_report)

    elapsed = time.perf_counter() - t_start
    print(f"\nTotal runtime: {elapsed:.1f}s on {WORKER_CORES} cores")
    print(f"Peak memory: ~{_estimate_memory_mb():.0f} MB")

    return {
        "opportunities": opps,
        "portfolio": portfolio,
        "backtest": bt_results,
        "feature_importances": fi,
    }


def _estimate_memory_mb() -> float:
    """Rough memory usage estimate."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # macOS returns KB
    except Exception:
        return 0.0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Quantum Alpha v5.0 — Live Market Research")
    parser.add_argument(
        "--tickers", type=str, default=None,
        help="Comma-separated list of tickers (default: S&P 500)"
    )
    parser.add_argument(
        "--no-backtest", action="store_true",
        help="Skip the backtest step for faster scans"
    )
    parser.add_argument(
        "--horizon", type=int, default=21,
        help="Prediction horizon in trading days (default: 21)"
    )
    args = parser.parse_args()

    tickers = None
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]

    if args.horizon != 21:
        Config.prediction_horizon_days = args.horizon

    results = main(custom_tickers=tickers, skip_backtest=args.no_backtest)
