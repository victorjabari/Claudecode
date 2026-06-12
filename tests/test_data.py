"""Data layer: parquet cache, retry/backoff, graceful per-ticker failure."""

import numpy as np
import pandas as pd
import pytest

from quantum_alpha.config import Config
from quantum_alpha.data import (
    YFinanceDataProvider,
    _normalise_prices,
    with_retry,
)
from tests.conftest import make_ohlcv


# ----------------------------------------------------------------- retry
def test_with_retry_succeeds_after_failures():
    calls = {"n": 0}
    delays = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    result = with_retry(flaky, retries=4, backoff_base=2.0,
                        sleep=delays.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert delays == [2.0, 4.0]   # exponential backoff


def test_with_retry_exhausts_and_raises():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise TimeoutError("down")

    with pytest.raises(TimeoutError):
        with_retry(always_fails, retries=3, backoff_base=2.0,
                   sleep=lambda _: None)
    assert calls["n"] == 4   # initial + 3 retries


# ----------------------------------------------------------------- normalise
def test_normalise_prices_strips_timezone_and_casts():
    df = make_ohlcv(n_days=200)
    df.index = df.index.tz_localize("America/New_York")
    out = _normalise_prices(df)
    assert out is not None
    assert out.index.tz is None
    assert out["Close"].dtype == np.float32
    assert out["Volume"].dtype == np.int64


def test_normalise_prices_rejects_short_history():
    assert _normalise_prices(make_ohlcv(n_days=50)) is None


def test_normalise_prices_rejects_missing_columns():
    df = make_ohlcv(n_days=200).drop(columns=["Volume"])
    assert _normalise_prices(df) is None


# ----------------------------------------------------------------- cache
def test_price_cache_roundtrip(tmp_path):
    cfg = Config(cache_dir=str(tmp_path), fetch_retries=0)
    provider = YFinanceDataProvider(cfg)
    df = make_ohlcv(n_days=300)
    provider._store_prices("TEST", df)

    loaded = provider._load_cached_prices("TEST")
    assert loaded is not None
    pd.testing.assert_frame_equal(loaded, df)


def test_fetch_prices_serves_cache_without_network(tmp_path, monkeypatch):
    cfg = Config(cache_dir=str(tmp_path), fetch_retries=0)
    provider = YFinanceDataProvider(cfg)
    df = make_ohlcv(n_days=300)
    provider._store_prices("TEST", df)

    import yfinance

    def explode(*a, **k):
        raise AssertionError("network must not be touched on cache hit")

    monkeypatch.setattr(yfinance, "Ticker", explode)
    monkeypatch.setattr(yfinance, "download", explode)

    out = provider.fetch_prices("TEST")
    assert out is not None
    pd.testing.assert_frame_equal(out, df)

    batch = provider.fetch_batch_prices(["TEST"])
    assert "TEST" in batch


def test_info_cache_roundtrip(tmp_path):
    cfg = Config(cache_dir=str(tmp_path), fetch_retries=0)
    provider = YFinanceDataProvider(cfg)
    info = {"marketCap": 1e10, "averageVolume": 2e6, "sector": "Tech",
            "shortName": "Test Corp"}
    provider._store_info("TEST", info)

    loaded = provider._load_cached_info("TEST")
    assert loaded is not None
    assert loaded["sector"] == "Tech"
    assert float(loaded["marketCap"]) == 1e10


def test_failed_ticker_is_skipped_not_fatal(tmp_path, monkeypatch):
    cfg = Config(cache_dir=str(tmp_path), fetch_retries=0)
    provider = YFinanceDataProvider(cfg)

    import yfinance

    def explode(*a, **k):
        raise ConnectionError("yahoo is down")

    monkeypatch.setattr(yfinance, "Ticker", explode)
    monkeypatch.setattr(yfinance, "download", explode)

    # Must not raise — failures are logged and skipped.
    out = provider.fetch_batch_prices(["NOPE1", "NOPE2"])
    assert out == {}
    assert provider.fetch_prices("NOPE3") is None
    assert provider.fetch_info("NOPE4") == {}
