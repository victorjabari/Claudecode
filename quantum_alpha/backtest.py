"""Walk-forward backtester with mandatory costs and benchmarks.

CLAUDE.md invariants 4 and 5:
- Every simulation (strategy AND benchmarks) charges ``transaction_cost_bps``
  per side on every dollar of traded notional, and reports annualized
  two-sided turnover (buys + sells, divided by portfolio value).
- Every backtest reports SPY total return and the equal-weight portfolio of
  the same universe over IDENTICAL dates, through the same simulation engine.
  Benchmarks are fully invested; the strategy's cash reserve is part of the
  strategy.

Return-series conventions:
- The per-period return series is ``period_ret`` — one observation per
  rebalance period (21 trading days by default), NOT daily. Volatility is
  annualized with sqrt(252 / rebalance_frequency_days).
- CAGR is measured from the first rebalance date (when capital is actually
  deployed) to the final valuation date. The old code divided by years that
  included the 2-year training warm-up, understating annualized figures.
- The universe is today's survivors (yfinance has no delisted tickers), so
  even the benchmarked comparison inherits survivorship bias. The
  equal-weight benchmark uses the SAME survivor set, which is what makes the
  strategy-vs-EW comparison apples-to-apples.
"""

import gc
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import Config
from .data import StockData
from .portfolio import SignalGenerator

log = logging.getLogger("quantum_alpha.backtest")

WeightsFn = Callable[[pd.Timestamp], Dict[str, float]]


def compute_rebalance(
    current_dollars: Dict[str, float],
    target_weights: Dict[str, float],
    port_value: float,
    invest_fraction: float,
    cost_rate: float,
) -> Tuple[Dict[str, float], float, float]:
    """Size targets and transaction costs for one rebalance.

    Returns (target_dollars, traded_notional, cost). Costs are charged at
    ``cost_rate`` on every traded dollar (each side); targets are sized on
    the post-cost portfolio value so cash never goes negative.
    """
    def _traded(targets: Dict[str, float]) -> float:
        tickers = set(targets) | set(current_dollars)
        return float(sum(
            abs(targets.get(t, 0.0) - current_dollars.get(t, 0.0))
            for t in tickers
        ))

    # First pass estimates the cost, second pass sizes targets net of it.
    est = {t: w * port_value * invest_fraction for t, w in target_weights.items()}
    v_net = port_value - _traded(est) * cost_rate
    targets = {t: w * v_net * invest_fraction for t, w in target_weights.items()}
    traded = _traded(targets)
    cost = traded * cost_rate
    return targets, traded, cost


def run_simulation(
    closes: pd.DataFrame,
    rebal_dates: List[pd.Timestamp],
    end_date: pd.Timestamp,
    weights_fn: WeightsFn,
    cost_rate: float,
    invest_fraction: float,
    initial_capital: float,
) -> Dict:
    """Generic weight-policy simulation. Used by the strategy and every
    benchmark so that dates and cost treatment are identical."""
    cash = initial_capital
    shares: Dict[str, float] = {}
    values, turnover, history = [], [], []
    n_trades = 0
    total_costs = 0.0

    for rebal_date in rebal_dates:
        prices = closes.loc[rebal_date]
        port_value = cash + float(sum(
            q * prices[t] for t, q in shares.items()
        ))

        weights = {
            t: w for t, w in weights_fn(rebal_date).items()
            if t in closes.columns and np.isfinite(prices[t]) and prices[t] > 0
        }
        current_dollars = {t: q * float(prices[t]) for t, q in shares.items()}
        targets, traded, cost = compute_rebalance(
            current_dollars, weights, port_value, invest_fraction, cost_rate,
        )

        n_trades += sum(
            1 for t in set(targets) | set(current_dollars)
            if abs(targets.get(t, 0.0) - current_dollars.get(t, 0.0)) > 1.0
        )
        shares = {t: d / float(prices[t]) for t, d in targets.items() if d > 0}
        cash = max(0.0, port_value - cost - sum(targets.values()))
        total_costs += cost
        turnover.append(traded / port_value if port_value > 0 else 0.0)

        post_cost_value = port_value - cost
        values.append((rebal_date, post_cost_value))
        history.append({
            "date": rebal_date,
            "portfolio_value": post_cost_value,
            "n_positions": len(shares),
            "period_cost": cost,
            "period_turnover": turnover[-1],
        })

    final_prices = closes.loc[end_date]
    final_value = cash + float(sum(
        q * final_prices[t] for t, q in shares.items()
    ))
    values.append((end_date, final_value))

    value_series = pd.Series(
        [v for _, v in values],
        index=pd.DatetimeIndex([d for d, _ in values]),
        name="portfolio_value",
    )
    return {
        "values": value_series,
        "turnover": turnover,
        "total_costs": total_costs,
        "num_trades": n_trades,
        "history": history,
    }


def series_metrics(
    values: pd.Series,
    risk_free_rate: float,
    periods_per_year: float,
) -> Dict:
    """Net-of-cost performance metrics for a portfolio-value path sampled at
    rebalance dates. ``period_ret`` has one observation per rebalance period."""
    period_ret = values.pct_change().dropna()
    years = max(0.1, (values.index[-1] - values.index[0]).days / 365.25)

    total_return = float(values.iloc[-1] / values.iloc[0] - 1)
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1)
    vol = (
        float(period_ret.std() * np.sqrt(periods_per_year))
        if len(period_ret) > 1 else 0.0
    )
    sharpe = (cagr - risk_free_rate) / max(vol, 1e-4)

    running_max = values.cummax()
    max_dd = float((values / running_max - 1).min())

    return {
        "total_return": total_return,
        "cagr": cagr,
        "volatility": vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "final_value": float(values.iloc[-1]),
        "years": years,
        "n_periods": int(len(period_ret)),
    }


class Backtester:
    def __init__(self, config: Config):
        self.config = config

    def run(
        self,
        stock_data: Dict[str, StockData],
        start_date: datetime,
        end_date: datetime,
        spy_prices: Optional[pd.DataFrame] = None,
        label_shuffler=None,
    ) -> Dict:
        """Walk-forward backtest with costs and benchmarks on identical dates.

        ``label_shuffler`` is forwarded to model training (falsification
        suite: permute forward-return labels within each date).
        """
        cfg = self.config
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

        closes = pd.DataFrame(
            {t: sd.prices["Close"].astype(np.float64) for t, sd in stock_data.items()}
        ).loc[all_dates]

        train_end_idx = min(cfg.ml_train_window, len(all_dates) // 2)
        rebal_dates = list(all_dates[train_end_idx :: cfg.rebalance_frequency_days])
        sim_end = all_dates[-1]
        if rebal_dates and rebal_dates[-1] == sim_end:
            rebal_dates = rebal_dates[:-1]
        if len(rebal_dates) < 2:
            return {"error": "No rebalance periods"}

        initial_capital = 1_000_000.0
        cost_rate = cfg.transaction_cost_bps / 10_000.0
        periods_per_year = cfg.trading_days_per_year / cfg.rebalance_frequency_days

        # ----------------------------------------------------------- strategy
        gen = SignalGenerator(cfg)
        retrain_freq = max(1, cfg.backtest_retrain_frequency
                           // cfg.rebalance_frequency_days)
        rebal_counter = {"n": 0}

        def strategy_weights(rebal_date: pd.Timestamp) -> Dict[str, float]:
            if rebal_counter["n"] % retrain_freq == 0:
                train_data = {}
                for t, sd in stock_data.items():
                    tp = sd.prices[sd.prices.index < rebal_date]
                    if len(tp) > 100:
                        train_data[t] = StockData(t, tp, sd.info, sd.sector,
                                                  sd.market_cap)
                if train_data:
                    gen.train(train_data, cutoff_date=rebal_date,
                              label_shuffler=label_shuffler)
                    log.info(f"Retrained at {rebal_date.date()}")
            rebal_counter["n"] += 1

            current_data = {}
            for t, sd in stock_data.items():
                cp = sd.prices[sd.prices.index <= rebal_date]
                if len(cp) > 100:
                    current_data[t] = StockData(t, cp, sd.info, sd.sector,
                                                sd.market_cap)

            gen._last_features = {}
            signals = gen.generate_signals(current_data)
            sel = gen.select_portfolio(signals, current_data, min_return=0.03)
            gc.collect()
            return {
                t: info["weight"] for t, info in sel.get("positions", {}).items()
            }

        strat_sim = run_simulation(
            closes, rebal_dates, sim_end, strategy_weights,
            cost_rate=cost_rate,
            invest_fraction=1.0 - cfg.cash_reserve,
            initial_capital=initial_capital,
        )
        strat_metrics = series_metrics(
            strat_sim["values"], cfg.risk_free_rate, periods_per_year,
        )

        # --------------------------------------------------------- benchmarks
        benchmarks: Dict[str, Dict] = {}

        ew_weights = {t: 1.0 / len(stock_data) for t in stock_data}
        ew_sim = run_simulation(
            closes, rebal_dates, sim_end, lambda d: ew_weights,
            cost_rate=cost_rate, invest_fraction=1.0,
            initial_capital=initial_capital,
        )
        ew_metrics = series_metrics(
            ew_sim["values"], cfg.risk_free_rate, periods_per_year,
        )
        ew_metrics["turnover_annualized"] = float(
            np.mean(ew_sim["turnover"]) * periods_per_year
        )
        ew_metrics["total_costs"] = ew_sim["total_costs"]
        ew_metrics["active_cagr"] = strat_metrics["cagr"] - ew_metrics["cagr"]
        benchmarks["equal_weight"] = ew_metrics

        if spy_prices is not None and len(spy_prices) > 0:
            spy_close = (
                spy_prices["Close"].astype(np.float64)
                .reindex(all_dates, method="ffill")
            )
            if spy_close.isna().any():
                benchmarks["SPY"] = {"error": "SPY history does not cover the "
                                              "backtest window"}
            else:
                spy_frame = pd.DataFrame({"SPY": spy_close})
                spy_sim = run_simulation(
                    spy_frame, rebal_dates, sim_end, lambda d: {"SPY": 1.0},
                    cost_rate=cost_rate, invest_fraction=1.0,
                    initial_capital=initial_capital,
                )
                spy_metrics = series_metrics(
                    spy_sim["values"], cfg.risk_free_rate, periods_per_year,
                )
                spy_metrics["turnover_annualized"] = float(
                    np.mean(spy_sim["turnover"]) * periods_per_year
                )
                spy_metrics["total_costs"] = spy_sim["total_costs"]
                spy_metrics["active_cagr"] = strat_metrics["cagr"] - spy_metrics["cagr"]
                benchmarks["SPY"] = spy_metrics
        else:
            benchmarks["SPY"] = {"error": "SPY data unavailable"}

        # ------------------------------------------------------------ result
        result = {
            "initial_capital": initial_capital,
            "cost_bps_per_side": cfg.transaction_cost_bps,
            "periods_per_year": periods_per_year,
            "rebalance_frequency_days": cfg.rebalance_frequency_days,
            "num_rebalances": len(rebal_dates),
            "start_date": rebal_dates[0],
            "end_date": sim_end,
            # strategy, net of costs
            **strat_metrics,
            "turnover_annualized": float(
                np.mean(strat_sim["turnover"]) * periods_per_year
            ),
            "total_costs": strat_sim["total_costs"],
            "num_trades": strat_sim["num_trades"],
            "period_returns": strat_sim["values"].pct_change().dropna(),
            "history": strat_sim["history"],
            "benchmarks": benchmarks,
            # model diagnostics from the last retrain (for integrity reporting)
            "oof_r2": gen.predictor.oof_r2,
            "cv_fold_summary": gen.predictor.cv_fold_summary,
        }
        log.info(
            f"Backtest done: strategy CAGR {strat_metrics['cagr']:+.1%} "
            f"(net of {cfg.transaction_cost_bps:.0f} bps/side), "
            f"EW CAGR {ew_metrics['cagr']:+.1%}"
        )
        return result
