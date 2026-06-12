"""Walk-forward backtester.

NOTE (Phase 0): carried over from quantum_alpha_v5.py unchanged. KNOWN GAPS,
scheduled for Phase 3: no transaction costs, no benchmark, and the rebalance
period return series is monthly but named/annualized ambiguously.
"""

import gc
import logging
from datetime import datetime
from typing import Dict

import numpy as np
import pandas as pd

from .config import Config
from .data import StockData
from .portfolio import SignalGenerator

log = logging.getLogger("quantum_alpha.backtest")


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

        for rebal_date in rebal_dates[:-1]:
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

            # Portfolio value at this rebalance
            port_val = cash
            for t, pos in positions.items():
                try:
                    price = stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                    port_val += pos["shares"] * price
                except Exception:
                    pass

            # Generate signals on data up to the rebalance date
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
                                           "action": "BUY", "shares": shares,
                                           "price": price})
                except Exception:
                    pass

            for t in positions:
                if t not in new_pos:
                    try:
                        price = stock_data[t].prices["Close"].loc[:rebal_date].iloc[-1]
                        trades.append({"date": rebal_date, "ticker": t,
                                       "action": "SELL",
                                       "shares": positions[t]["shares"],
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
