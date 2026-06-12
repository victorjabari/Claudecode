"""Return prediction: stacked ensemble (RF + GB → Ridge meta-learner).

NOTE (Phase 0): carried over from quantum_alpha_v5.py unchanged. The
cross-validation here is KNOWN-BROKEN: TimeSeriesSplit is applied to arrays
stacked ticker-by-ticker, so folds split across tickers rather than time.
Phase 2 replaces it with a pooled (date, ticker) panel and purged k-fold
with an embargo.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler

from .config import Config

log = logging.getLogger("quantum_alpha.model")


class ReturnPredictor:
    """Stacked ensemble with uncertainty quantification.

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
        self._oof_residuals: Optional[np.ndarray] = None
        self.oof_r2: Optional[float] = None

    def _create_base_models(self) -> Dict:
        return {
            "rf": RandomForestRegressor(
                n_estimators=self.config.rf_n_estimators,
                max_depth=self.config.rf_max_depth,
                min_samples_leaf=self.config.rf_min_samples_leaf,
                max_features="sqrt",
                n_jobs=-1,
                random_state=self.config.random_seed,
            ),
            "gb": GradientBoostingRegressor(
                n_estimators=self.config.gb_n_estimators,
                max_depth=self.config.gb_max_depth,
                learning_rate=self.config.gb_learning_rate,
                min_samples_leaf=self.config.gb_min_samples_leaf,
                subsample=self.config.gb_subsample,
                random_state=self.config.random_seed,
            ),
        }

    @staticmethod
    def _cross_sectional_normalise(
        all_features: Dict[str, pd.DataFrame],
    ) -> Dict[str, pd.DataFrame]:
        """Z-score each feature ACROSS stocks at each date."""
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
        """Train on data strictly before cutoff_date."""
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
        log.info(f"Target: mean={y.mean():.2%}, std={y.std():.2%}")

        X_scaled = self.scaler.fit_transform(X)

        # --- Out-of-fold predictions for meta-learner + calibration ---
        tscv = TimeSeriesSplit(n_splits=self.config.n_cv_folds)
        model_names = ["rf", "gb"]
        oof_preds = {name: np.full(len(X_scaled), np.nan) for name in model_names}

        for train_idx, val_idx in tscv.split(X_scaled):
            X_tr, X_val = X_scaled[train_idx], X_scaled[val_idx]
            y_tr = y[train_idx]
            fold_models = self._create_base_models()
            for name, model in fold_models.items():
                model.fit(X_tr, y_tr)
                oof_preds[name][val_idx] = model.predict(X_val)

        has_oof = np.all([np.isfinite(oof_preds[n]) for n in model_names], axis=0)
        meta_X = np.column_stack([oof_preds[n][has_oof] for n in model_names])
        meta_y = y[has_oof]

        self.meta_model = RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0])
        self.meta_model.fit(meta_X, meta_y)
        oof_final = self.meta_model.predict(meta_X)
        self.oof_r2 = float(self.meta_model.score(meta_X, meta_y))

        self._oof_residuals = meta_y - oof_final
        residual_std = np.std(self._oof_residuals)
        residual_mae = np.mean(np.abs(self._oof_residuals))

        log.info(f"Meta-learner R²: {self.oof_r2:.4f}")
        log.info(f"OOF residual std: {residual_std:.2%}, MAE: {residual_mae:.2%}")

        if self.oof_r2 > 0.15:
            log.warning(f"R² = {self.oof_r2:.3f} on real data is unusually high. "
                        f"Inspect for leakage or regime-specific overfitting.")
        if self.oof_r2 < -0.05:
            log.warning(f"R² = {self.oof_r2:.3f} — model has no predictive power.")

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
                log.info(f"  {self.feature_names[i]:<25} "
                         f"{self._feature_importances[i]:.4f}")

        log.info("Training complete")

    def predict_batch(
        self, all_features: Dict[str, pd.DataFrame]
    ) -> Dict[str, Dict[str, float]]:
        """Predict with uncertainty quantification for the latest date."""
        if not self.is_fitted:
            return {}

        tickers, rows = [], []
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

        preds_rf = self.base_models["rf"].predict(X_scaled)
        preds_gb = self.base_models["gb"].predict(X_scaled)

        meta_X = np.column_stack([preds_rf, preds_gb])
        final_preds = self.meta_model.predict(meta_X)

        # Uncertainty from individual RF trees
        rf_model = self.base_models["rf"]
        tree_preds = np.array([tree.predict(X_scaled) for tree in rf_model.estimators_])
        tree_std = tree_preds.std(axis=0)
        pctl_low = np.percentile(tree_preds, self.config.bootstrap_percentiles[0], axis=0)
        pctl_high = np.percentile(tree_preds, self.config.bootstrap_percentiles[1], axis=0)

        calibrated_std = (
            float(np.std(self._oof_residuals))
            if self._oof_residuals is not None else 0.10
        )

        model_spread = np.abs(preds_rf - preds_gb)
        confidence = 1.0 / (1.0 + model_spread * 5.0)

        results = {}
        for i, ticker in enumerate(tickers):
            pred = float(np.clip(final_preds[i], -0.50, 1.00))
            cal_ci_low = pred - 1.28 * calibrated_std   # 80% interval
            cal_ci_high = pred + 1.28 * calibrated_std

            results[ticker] = {
                "expected_return": pred,
                "ci_low": min(float(pctl_low[i]), cal_ci_low),
                "ci_high": max(float(pctl_high[i]), cal_ci_high),
                "confidence": float(confidence[i]),
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
