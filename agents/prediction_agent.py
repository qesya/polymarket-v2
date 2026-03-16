"""
PredictionAgent

Consumes (MarketCandidate, ResearchSummary) pairs.
Builds feature vectors, runs ML ensemble, optionally invokes Claude,
computes edge, and publishes PredictionResult.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Tuple

from agents.base_agent import BaseAgent
from core.bus import CHANNEL_RESEARCH_JOBS, CHANNEL_PREDICTIONS_READY
from core.config import settings
from core.models import (
    MarketCandidate, ResearchSummary, PredictionResult, ModelPredictions
)
from core import metrics as m
from core.circuit_breaker import CircuitBreaker
from model.features import FeatureBuilder
from model.ensemble import ModelEnsemble
from sentiment.analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class PredictionAgent(BaseAgent):
    """
    Reactive agent: triggered by ResearchSummary arriving on bus.
    Maintains an in-memory cache of MarketCandidates for joining.
    """

    name = "prediction"
    cycle_interval_seconds = 999999  # message-driven

    def __init__(
        self,
        bus,
        circuit_breaker: CircuitBreaker,
        anthropic_client=None,
        redis_client=None,
    ) -> None:
        super().__init__(bus, circuit_breaker)
        self._feature_builder = FeatureBuilder()
        self._ensemble = ModelEnsemble(redis_client=redis_client)
        self._sentiment = SentimentAnalyzer(anthropic_client=anthropic_client)
        self._anthropic = anthropic_client
        self._redis = redis_client

        # Cache market candidates by market_id (populated from bus subscription)
        self._market_cache: Dict[str, MarketCandidate] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        # Load models at startup
        try:
            self._ensemble.load()
        except Exception as exc:
            logger.warning("Model load failed (will use fallback 0.5): %s", exc)

    async def tick(self) -> None:
        """Drain one research summary from queue and generate prediction."""
        try:
            research: ResearchSummary = await asyncio.wait_for(
                self._queue.get(), timeout=5.0
            )
        except asyncio.TimeoutError:
            return

        market = self._market_cache.get(research.market_id)
        if market is None:
            self._log.warning(
                "No cached market for %s — skipping prediction", research.market_id
            )
            self._queue.task_done()
            return

        if await self.check_circuit("model"):
            self._queue.task_done()
            return

        try:
            result = await self._predict(market, research)
            if result:
                await self.publish(CHANNEL_PREDICTIONS_READY, result)
                m.PREDICTIONS_TOTAL.labels(
                    model_name="ensemble",
                    traded=str(result.should_trade),
                ).inc()
        except Exception as exc:
            self._log.exception("Prediction error for %s: %s", research.market_id, exc)
        finally:
            self._queue.task_done()

    def cache_market(self, candidate: MarketCandidate) -> None:
        """Store market candidate for later join with research summary."""
        self._market_cache[candidate.market_id] = candidate
        # Evict oldest entries if cache grows too large
        if len(self._market_cache) > 500:
            oldest_key = next(iter(self._market_cache))
            del self._market_cache[oldest_key]

    async def enqueue(self, research: ResearchSummary) -> None:
        try:
            self._queue.put_nowait(research)
        except asyncio.QueueFull:
            self._log.warning("Prediction queue full — dropping %s", research.market_id)

    async def _predict(
        self,
        market: MarketCandidate,
        research: ResearchSummary,
    ) -> Optional[PredictionResult]:
        """Core prediction logic."""

        # ── Portfolio context (optional enrichment) ───────────────────────
        portfolio_ctx = await self._get_portfolio_context()

        # ── Build features ────────────────────────────────────────────────
        features, feature_hash = self._feature_builder.build(market, research, portfolio_ctx)

        # ── ML ensemble prediction ────────────────────────────────────────
        xgb_prob, lgbm_prob, ml_ensemble, ml_confidence = self._ensemble.predict(features)

        # ── Claude augmentation (conditional) ────────────────────────────
        claude_prob: Optional[float] = None
        final_prob = ml_ensemble
        confidence = ml_confidence

        disagreement = abs(xgb_prob - lgbm_prob)
        if disagreement > settings.claude_disagreement_threshold and self._anthropic:
            claude_result = await self._sentiment.analyze_with_claude(
                question=market.question,
                texts=research.top_headlines,
                market_price=market.price_yes,
            )
            if claude_result:
                claude_prob, _ = claude_result
                final_prob, confidence = self._ensemble.predict_with_claude(features, claude_prob)

        # ── Apply probability clipping ────────────────────────────────────
        final_prob = max(settings.probability_clip_low, min(settings.probability_clip_high, final_prob))

        # ── Edge calculation ──────────────────────────────────────────────
        edge = final_prob - market.price_yes

        # Adjust edge for transaction cost estimate (bid/ask spread / 2)
        cost_estimate = market.bid_ask_spread / 2.0
        adjusted_edge = edge - cost_estimate

        should_trade = (
            abs(adjusted_edge) >= settings.min_edge_threshold
            and confidence >= settings.min_confidence_threshold
            and research.data_quality != "LOW"
        )

        # ── Ensemble weights used ─────────────────────────────────────────
        if claude_prob is not None:
            total_w = settings.xgb_weight + settings.lgbm_weight + settings.claude_weight
            xgb_w = settings.xgb_weight / total_w
            lgbm_w = settings.lgbm_weight / total_w
            claude_w = settings.claude_weight / total_w
        else:
            claude_w = 0.0
            total_w = settings.xgb_weight + settings.lgbm_weight
            xgb_w = settings.xgb_weight / total_w
            lgbm_w = settings.lgbm_weight / total_w

        return PredictionResult(
            market_id=market.market_id,
            market_price_yes=market.price_yes,
            model_predictions=ModelPredictions(
                xgb_p_yes=xgb_prob,
                lgbm_p_yes=lgbm_prob,
                claude_p_yes=claude_prob,
                ensemble_p_yes=final_prob,
                xgb_weight=xgb_w,
                lgbm_weight=lgbm_w,
                claude_weight=claude_w,
            ),
            predicted_p_yes=final_prob,
            edge=adjusted_edge,
            confidence=confidence,
            feature_vector_hash=feature_hash,
            model_version=self._ensemble.model_version,
            should_trade=should_trade,
        )

    async def _get_portfolio_context(self) -> dict:
        if not self._redis:
            return {}
        try:
            from core.storage import get_portfolio_state
            state = await get_portfolio_state()
            if state:
                return {
                    "portfolio_exposure_pct": 1.0 - (state.cash_available / (state.total_value + 1e-9)),
                    "portfolio_drawdown_pct": state.current_drawdown_pct,
                    "portfolio_open_positions": state.open_position_count,
                }
        except Exception:
            pass
        return {}
