"""Backtester: cost accounting, turnover, annualization, benchmarks.

CLAUDE.md required test (e): a round-trip on a known trade costs exactly the
configured bps per side.
"""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from quantum_alpha.backtest import (
    Backtester,
    compute_rebalance,
    run_simulation,
    series_metrics,
)
from tests.conftest import make_ohlcv, make_universe

COST_RATE = 0.001   # 10 bps per side


def _constant_closes(tickers, n_days=10, price=100.0):
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    return pd.DataFrame({t: price for t in tickers}, index=idx)


# --------------------------------------------------------------- unit costs
def test_round_trip_costs_exactly_ten_bps_per_side():
    # BUY: deploy everything into A at 10 bps.
    targets, traded, cost_buy = compute_rebalance(
        current_dollars={}, target_weights={"A": 1.0},
        port_value=1_000_000.0, invest_fraction=1.0, cost_rate=COST_RATE,
    )
    assert targets["A"] == pytest.approx(999_000.0)   # sized net of cost
    assert traded == pytest.approx(999_000.0)
    assert cost_buy == pytest.approx(999_000.0 * COST_RATE)

    # SELL: liquidate the same position at an unchanged price.
    _, traded_sell, cost_sell = compute_rebalance(
        current_dollars={"A": 999_000.0}, target_weights={},
        port_value=999_000.0, invest_fraction=1.0, cost_rate=COST_RATE,
    )
    assert traded_sell == pytest.approx(999_000.0)
    assert cost_sell == pytest.approx(999_000.0 * COST_RATE)

    # Round trip = 2 sides × 10 bps on the traded notional. Exactly.
    assert cost_buy + cost_sell == pytest.approx(2 * COST_RATE * 999_000.0)


def test_simulation_round_trip_on_flat_prices_loses_only_costs():
    closes = _constant_closes(["A"], n_days=10)
    rebal_dates = [closes.index[0], closes.index[4]]
    plan = {closes.index[0]: {"A": 1.0}, closes.index[4]: {}}

    sim = run_simulation(
        closes, rebal_dates, closes.index[-1],
        weights_fn=lambda d: plan[d],
        cost_rate=COST_RATE, invest_fraction=1.0, initial_capital=1_000_000.0,
    )
    # Flat prices: the ONLY loss must be the two cost legs (999 + 999).
    assert sim["total_costs"] == pytest.approx(1_998.0)
    assert sim["values"].iloc[-1] == pytest.approx(1_000_000.0 - 1_998.0)


def test_full_switch_turnover_is_two_sided():
    closes = _constant_closes(["A", "B"], n_days=15)
    rebal_dates = [closes.index[0], closes.index[5], closes.index[10]]
    plan = {
        closes.index[0]: {"A": 1.0},
        closes.index[5]: {"B": 1.0},    # full switch: sell A AND buy B
        closes.index[10]: {"B": 1.0},
    }
    sim = run_simulation(
        closes, rebal_dates, closes.index[-1],
        weights_fn=lambda d: plan[d],
        cost_rate=COST_RATE, invest_fraction=1.0, initial_capital=1_000_000.0,
    )
    assert sim["turnover"][1] == pytest.approx(2.0, rel=0.01)
    assert sim["turnover"][2] == pytest.approx(0.0, abs=0.01)   # hold


# ------------------------------------------------------------ annualization
def test_metrics_annualize_with_actual_period_length():
    # Two years, valued every 21 trading days, +1% per period.
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2022-01-03") + pd.Timedelta(days=int(i * 30.4))
         for i in range(25)]
    )
    values = pd.Series(1_000_000.0 * 1.01 ** np.arange(25), index=idx)

    m = series_metrics(values, risk_free_rate=0.0, periods_per_year=12)
    assert m["n_periods"] == 24
    assert m["total_return"] == pytest.approx(1.01 ** 24 - 1)
    # ~2 years → CAGR ≈ 1.01^12 − 1 per year
    assert m["cagr"] == pytest.approx(1.01 ** 12 - 1, rel=0.02)
    # Constant period returns → (near-)zero annualized vol
    assert m["volatility"] == pytest.approx(0.0, abs=1e-9)
    assert m["max_drawdown"] == pytest.approx(0.0)


# -------------------------------------------------------------- integration
def test_backtester_reports_costs_and_benchmarks_on_identical_dates(fast_config):
    cfg = dataclasses.replace(fast_config, backtest_retrain_frequency=126)
    universe = make_universe(n_tickers=6, n_days=600, seed=21)
    spy = make_ohlcv(n_days=600, seed=777)

    start = universe["SYN00"].prices.index[0]
    end = universe["SYN00"].prices.index[-1]

    result = Backtester(cfg).run(universe, start, end, spy_prices=spy)
    assert "error" not in result

    assert result["cost_bps_per_side"] == 10.0
    assert result["periods_per_year"] == pytest.approx(12.0)
    assert result["turnover_annualized"] >= 0.0
    assert len(result["period_returns"]) == result["num_rebalances"]

    ew = result["benchmarks"]["equal_weight"]
    assert "error" not in ew
    # The EW benchmark always trades, so it must always pay costs.
    assert ew["total_costs"] > 0
    # Identical dates: same number of periods, same window length.
    assert ew["n_periods"] == result["n_periods"]
    assert ew["years"] == pytest.approx(result["years"])
    assert ew["active_cagr"] == pytest.approx(result["cagr"] - ew["cagr"])

    spy_m = result["benchmarks"]["SPY"]
    assert "error" not in spy_m
    assert spy_m["n_periods"] == result["n_periods"]
    # SPY buy-and-hold: one initial buy, then ~zero turnover.
    assert spy_m["turnover_annualized"] < ew["turnover_annualized"] + 1.0

    for key in ("total_return", "cagr", "volatility", "sharpe_ratio",
                "max_drawdown", "final_value"):
        assert np.isfinite(result[key])
        assert np.isfinite(ew[key])
        assert np.isfinite(spy_m[key])
