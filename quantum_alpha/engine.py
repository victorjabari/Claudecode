"""Trading engine and CLI entry point."""

import argparse
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .backtest import Backtester
from .config import N_CORES, WORKER_CORES, Config
from .data import DataManager, StockData
from .integrity import build_integrity_report
from .portfolio import SignalGenerator
from .reporting import report

log = logging.getLogger("quantum_alpha.engine")


class TradingEngine:
    def __init__(self, config: Optional[Config] = None,
                 custom_tickers: Optional[List[str]] = None):
        self.config = config or Config()
        self.dm = DataManager(self.config)
        self.gen = SignalGenerator(self.config)
        self.bt = Backtester(self.config)
        self.custom_tickers = custom_tickers
        self._stock_data: Optional[Dict[str, StockData]] = None
        self._train_cutoff: Optional[datetime] = None

    def load_data(self) -> Dict[str, StockData]:
        if self._stock_data is None:
            universe = self.dm.get_universe(self.custom_tickers)
            self._stock_data = self.dm.fetch_all(universe)
        return self._stock_data

    def train(self) -> None:
        data = self.load_data()
        cutoff = datetime.now() - timedelta(days=self.config.prediction_horizon_days)
        self._train_cutoff = cutoff
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

    def backtest(self, years: int = 2, label_shuffler=None) -> Dict:
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        data = self.load_data()
        spy_prices = self.dm.provider.fetch_prices("SPY")
        if spy_prices is None:
            log.warning("SPY fetch failed — backtest will lack the SPY benchmark")
        return self.bt.run(data, start, end, spy_prices=spy_prices,
                           label_shuffler=label_shuffler)


def main(
    config: Optional[Config] = None,
    custom_tickers: Optional[List[str]] = None,
    skip_backtest: bool = False,
    run_falsification: bool = True,
) -> Dict:
    """Run the full pipeline: fetch → train → scan → portfolio → backtest."""
    t_start = time.perf_counter()
    config = config or Config()

    print("\n" + "=" * 90)
    print("QUANTUM ALPHA v5.1 — Live Quantitative Research Framework")
    print(f"Hardware: {N_CORES} cores, {WORKER_CORES} workers")
    print("Data: real market data via Yahoo Finance (daily parquet cache)")
    print("=" * 90 + "\n")

    engine = TradingEngine(config, custom_tickers)

    print("Step 1: Fetching market data (cache-first)...")
    print("-" * 50)
    engine.load_data()
    print(f"  Loaded {len(engine._stock_data)} stocks\n")

    print("Step 2: Training ML models on historical data...")
    print("-" * 50)
    engine.train()

    print("\nStep 3: Scanning for opportunities...")
    print("-" * 50)
    opps = engine.scan()

    print("\nStep 4: Optimising portfolio...")
    print("-" * 50)
    portfolio = engine.recommend_portfolio()

    if not skip_backtest:
        print("\nStep 5: Walk-forward backtest (2 years)...")
        print("-" * 50)
        bt_results = engine.backtest(years=2)
    else:
        print("\nStep 5: Backtest skipped (--no-backtest)")
        bt_results = {"error": "Skipped by user"}

    print("\nStep 6: Falsification suite + measured integrity report...")
    print("-" * 50)
    integrity_checks = build_integrity_report(
        config=config,
        features=engine.gen._last_features,
        all_prices={t: sd.prices for t, sd in engine._stock_data.items()},
        cutoff_date=engine._train_cutoff,
        cv_fold_summary=engine.gen.predictor.cv_fold_summary,
        bt_results=bt_results,
        run_permutation=run_falsification,
        run_feature_lag=run_falsification,
    )

    fi = engine.gen.predictor.get_feature_importances()
    full_report = report(opps, portfolio, bt_results, fi, config, integrity_checks)
    print("\n" + full_report)

    elapsed = time.perf_counter() - t_start
    print(f"\nTotal runtime: {elapsed:.1f}s")

    return {
        "opportunities": opps,
        "portfolio": portfolio,
        "backtest": bt_results,
        "feature_importances": fi,
        "integrity_checks": integrity_checks,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quantum Alpha — Live Market Research")
    parser.add_argument(
        "--tickers", type=str, default=None,
        help="Comma-separated list of tickers (default: S&P 500)")
    parser.add_argument(
        "--no-backtest", action="store_true",
        help="Skip the backtest step for faster scans")
    parser.add_argument(
        "--horizon", type=int, default=None,
        help="Prediction horizon in trading days (default: 21)")
    parser.add_argument(
        "--cache-dir", type=str, default=None,
        help="Parquet cache directory (default: data/cache)")
    parser.add_argument(
        "--no-falsification", action="store_true",
        help="Skip the permutation + feature-lag refits (the falsification "
             "gate then reports NOT RUN and backtest output is withheld)")
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    """Build a Config INSTANCE from CLI args.

    Never assigns to Config class attributes: dataclass defaults are baked in
    at class-creation time, so class-attribute writes silently change nothing
    for code holding existing instances (the old --horizon bug).
    """
    overrides = {}
    if args.horizon is not None:
        overrides["prediction_horizon_days"] = args.horizon
    if getattr(args, "cache_dir", None):
        overrides["cache_dir"] = args.cache_dir
    return Config(**overrides)


def cli(argv: Optional[List[str]] = None) -> Dict:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    args = build_arg_parser().parse_args(argv)
    config = config_from_args(args)

    tickers = None
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]

    return main(config=config, custom_tickers=tickers,
                skip_backtest=args.no_backtest,
                run_falsification=not args.no_falsification)
