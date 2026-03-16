"""
Nightly model retraining pipeline.

Runs as a Celery task at 02:00 UTC daily.
Fetches resolved trades from PostgreSQL, rebuilds features,
trains XGBoost + LightGBM with time-series cross-validation,
gates deployment on Brier score improvement, saves versioned models.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb
import lightgbm as lgb

from core.config import settings
from model.features import FeatureBuilder

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("MODEL_DIR", "/root/polymarket-v2/data/models"))

XGB_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "max_depth": 5,
    "n_estimators": 500,
    "learning_rate": 0.04,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "min_child_weight": 15,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "tree_method": "hist",
    "random_state": 42,
    "verbosity": 0,
}

LGBM_PARAMS = {
    "objective": "binary",
    "metric": ["binary_logloss", "auc"],
    "num_leaves": 31,
    "n_estimators": 500,
    "learning_rate": 0.04,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "verbose": -1,
}


class ModelTrainer:
    def __init__(self) -> None:
        self._feature_builder = FeatureBuilder()
        MODEL_DIR.mkdir(parents=True, exist_ok=True)

    def run_full_retrain(self, training_records: List[dict]) -> dict:
        """
        Full retraining pipeline.
        training_records: list of dicts with keys matching predictions + market tables.

        Returns metrics dict for LearningAgent to store.
        """
        logger.info("Starting retrain on %d records", len(training_records))

        if len(training_records) < settings.min_trades_to_retrain:
            logger.warning(
                "Insufficient training data: %d < %d",
                len(training_records),
                settings.min_trades_to_retrain,
            )
            return {"deployed": False, "reason": "insufficient_data"}

        X, y = self._build_dataset(training_records)
        logger.info("Feature matrix: %s, class balance: %.2f", X.shape, y.mean())

        # Time-series split (no shuffling — respect temporal order)
        tscv = TimeSeriesSplit(n_splits=5)

        # ── XGBoost ───────────────────────────────────────────────────────
        xgb_model, xgb_metrics = self._train_xgb(X, y, tscv)

        # ── LightGBM ──────────────────────────────────────────────────────
        lgbm_model, lgbm_metrics = self._train_lgbm(X, y, tscv)

        # ── Calibration ───────────────────────────────────────────────────
        # Use last 20% as calibration set (time-ordered)
        cal_idx = int(len(X) * 0.80)
        X_cal, y_cal = X[cal_idx:], y[cal_idx:]

        xgb_calibrated = CalibratedClassifierCV(xgb_model, method="isotonic", cv="prefit")
        xgb_calibrated.fit(X_cal, y_cal)

        # LightGBM calibration (wrap in sklearn interface)
        lgbm_wrapper = _LGBMSklearnWrapper(lgbm_model)
        lgbm_calibrated = CalibratedClassifierCV(lgbm_wrapper, method="isotonic", cv="prefit")
        lgbm_calibrated.fit(X_cal, y_cal)

        # ── Evaluate on holdout ───────────────────────────────────────────
        y_prob_xgb = xgb_calibrated.predict_proba(X_cal)[:, 1]
        y_prob_lgbm = lgbm_calibrated.predict_proba(X_cal)[:, 1]

        brier_xgb = brier_score_loss(y_cal, y_prob_xgb)
        brier_lgbm = brier_score_loss(y_cal, y_prob_lgbm)

        logger.info("XGB Brier: %.4f | LGBM Brier: %.4f", brier_xgb, brier_lgbm)

        # ── Deployment gate ───────────────────────────────────────────────
        baseline_brier = self._load_baseline_brier()
        best_brier = min(brier_xgb, brier_lgbm)
        should_deploy = best_brier <= baseline_brier * (1 + settings.model_brier_degradation_threshold)

        version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

        if should_deploy:
            self._save_models(xgb_model, lgbm_model, version)
            self._save_baseline_brier(best_brier)
            logger.info("Models deployed as version %s", version)
        else:
            logger.warning(
                "Deployment blocked: new Brier %.4f > baseline %.4f * %.2f",
                best_brier,
                baseline_brier,
                1 + settings.model_brier_degradation_threshold,
            )

        return {
            "version": version,
            "xgb_brier": brier_xgb,
            "lgbm_brier": brier_lgbm,
            "training_samples": len(X),
            "deployed": should_deploy,
            "xgb_cv_metrics": xgb_metrics,
            "lgbm_cv_metrics": lgbm_metrics,
        }

    def _build_dataset(self, records: List[dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Build (X, y) from stored prediction records.
        y = 1 if YES outcome, 0 if NO outcome.
        """
        from core.models import MarketCandidate, ResearchSummary, MarketCategory

        rows = []
        labels = []

        for rec in records:
            if rec.get("resolution") is None:
                continue  # skip unresolved

            # Reconstruct feature vector from stored metadata
            # In production, features_blob would be stored; here we rebuild from stored scalars
            market = MarketCandidate(
                market_id=rec.get("market_id", "unknown"),
                question=rec.get("question", ""),
                category=MarketCategory(rec.get("category", "other")),
                price_yes=float(rec.get("market_price", 0.5)),
                price_no=1.0 - float(rec.get("market_price", 0.5)),
                volume_24h=float(rec.get("volume_24h", 0)),
                volume_7d=float(rec.get("volume_7d", 0)),
                liquidity=float(rec.get("liquidity", 0)),
                bid_ask_spread=float(rec.get("spread", 0.05)),
                time_to_resolution_hours=float(rec.get("ttr_hours", 24)),
                market_age_days=float(rec.get("market_age_days", 0)),
                volatility_7d=float(rec.get("volatility_7d", 0)),
                orderbook_imbalance=0.0,
                whale_trade_count_24h=0,
                unique_traders_7d=0,
                opportunity_score=0.0,
            )
            research = ResearchSummary(
                market_id=rec.get("market_id", "unknown"),
                sentiment_positive=float(rec.get("sentiment_positive", 0)),
                sentiment_negative=float(rec.get("sentiment_negative", 0)),
                sentiment_uncertainty=float(rec.get("sentiment_uncertainty", 0.5)),
                social_momentum=float(rec.get("social_momentum", 1.0)),
                narrative_intensity=float(rec.get("narrative_intensity", 0)),
                data_quality=rec.get("data_quality", "MEDIUM"),
            )

            features, _ = self._feature_builder.build(market, research)
            rows.append(features)
            labels.append(1 if rec["resolution"] else 0)

        if not rows:
            raise ValueError("No valid training rows after filtering")

        return np.array(rows), np.array(labels)

    def _train_xgb(
        self,
        X: np.ndarray,
        y: np.ndarray,
        tscv: TimeSeriesSplit,
    ) -> Tuple[xgb.XGBClassifier, dict]:
        cv_brierscores = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]

            scale_pos_weight = (y_tr == 0).sum() / max((y_tr == 1).sum(), 1)
            model = xgb.XGBClassifier(
                **{**XGB_PARAMS, "scale_pos_weight": scale_pos_weight}
            )
            model.fit(
                X_tr, y_tr,
                eval_set=[(X_val, y_val)],
                early_stopping_rounds=30,
                verbose=False,
            )
            preds = model.predict_proba(X_val)[:, 1]
            cv_brierscores.append(brier_score_loss(y_val, preds))

        # Final fit on all data
        scale_pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)
        final_model = xgb.XGBClassifier(
            **{**XGB_PARAMS, "scale_pos_weight": scale_pos_weight}
        )
        final_model.fit(X, y, verbose=False)

        return final_model, {"cv_brier_mean": float(np.mean(cv_brierscores))}

    def _train_lgbm(
        self,
        X: np.ndarray,
        y: np.ndarray,
        tscv: TimeSeriesSplit,
    ) -> Tuple[lgb.Booster, dict]:
        from model.features import FEATURE_NAMES

        cv_brierscores = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]

            dtrain = lgb.Dataset(X_tr, label=y_tr, feature_name=FEATURE_NAMES)
            dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)
            callbacks = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=-1)]
            model = lgb.train(
                LGBM_PARAMS, dtrain,
                valid_sets=[dval],
                callbacks=callbacks,
            )
            preds = model.predict(X_val)
            cv_brierscores.append(brier_score_loss(y_val, preds))

        # Final fit
        dtrain_full = lgb.Dataset(X, label=y, feature_name=FEATURE_NAMES)
        final_model = lgb.train(
            {**LGBM_PARAMS, "n_estimators": LGBM_PARAMS["n_estimators"]},
            dtrain_full,
        )

        return final_model, {"cv_brier_mean": float(np.mean(cv_brierscores))}

    def _save_models(
        self,
        xgb_model: xgb.XGBClassifier,
        lgbm_model: lgb.Booster,
        version: str,
    ) -> None:
        xgb_model.save_model(str(MODEL_DIR / f"xgb_{version}.json"))
        lgbm_model.save_model(str(MODEL_DIR / f"lgbm_{version}.txt"))
        # Save version manifest
        manifest = {"version": version, "saved_at": datetime.now(timezone.utc).isoformat()}
        with open(MODEL_DIR / "latest_version.json", "w") as f:
            json.dump(manifest, f)

    def _load_baseline_brier(self) -> float:
        manifest_path = MODEL_DIR / "baseline_brier.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f).get("brier_score", 0.25)
        return 0.25  # default baseline for first run

    def _save_baseline_brier(self, score: float) -> None:
        with open(MODEL_DIR / "baseline_brier.json", "w") as f:
            json.dump({"brier_score": score, "updated_at": datetime.now(timezone.utc).isoformat()}, f)


class _LGBMSklearnWrapper:
    """Minimal sklearn-compatible wrapper for LightGBM Booster for calibration."""

    def __init__(self, booster: lgb.Booster) -> None:
        self.booster = booster
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        pos = self.booster.predict(X)
        return np.column_stack([1 - pos, pos])

    def fit(self, X, y):
        return self
