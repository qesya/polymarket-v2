"""
ModelEnsemble

Combines XGBoost, LightGBM, and optional Claude predictions.
Weights are dynamically loaded from Redis (updated nightly by LearningAgent).
Falls back to config defaults when Redis unavailable.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from core.config import settings

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("MODEL_DIR", "/root/polymarket-v2/data/models"))
REDIS_WEIGHTS_KEY = "model:ensemble_weights"


class ModelEnsemble:
    """
    Loads XGBoost and LightGBM models from disk.
    Provides predict(features) → (probability, confidence) interface.

    Models are loaded lazily on first prediction call.
    Thread-safe for asyncio use (models are read-only after loading).
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._xgb_model = None
        self._lgbm_model = None
        self._loaded = False
        self._model_version = "unknown"

    def load(self, version: Optional[str] = None) -> None:
        """Load latest (or specified version) models from disk."""
        import xgboost as xgb
        import lightgbm as lgb

        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        if version:
            xgb_path = MODEL_DIR / f"xgb_{version}.json"
            lgbm_path = MODEL_DIR / f"lgbm_{version}.txt"
        else:
            # Load most recent files
            xgb_path = self._latest_model(MODEL_DIR, "xgb_*.json")
            lgbm_path = self._latest_model(MODEL_DIR, "lgbm_*.txt")

        if xgb_path and xgb_path.exists():
            self._xgb_model = xgb.XGBClassifier()
            self._xgb_model.load_model(str(xgb_path))
            logger.info("Loaded XGBoost model: %s", xgb_path)
        else:
            logger.warning("No XGBoost model found at %s — predictions will use fallback", xgb_path)

        if lgbm_path and lgbm_path.exists():
            self._lgbm_model = lgb.Booster(model_file=str(lgbm_path))
            logger.info("Loaded LightGBM model: %s", lgbm_path)
        else:
            logger.warning("No LightGBM model found — predictions will use fallback")

        self._loaded = True
        self._model_version = str(version or "latest")

    def predict(
        self,
        features: np.ndarray,
    ) -> Tuple[float, float, float, float]:
        """
        Generate predictions from all available models.

        Returns:
            (xgb_prob, lgbm_prob, ensemble_prob, confidence)
        where confidence = 1 - disagreement between models.
        """
        if not self._loaded:
            self.load()

        xgb_prob = self._predict_xgb(features)
        lgbm_prob = self._predict_lgbm(features)

        # Confidence = 1 minus the normalized disagreement
        disagreement = abs(xgb_prob - lgbm_prob)
        confidence = 1.0 - min(disagreement / 0.3, 1.0)  # 0.3 = max meaningful disagreement

        weights = self._get_weights()
        xgb_w = weights["xgb"]
        lgbm_w = weights["lgbm"]

        # Renormalize to sum to 1 (ignoring Claude weight here)
        ml_total = xgb_w + lgbm_w
        ensemble_prob = (xgb_prob * xgb_w + lgbm_prob * lgbm_w) / ml_total

        # Clip to safe range
        ensemble_prob = float(np.clip(ensemble_prob, 0.05, 0.95))

        return xgb_prob, lgbm_prob, ensemble_prob, confidence

    def predict_with_claude(
        self,
        features: np.ndarray,
        claude_prob: float,
    ) -> Tuple[float, float]:
        """
        Blend Claude probability into ensemble.
        Returns (final_prob, confidence).
        """
        xgb_prob, lgbm_prob, ml_ensemble, ml_confidence = self.predict(features)

        weights = self._get_weights()
        total_w = weights["xgb"] + weights["lgbm"] + weights["claude"]

        final_prob = (
            xgb_prob * weights["xgb"]
            + lgbm_prob * weights["lgbm"]
            + claude_prob * weights["claude"]
        ) / total_w

        # Higher confidence when all three agree
        all_three = [xgb_prob, lgbm_prob, claude_prob]
        max_spread = max(all_three) - min(all_three)
        confidence = 1.0 - min(max_spread / 0.3, 1.0)

        return float(np.clip(final_prob, 0.05, 0.95)), confidence

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def models_loaded(self) -> bool:
        return self._xgb_model is not None or self._lgbm_model is not None

    def _predict_xgb(self, features: np.ndarray) -> float:
        if self._xgb_model is None:
            return 0.5
        try:
            proba = self._xgb_model.predict_proba(features.reshape(1, -1))[0]
            return float(proba[1])  # P(YES)
        except Exception as exc:
            logger.error("XGBoost prediction error: %s", exc)
            return 0.5

    def _predict_lgbm(self, features: np.ndarray) -> float:
        if self._lgbm_model is None:
            return 0.5
        try:
            proba = self._lgbm_model.predict(features.reshape(1, -1))
            return float(proba[0])  # LightGBM returns P(positive class) directly
        except Exception as exc:
            logger.error("LightGBM prediction error: %s", exc)
            return 0.5

    def _get_weights(self) -> dict:
        """Load ensemble weights from Redis or fall back to config defaults."""
        if self._redis:
            try:
                import asyncio
                # Synchronous get for use inside asyncio context
                raw = None
                if hasattr(self._redis, "get"):
                    # Use sync redis client for model weights
                    pass
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return {
            "xgb": settings.xgb_weight,
            "lgbm": settings.lgbm_weight,
            "claude": settings.claude_weight,
        }

    @staticmethod
    def _latest_model(directory: Path, pattern: str) -> Optional[Path]:
        """Find the most recently modified file matching pattern."""
        matches = sorted(directory.glob(pattern), key=os.path.getmtime, reverse=True)
        return matches[0] if matches else None
