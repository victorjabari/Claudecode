"""Return prediction: stacked ensemble (RF + GB → Ridge meta-learner).

Temporal correctness (CLAUDE.md invariant 3):
- Training data is ONE pooled panel, MultiIndex (date, ticker), sorted by
  date. Never ticker-stacked arrays.
- Cross-validation is purged walk-forward on UNIQUE DATES with an embargo of
  one prediction horizon: forward-return labels overlap for `horizon` trading
  days, so every fold must satisfy
      position(max train date) + embargo < position(min val date)
  on the panel's trading-day grid. Enforced by tests/test_cv.py.
- Labels at (t, ticker) end at the close `horizon` TRADING rows later in that
  ticker's own calendar; rows whose label ends at/after the cutoff are
  excluded (no calendar-day approximations).
- No global scaler: the old RobustScaler was fit on the full training set
  before out-of-fold prediction (a distributional leak across folds). Trees
  are scale-invariant and the cross-sectional z-score already standardises
  each date's cross-section, so it is gone entirely.

Uncertainty:
1. Individual RF tree predictions → prediction interval
2. RF vs GB disagreement → model agreement score
3. Out-of-fold residual distribution (purged splits) → calibrated intervals
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import RidgeCV

from .config import Config

log = logging.getLogger("quantum_alpha.model")


# ===========================================================================
# Pooled panel
# ===========================================================================
@dataclass
class Panel:
    """Pooled training panel, sorted by (date, ticker)."""
    X: pd.DataFrame            # MultiIndex (date, ticker) × features
    y: pd.Series               # forward return close[t] → close[t+h]
    label_end: pd.Series       # the date the label's return window ends

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.X.index.get_level_values("date")


def build_panel(
    all_features: Dict[str, pd.DataFrame],
    all_prices: Dict[str, pd.DataFrame],
    horizon: int,
    cutoff_date: datetime,
) -> Optional[Panel]:
    """Pool per-ticker features into one (date, ticker) panel with labels.

    A row at (t, ticker) is included only if its label window
    [t, t + horizon trading days] ends strictly BEFORE cutoff_date.
    """
    cutoff_ts = pd.Timestamp(cutoff_date)
    X_parts, y_parts, end_parts = [], [], []

    for ticker, feat in all_features.items():
        if ticker not in all_prices or feat is None or feat.empty:
            continue
        close = all_prices[ticker]["Close"].astype(np.float64)

        fwd = close.shift(-horizon) / close - 1
        # Label end date = the actual trading day `horizon` rows later.
        end_date = pd.Series(close.index, index=close.index).shift(-horizon)
        valid = fwd.notna() & end_date.notna() & (end_date < cutoff_ts)

        idx = feat.index.intersection(close.index[valid])
        if len(idx) == 0:
            continue

        Xt = feat.loc[idx].astype(np.float64)
        Xt["ticker"] = ticker
        Xt = Xt.set_index("ticker", append=True)
        X_parts.append(Xt)
        y_parts.append(pd.Series(fwd.loc[idx].values, index=Xt.index))
        end_parts.append(pd.Series(end_date.loc[idx].values, index=Xt.index))

    if not X_parts:
        return None

    X = pd.concat(X_parts)
    y = pd.concat(y_parts)
    label_end = pd.concat(end_parts)

    X.index.names = ["date", "ticker"]
    y.index.names = ["date", "ticker"]
    label_end.index.names = ["date", "ticker"]

    # Sort by date (then ticker) — the temporal ordering the CV relies on.
    order = X.index.sortlevel(["date", "ticker"])[1]
    X, y, label_end = X.iloc[order], y.iloc[order], label_end.iloc[order]

    # Drop non-finite rows.
    finite = np.isfinite(X.values).all(axis=1) & np.isfinite(y.values)
    return Panel(X=X.loc[finite], y=y.loc[finite], label_end=label_end.loc[finite])


def cross_sectional_normalise(X: pd.DataFrame) -> pd.DataFrame:
    """Z-score each feature ACROSS tickers at each date.

    Forces the model to learn RELATIVE signals, not absolute levels. A
    zero-variance (or single-stock) cross-section z-scores to 0.
    """
    g = X.groupby(level="date")
    mu = g.transform("mean")
    sd = g.transform("std")
    return (X - mu) / sd.where(sd > 0, 1.0)


# ===========================================================================
# Purged walk-forward cross-validation
# ===========================================================================
class PurgedWalkForwardCV:
    """Walk-forward CV over unique dates with a purging embargo.

    The unique, sorted panel dates are cut into ``n_splits + 1`` contiguous
    blocks. Fold i validates on block i+1 and trains on every date that ends
    at least ``embargo + 1`` trading positions before the validation block
    starts, so a training label window [t, t+embargo] can never reach into
    the validation period:

        position(max train date) + embargo < position(min val date)
    """

    def __init__(self, n_splits: int = 5, embargo: int = 21):
        if n_splits < 1:
            raise ValueError("n_splits must be >= 1")
        self.n_splits = n_splits
        self.embargo = embargo

    def split_dates(
        self, unique_dates: pd.DatetimeIndex
    ) -> Iterator[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        n = len(unique_dates)
        block_bounds = np.linspace(0, n, self.n_splits + 2).astype(int)

        for i in range(1, self.n_splits + 1):
            val_start, val_stop = block_bounds[i], block_bounds[i + 1]
            train_stop = val_start - self.embargo   # exclusive end
            if train_stop < 1 or val_stop <= val_start:
                continue
            yield unique_dates[:train_stop], unique_dates[val_start:val_stop]

    def split(
        self, sample_dates: pd.DatetimeIndex
    ) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, val_idx) into a sample array given each
        sample's date (the panel's date level)."""
        unique_dates = pd.DatetimeIndex(sample_dates.unique()).sort_values()
        for train_dates, val_dates in self.split_dates(unique_dates):
            train_idx = np.flatnonzero(sample_dates.isin(train_dates))
            val_idx = np.flatnonzero(sample_dates.isin(val_dates))
            if len(train_idx) and len(val_idx):
                yield train_idx, val_idx


# ===========================================================================
# Predictor
# ===========================================================================
class ReturnPredictor:
    def __init__(self, config: Config):
        self.config = config
        self.base_models: Dict[str, object] = {}
        self.meta_model = None
        self.feature_names: List[str] = []
        self.is_fitted = False
        self._feature_importances: Optional[np.ndarray] = None

        # Out-of-fold artifacts (purged splits) — calibration + audits
        self.oof_r2: Optional[float] = None
        self._oof_residuals: Optional[np.ndarray] = None
        self.oof_frame: Optional[pd.DataFrame] = None   # pred/y/tree_std/conf
        self.cv_fold_summary: List[Dict] = []

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

    def fit(
        self,
        all_features: Dict[str, pd.DataFrame],
        all_prices: Dict[str, pd.DataFrame],
        cutoff_date: datetime,
        label_shuffler=None,
    ) -> None:
        """Train on the pooled panel; every label window ends before cutoff.

        ``label_shuffler``: optional hook used by the falsification suite —
        called as label_shuffler(y) and must return a y Series with the same
        index (e.g. forward returns permuted within each date).
        """
        horizon = self.config.prediction_horizon_days
        panel = build_panel(all_features, all_prices, horizon, cutoff_date)
        if panel is None or len(panel.X) < 200:
            n = 0 if panel is None else len(panel.X)
            log.error(f"Only {n} panel rows — too few to train")
            return

        X = cross_sectional_normalise(panel.X)
        y = panel.y
        if label_shuffler is not None:
            y = label_shuffler(y)

        finite = np.isfinite(X.values).all(axis=1)
        X, y = X.loc[finite], y.loc[finite]

        self.feature_names = list(X.columns)
        sample_dates = X.index.get_level_values("date")
        n_dates = sample_dates.nunique()
        log.info(f"Panel: {len(X)} rows, {X.shape[1]} features, "
                 f"{n_dates} dates, {X.index.get_level_values('ticker').nunique()} tickers")
        log.info(f"Target: mean={y.mean():.2%}, std={y.std():.2%}")

        X_arr = X.values
        y_arr = y.values

        # --- Out-of-fold predictions on purged walk-forward splits ---
        cv = PurgedWalkForwardCV(
            n_splits=self.config.n_cv_folds,
            embargo=horizon,
        )
        model_names = ["rf", "gb"]
        oof_preds = {name: np.full(len(X_arr), np.nan) for name in model_names}
        oof_tree_std = np.full(len(X_arr), np.nan)
        self.cv_fold_summary = []

        unique_dates = pd.DatetimeIndex(sample_dates.unique()).sort_values()
        date_pos = {d: i for i, d in enumerate(unique_dates)}

        for fold_i, (train_idx, val_idx) in enumerate(cv.split(sample_dates)):
            X_tr, y_tr = X_arr[train_idx], y_arr[train_idx]
            X_val = X_arr[val_idx]

            fold_models = self._create_base_models()
            for name, mdl in fold_models.items():
                mdl.fit(X_tr, y_tr)
                oof_preds[name][val_idx] = mdl.predict(X_val)

            trees = fold_models["rf"].estimators_
            oof_tree_std[val_idx] = np.std(
                [t.predict(X_val) for t in trees], axis=0,
            )

            tr_dates = sample_dates[train_idx]
            va_dates = sample_dates[val_idx]
            self.cv_fold_summary.append({
                "fold": fold_i,
                "train_rows": len(train_idx),
                "val_rows": len(val_idx),
                "train_max_date": tr_dates.max(),
                "val_min_date": va_dates.min(),
                "val_max_date": va_dates.max(),
                "gap_trading_days": date_pos[va_dates.min()] - date_pos[tr_dates.max()],
                "embargo": horizon,
                "ordering_ok": bool(
                    date_pos[tr_dates.max()] + horizon < date_pos[va_dates.min()]
                ),
            })

        if not self.cv_fold_summary:
            log.error("No usable CV folds — not enough dates")
            return

        has_oof = np.all([np.isfinite(oof_preds[n]) for n in model_names], axis=0)
        if has_oof.sum() < 100:
            log.error(f"Only {has_oof.sum()} OOF rows — too few to calibrate")
            return

        meta_X = np.column_stack([oof_preds[n][has_oof] for n in model_names])
        meta_y = y_arr[has_oof]

        self.meta_model = RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0])
        self.meta_model.fit(meta_X, meta_y)
        oof_final = self.meta_model.predict(meta_X)
        self.oof_r2 = float(self.meta_model.score(meta_X, meta_y))

        # --- Calibration: OOF residuals from purged splits ---
        self._oof_residuals = meta_y - oof_final
        residual_std = np.std(self._oof_residuals)
        residual_mae = np.mean(np.abs(self._oof_residuals))

        # --- OOF frame for downstream audits (conviction tiers, Phase 5) ---
        spread = np.abs(oof_preds["rf"][has_oof] - oof_preds["gb"][has_oof])
        self.oof_frame = pd.DataFrame(
            {
                "pred": oof_final,
                "y": meta_y,
                "tree_std": oof_tree_std[has_oof],
                "confidence": 1.0 / (1.0 + spread * 5.0),
            },
            index=X.index[has_oof],
        )

        log.info(f"Purged OOF R²: {self.oof_r2:.4f} "
                 f"({has_oof.sum()} OOF rows, {len(self.cv_fold_summary)} folds)")
        log.info(f"OOF residual std: {residual_std:.2%}, MAE: {residual_mae:.2%}")

        if self.oof_r2 > 0.05:
            log.warning(f"OOF R² = {self.oof_r2:.3f} is suspiciously high for "
                        f"monthly equity data — hunt for leakage before "
                        f"trusting anything downstream.")
        if self.oof_r2 < -0.05:
            log.warning(f"OOF R² = {self.oof_r2:.3f} — model has no predictive power.")

        # Retrain base models on all panel data
        self.base_models = self._create_base_models()
        for name, mdl in self.base_models.items():
            mdl.fit(X_arr, y_arr)

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
            if feat is None or feat.empty:
                continue
            row = feat.iloc[-1:].values
            row = np.nan_to_num(row, nan=0.0, posinf=0.0, neginf=0.0)
            tickers.append(ticker)
            rows.append(row[0])

        if not tickers:
            return {}

        X_raw = np.vstack(rows).astype(np.float64)

        # Cross-sectional z-score at prediction time (same convention as
        # training normalisation: across tickers, per date).
        mu = X_raw.mean(axis=0)
        sigma = X_raw.std(axis=0, ddof=1) if len(tickers) > 1 else np.ones(X_raw.shape[1])
        sigma[~np.isfinite(sigma)] = 1.0
        sigma[sigma == 0] = 1.0
        X_normed = (X_raw - mu) / sigma

        preds_rf = self.base_models["rf"].predict(X_normed)
        preds_gb = self.base_models["gb"].predict(X_normed)

        meta_X = np.column_stack([preds_rf, preds_gb])
        final_preds = self.meta_model.predict(meta_X)

        # Uncertainty from individual RF trees
        rf_model = self.base_models["rf"]
        tree_preds = np.array([t.predict(X_normed) for t in rf_model.estimators_])
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
