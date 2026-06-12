"""Portfolio construction: conviction tiers, risk scoring, optimizer, signals."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from .config import Config
from .data import StockData
from .features import FeatureEngine
from .model import ReturnPredictor

log = logging.getLogger("quantum_alpha.portfolio")


@dataclass
class Signal:
    ticker: str
    expected_return: float        # point estimate
    ci_low: float                 # lower bound of prediction interval
    ci_high: float                # upper bound
    confidence: float             # 0-1 model agreement
    conviction: str               # HIGH / MEDIUM / LOW / SPECULATIVE / AVOID
    holding_period: int
    factors: Dict
    timestamp: datetime = field(default_factory=datetime.now)


def classify_conviction(
    expected_return: float,
    ci_low: float,
    ci_high: float,
    confidence: float,
    tree_std: float,
) -> str:
    """
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
    elif ci_low > -0.05 and confidence > 0.45:
        return "MEDIUM"
    elif confidence > 0.30:
        return "LOW"
    return "SPECULATIVE"


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
        if not tickers:
            return {}
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
            "max_position": float(max(weights.values())),
            "sector_weights": dict(sector_w),
        }


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

        mom_cols = [c for c in features.columns if c.startswith("mom_")]
        scores["momentum_quality"] = (
            float(features[mom_cols].iloc[-1].mean()) if mom_cols else 0.0
        )

        # Fundamental quality from .info snapshots — Phase 1 removes this
        # (point-in-time-today data must not drive historical-model scoring).
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

        scores["composite"] = (
            0.35 * scores["conf_adj_return"]
            + 0.25 * scores["sharpe_est"] / 3.0
            + 0.15 * scores["momentum_quality"]
            + 0.25 * scores["fundamental_quality"]
        )
        return scores


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
                    "rf_pred": pred["rf_pred"],
                    "gb_pred": pred["gb_pred"],
                    "tree_std": pred["tree_std"],
                    "calibrated_std": pred["calibrated_std"],
                },
            ))

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
