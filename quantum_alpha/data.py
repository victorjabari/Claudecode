"""Data layer: yfinance with a parquet cache and retry/backoff.

Cache layout (keyed by fetch date, so anything fetched today is "fresh"):
    {cache_dir}/prices/{YYYY-MM-DD}/{TICKER}.parquet   — OHLCV, tz-naive index
    {cache_dir}/info/{YYYY-MM-DD}/{TICKER}.parquet     — one row, INFO_FIELDS only
    {cache_dir}/universe/sp500_{YYYY-MM-DD}.parquet    — S&P 500 symbol list

`.info` is slow and rate-limited, so only the fields actually consumed
downstream are fetched and cached (see INFO_FIELDS). Per-ticker failures are
logged and skipped — they are never fatal to the run.
"""

import gc
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, TypeVar

import numpy as np
import pandas as pd

from .config import Config

log = logging.getLogger("quantum_alpha.data")

T = TypeVar("T")

# The only .info fields the pipeline consumes: universe filters (marketCap,
# averageVolume) and report metadata (sector, shortName). Snapshot
# fundamentals are point-in-time TODAY and are FORBIDDEN as features
# (CLAUDE.md invariants 1 and 2) — they may never reach the feature matrix.
INFO_FIELDS = [
    "marketCap",
    "averageVolume",
    "sector",
    "shortName",
]


@dataclass
class StockData:
    ticker: str
    prices: pd.DataFrame          # OHLCV, tz-naive DatetimeIndex
    info: Dict                    # cached subset of yfinance .info
    sector: str = "Unknown"
    market_cap: float = 0.0


def with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 4,
    backoff_base: float = 2.0,
    label: str = "call",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``fn`` with exponential backoff (2s, 4s, 8s, 16s by default).

    Raises the last exception if every attempt fails; callers decide whether
    that is fatal (for per-ticker fetches it never is — log and skip).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — network errors vary widely
            last_exc = exc
            if attempt < retries:
                delay = backoff_base * (2 ** attempt)
                log.warning(f"{label} failed (attempt {attempt + 1}/{retries + 1}): "
                            f"{exc} — retrying in {delay:.0f}s")
                sleep(delay)
    raise last_exc  # type: ignore[misc]


def _normalise_prices(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Standardise a raw yfinance OHLCV frame; None if unusable."""
    if df is None or df.empty:
        return None
    df = df.copy()
    df.columns = [str(c).strip().title() for c in df.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(col not in df.columns for col in required):
        return None
    df = df[required]
    # tz-naive index: everything downstream compares against naive timestamps
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df = df[df["Close"] > 0].dropna(subset=required)
    if len(df) < 100:
        return None
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col].astype(np.float32)
    df["Volume"] = df["Volume"].astype(np.int64)
    return df


class YFinanceDataProvider:
    """Real market data via yfinance, behind a parquet cache.

    The cache is keyed by fetch date: data fetched today is served from disk
    (< 24 h fresh), so repeated runs in a day never touch the network.
    """

    def __init__(self, config: Config):
        self.config = config
        self.cache_root = Path(config.cache_dir)

    # ---------------------------------------------------------------- cache
    def _today_key(self) -> str:
        return date.today().isoformat()

    def _price_cache_path(self, ticker: str) -> Path:
        return self.cache_root / "prices" / self._today_key() / f"{ticker}.parquet"

    def _info_cache_path(self, ticker: str) -> Path:
        return self.cache_root / "info" / self._today_key() / f"{ticker}.parquet"

    def _load_cached_prices(self, ticker: str) -> Optional[pd.DataFrame]:
        path = self._price_cache_path(ticker)
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception as exc:
                log.warning(f"Corrupt price cache for {ticker}: {exc}")
        return None

    def _store_prices(self, ticker: str, df: pd.DataFrame) -> None:
        path = self._price_cache_path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

    def _load_cached_info(self, ticker: str) -> Optional[Dict]:
        path = self._info_cache_path(ticker)
        if path.exists():
            try:
                row = pd.read_parquet(path)
                return {k: row[k].iloc[0] for k in row.columns}
            except Exception as exc:
                log.warning(f"Corrupt info cache for {ticker}: {exc}")
        return None

    def _store_info(self, ticker: str, info: Dict) -> None:
        path = self._info_cache_path(ticker)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([info]).to_parquet(path)

    # ------------------------------------------------------------- universe
    def get_sp500_tickers(self) -> List[str]:
        """Current S&P 500 components from Wikipedia, cached daily."""
        cache = self.cache_root / "universe" / f"sp500_{self._today_key()}.parquet"
        if cache.exists():
            try:
                tickers = pd.read_parquet(cache)["Symbol"].tolist()
                log.info(f"S&P 500 list from cache: {len(tickers)} tickers")
                return tickers
            except Exception:
                pass

        def _fetch() -> List[str]:
            # Wikipedia 403s urllib's default user-agent, so fetch the HTML
            # with a browser UA and hand the markup to pd.read_html.
            import io
            import urllib.request
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (quantum-alpha research)"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8")
            tables = pd.read_html(io.StringIO(html))
            return tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()

        try:
            tickers = with_retry(
                _fetch,
                retries=self.config.fetch_retries,
                backoff_base=self.config.fetch_backoff_base,
                label="S&P 500 list fetch",
            )
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"Symbol": tickers}).to_parquet(cache)
            log.info(f"Fetched {len(tickers)} S&P 500 tickers")
            return tickers
        except Exception as exc:
            log.warning(f"Could not fetch S&P 500 list: {exc} — using fallback")
            return self._fallback_universe()

    @staticmethod
    def _fallback_universe() -> List[str]:
        """If the Wikipedia scrape fails, a solid cross-sector universe."""
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

    @staticmethod
    def get_custom_universe(tickers: List[str]) -> List[str]:
        return [t.upper().strip() for t in tickers if t.strip()]

    # --------------------------------------------------------------- prices
    def fetch_prices(self, ticker: str, period: str = "3y") -> Optional[pd.DataFrame]:
        """OHLCV for one ticker: cache first, then network with retry."""
        cached = self._load_cached_prices(ticker)
        if cached is not None:
            return cached

        def _fetch() -> pd.DataFrame:
            import yfinance as yf
            return yf.Ticker(ticker).history(period=period, auto_adjust=True)

        try:
            raw = with_retry(
                _fetch,
                retries=self.config.fetch_retries,
                backoff_base=self.config.fetch_backoff_base,
                label=f"price fetch {ticker}",
            )
        except Exception as exc:
            log.warning(f"Skipping {ticker}: price fetch failed ({exc})")
            return None

        df = _normalise_prices(raw)
        if df is None:
            log.warning(f"Skipping {ticker}: unusable price history")
            return None
        self._store_prices(ticker, df)
        return df

    def fetch_batch_prices(
        self, tickers: List[str], period: str = "3y"
    ) -> Dict[str, pd.DataFrame]:
        """Prices for many tickers: serve cached ones, batch-download the rest."""
        results: Dict[str, pd.DataFrame] = {}
        to_fetch: List[str] = []
        for ticker in tickers:
            cached = self._load_cached_prices(ticker)
            if cached is not None:
                results[ticker] = cached
            else:
                to_fetch.append(ticker)

        if results:
            log.info(f"Price cache hit for {len(results)} / {len(tickers)} tickers")

        batch_size = self.config.yfinance_batch_size
        for i in range(0, len(to_fetch), batch_size):
            batch = to_fetch[i:i + batch_size]
            log.info(f"Downloading batch {i // batch_size + 1}: {len(batch)} tickers")

            def _download(batch=batch):
                import yfinance as yf
                return yf.download(
                    batch, period=period, auto_adjust=True,
                    group_by="ticker", threads=True, progress=False,
                )

            try:
                data = with_retry(
                    _download,
                    retries=self.config.fetch_retries,
                    backoff_base=self.config.fetch_backoff_base,
                    label=f"batch download ({len(batch)} tickers)",
                )
            except Exception as exc:
                log.warning(f"Batch download failed ({exc}) — trying individually")
                for ticker in batch:
                    df = self.fetch_prices(ticker, period)
                    if df is not None:
                        results[ticker] = df
                continue

            if isinstance(data.columns, pd.MultiIndex):
                for ticker in batch:
                    try:
                        df = _normalise_prices(data[ticker])
                    except (KeyError, Exception):
                        df = None
                    if df is not None:
                        results[ticker] = df
                        self._store_prices(ticker, df)
                    else:
                        log.warning(f"Skipping {ticker}: no usable data in batch")
            elif len(batch) == 1:
                df = _normalise_prices(data)
                if df is not None:
                    results[batch[0]] = df
                    self._store_prices(batch[0], df)

            gc.collect()

        log.info(f"Prices ready for {len(results)} / {len(tickers)} tickers")
        return results

    # ----------------------------------------------------------------- info
    def fetch_info(self, ticker: str) -> Dict:
        """INFO_FIELDS subset of .info for one ticker, cached daily."""
        cached = self._load_cached_info(ticker)
        if cached is not None:
            return cached

        def _fetch() -> Dict:
            import yfinance as yf
            raw = yf.Ticker(ticker).info or {}
            return {k: raw.get(k) for k in INFO_FIELDS}

        try:
            info = with_retry(
                _fetch,
                retries=self.config.fetch_retries,
                backoff_base=self.config.fetch_backoff_base,
                label=f"info fetch {ticker}",
            )
        except Exception as exc:
            log.warning(f"Skipping info for {ticker}: {exc}")
            return {}
        self._store_info(ticker, info)
        return info

    def fetch_batch_info(self, tickers: List[str]) -> Dict[str, Dict]:
        results = {}
        for i, ticker in enumerate(tickers):
            if i % 20 == 0 and i > 0:
                log.info(f"Fetching fundamentals: {i}/{len(tickers)}")
            info = self.fetch_info(ticker)
            if info:
                results[ticker] = info
            if i % 5 == 0:
                time.sleep(0.1)   # rate-limiting kindness
        return results


class DataManager:
    """Orchestrates fetching + universe filtering."""

    def __init__(self, config: Config):
        self.config = config
        self.provider = YFinanceDataProvider(config)

    def get_universe(self, custom_tickers: Optional[List[str]] = None) -> List[str]:
        if custom_tickers:
            return self.provider.get_custom_universe(custom_tickers)
        return self.provider.get_sp500_tickers()

    def fetch_all(
        self, tickers: List[str], period: str = "3y"
    ) -> Dict[str, StockData]:
        """Fetch all data and apply universe filters."""
        if len(tickers) > self.config.max_universe_size:
            log.info(f"Universe capped at {self.config.max_universe_size} "
                     f"(from {len(tickers)})")
            tickers = tickers[: self.config.max_universe_size]

        prices_dict = self.provider.fetch_batch_prices(tickers, period)

        log.info("Fetching fundamental data (filter fields only)...")
        info_dict = self.provider.fetch_batch_info(list(prices_dict.keys()))

        result = {}
        skipped = {"low_cap": 0, "low_vol": 0, "price": 0}

        for ticker, prices in prices_dict.items():
            info = info_dict.get(ticker, {})
            sector = info.get("sector") or "Unknown"
            market_cap = _as_float(info.get("marketCap"))
            avg_volume = _as_float(info.get("averageVolume"))
            current_price = float(prices["Close"].iloc[-1])

            if 0 < market_cap < self.config.min_market_cap:
                skipped["low_cap"] += 1
                continue
            if 0 < avg_volume < self.config.min_avg_volume:
                skipped["low_vol"] += 1
                continue
            if not (self.config.min_price <= current_price <= self.config.max_price):
                skipped["price"] += 1
                continue

            result[ticker] = StockData(
                ticker=ticker,
                prices=prices,
                info=info,
                sector=str(sector),
                market_cap=market_cap,
            )

        log.info(f"Universe: {len(result)} stocks pass filters")
        log.info(f"Skipped — low cap: {skipped['low_cap']}, "
                 f"low vol: {skipped['low_vol']}, price: {skipped['price']}")
        gc.collect()
        return result


def _as_float(value, default: float = 0.0) -> float:
    try:
        f = float(value)
        return f if np.isfinite(f) else default
    except (TypeError, ValueError):
        return default
