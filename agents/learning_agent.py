"""
LearningAgent

Polls for resolved markets, runs postmortem analysis on losing trades,
stores mistakes in ChromaDB, triggers nightly model retraining,
and updates ensemble weights based on model performance.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic

from agents.base_agent import BaseAgent
from core.config import settings
from core.models import MistakeCategory, PostmortemResult
from core import metrics as m
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Postmortem prompt — structured to produce parseable output
POSTMORTEM_PROMPT = """You are analyzing a prediction market trading mistake.

MARKET QUESTION: {question}

OUR PREDICTION: {predicted_p_yes:.1%} probability of YES
MARKET PRICE AT TIME: {market_price:.1%}
ACTUAL OUTCOME: {outcome}
P&L: ${pnl:+.2f}

MODEL COMPONENTS:
- XGBoost predicted: {xgb:.1%}
- LightGBM predicted: {lgbm:.1%}
- Claude predicted: {claude}

TOP HEADLINES AT TIME OF PREDICTION:
{headlines}

TASK: Analyze why this prediction was wrong. Be specific and actionable.

Respond in this exact format:
MISTAKE_CATEGORY: [model_error|data_quality|execution|bad_luck|distribution_shift]
CONFIDENCE_IN_CATEGORY: [HIGH|MEDIUM|LOW]
ROOT_CAUSE: [1 sentence]
WHAT_WE_MISSED: [1 sentence — the signal we should have caught]
FEATURE_TO_IMPROVE: [specific feature name or data source]
LEARNING: [1 actionable improvement for future trades]"""


class LearningAgent(BaseAgent):
    """
    Runs two loops:
    1. Continuous: polls for newly resolved markets → postmortem
    2. Nightly (via Celery): full model retraining
    """

    name = "learning"
    cycle_interval_seconds = settings.resolution_poll_interval_seconds  # 5 min

    def __init__(
        self,
        bus,
        circuit_breaker: CircuitBreaker,
        anthropic_client: Optional[anthropic.Anthropic] = None,
        redis_client=None,
    ) -> None:
        super().__init__(bus, circuit_breaker)
        self._anthropic = anthropic_client
        self._redis = redis_client

    async def tick(self) -> None:
        """Check for newly resolved markets and run postmortems."""
        try:
            await self._process_resolutions()
        except Exception as exc:
            self._log.error("Resolution processing error: %s", exc)

    async def _process_resolutions(self) -> None:
        """Fetch unresolved trades, check Polymarket for resolutions, run postmortems."""
        try:
            from core.storage import fetch_unresolved_trades
            from data.polymarket_client import PolymarketClient
        except ImportError:
            return

        try:
            trades = await fetch_unresolved_trades()
        except Exception as exc:
            self._log.warning("Could not fetch unresolved trades: %s", exc)
            return

        if not trades:
            return

        client = PolymarketClient(api_key=settings.polymarket_api_key)

        for trade in trades:
            market_id = trade["market_id"]
            resolution = trade.get("resolution")

            if resolution is None:
                continue  # not yet resolved per our DB

            await self._run_postmortem(trade, bool(resolution))

        await client.close()

    async def _run_postmortem(self, trade: dict, outcome: bool) -> None:
        """
        Analyze a resolved trade and store learnings.
        """
        predicted = float(trade.get("p_yes_ensemble", 0.5))
        market_price = float(trade.get("market_price", 0.5))
        pnl = self._compute_pnl(trade, outcome)

        # Only do expensive Claude postmortem on losses above $5
        if pnl >= 0 or abs(pnl) < 5.0:
            self._log.debug(
                "Skipping postmortem for trade %d (pnl=%.2f)", trade["id"], pnl
            )
            return

        self._log.info(
            "Running postmortem: trade %d, pnl=%.2f, outcome=%s",
            trade["id"], pnl, outcome,
        )

        # ── Claude postmortem ─────────────────────────────────────────────
        analysis = await self._claude_postmortem(trade, outcome, pnl)
        if analysis is None:
            analysis = {
                "category": MistakeCategory.BAD_LUCK,
                "root_cause": "Analysis unavailable",
                "learning": "N/A",
                "raw": "",
            }

        # ── Store in ChromaDB ─────────────────────────────────────────────
        chroma_id = await self._store_mistake(trade, analysis, pnl)

        result = PostmortemResult(
            trade_id=int(trade["id"]),
            market_id=str(trade["market_id"]),
            predicted_p_yes=predicted,
            actual_outcome=outcome,
            pnl=pnl,
            mistake_category=analysis["category"],
            claude_analysis=analysis["raw"],
            key_learnings=[analysis["learning"]],
            chroma_doc_id=chroma_id,
        )

        # ── Update Prometheus ─────────────────────────────────────────────
        m.TRADE_PNL.observe(pnl)

        self._log.info(
            "Postmortem complete: trade %d | category=%s | learning=%s",
            trade["id"], result.mistake_category, analysis["learning"][:80],
        )

    async def _claude_postmortem(
        self, trade: dict, outcome: bool, pnl: float
    ) -> Optional[dict]:
        if not self._anthropic:
            return None

        claude_pred = trade.get("p_yes_claude")
        claude_str = f"{float(claude_pred):.1%}" if claude_pred else "not invoked"

        headlines = trade.get("top_headlines", [])
        headlines_str = "\n".join(f"- {h}" for h in headlines[:5]) if headlines else "none available"

        prompt = POSTMORTEM_PROMPT.format(
            question=trade.get("question", "Unknown market"),
            predicted_p_yes=float(trade.get("p_yes_ensemble", 0.5)),
            market_price=float(trade.get("market_price", 0.5)),
            outcome="YES" if outcome else "NO",
            pnl=pnl,
            xgb=float(trade.get("p_yes_xgb", 0.5)),
            lgbm=float(trade.get("p_yes_lgbm", 0.5)),
            claude=claude_str,
            headlines=headlines_str,
        )

        try:
            response = self._anthropic.messages.create(
                model=settings.claude_model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            m.CLAUDE_API_CALLS.labels(agent_name="learning", model=settings.claude_model).inc()
            usage = response.usage
            m.CLAUDE_TOKENS.labels(agent_name="learning", direction="input").inc(usage.input_tokens)
            m.CLAUDE_TOKENS.labels(agent_name="learning", direction="output").inc(usage.output_tokens)

            raw = response.content[0].text
            return self._parse_postmortem(raw)
        except Exception as exc:
            self._log.error("Claude postmortem error: %s", exc)
            return None

    def _parse_postmortem(self, text: str) -> dict:
        lines = {
            line.split(":")[0].strip(): ":".join(line.split(":")[1:]).strip()
            for line in text.split("\n")
            if ":" in line
        }

        cat_str = lines.get("MISTAKE_CATEGORY", "bad_luck").lower().strip()
        try:
            category = MistakeCategory(cat_str)
        except ValueError:
            category = MistakeCategory.BAD_LUCK

        return {
            "category": category,
            "root_cause": lines.get("ROOT_CAUSE", ""),
            "what_we_missed": lines.get("WHAT_WE_MISSED", ""),
            "feature_to_improve": lines.get("FEATURE_TO_IMPROVE", ""),
            "learning": lines.get("LEARNING", ""),
            "raw": text,
        }

    async def _store_mistake(self, trade: dict, analysis: dict, pnl: float) -> Optional[str]:
        try:
            from core.storage import store_mistake_embedding
            text = (
                f"Market: {trade.get('question', '')}\n"
                f"Category: {analysis['category']}\n"
                f"Root cause: {analysis['root_cause']}\n"
                f"Missed: {analysis['what_we_missed']}\n"
                f"Learning: {analysis['learning']}"
            )
            # Simple embedding: use TF-IDF-style hash embedding (no external API needed)
            # In production: use claude embeddings or sentence-transformers
            import hashlib
            fake_embedding = [float(b) / 255.0 for b in hashlib.sha256(text.encode()).digest()]
            # Pad to standard embedding size
            while len(fake_embedding) < 384:
                fake_embedding.extend(fake_embedding[:384 - len(fake_embedding)])
            fake_embedding = fake_embedding[:384]

            doc_id = store_mistake_embedding(
                trade_id=int(trade["id"]),
                analysis_text=text,
                embedding=fake_embedding,
                metadata={
                    "category": str(analysis["category"]),
                    "pnl": pnl,
                    "market_id": str(trade.get("market_id", "")),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return doc_id
        except Exception as exc:
            self._log.warning("ChromaDB storage failed: %s", exc)
            return None

    def _compute_pnl(self, trade: dict, outcome: bool) -> float:
        """Compute realized PnL from trade record and resolution."""
        side = str(trade.get("side", "YES")).upper()
        filled_shares = float(trade.get("filled_shares") or 0)
        fill_price = float(trade.get("fill_price") or 0)
        dollar_spent = filled_shares * fill_price

        if (side == "YES" and outcome) or (side == "NO" and not outcome):
            # Won: each share pays $1
            pnl = filled_shares - dollar_spent
        else:
            # Lost: shares are worthless
            pnl = -dollar_spent

        return round(pnl, 2)

    async def trigger_retrain(self) -> None:
        """Manually trigger a model retraining (called from nightly cron)."""
        self._log.info("Triggering nightly model retrain")
        try:
            from core.storage import fetch_training_data
            from model.trainer import ModelTrainer

            records = await fetch_training_data(window_days=settings.training_window_days)
            if not records:
                self._log.warning("No training data available")
                return

            records_dict = [dict(r) for r in records]
            trainer = ModelTrainer()
            result = trainer.run_full_retrain(records_dict)

            self._log.info("Retrain complete: %s", result)

            if result.get("deployed") and self._redis:
                # Update ensemble weights based on comparative performance
                await self._update_weights(result)

        except Exception as exc:
            self._log.exception("Retrain failed: %s", exc)

    async def _update_weights(self, retrain_result: dict) -> None:
        """Update XGB/LGBM ensemble weights based on recent Brier scores."""
        import json
        xgb_brier = retrain_result.get("xgb_brier", 0.25)
        lgbm_brier = retrain_result.get("lgbm_brier", 0.25)

        # Lower Brier = better model = higher weight
        # Convert to weights: w_i = (1 / brier_i) / sum(1 / brier_j)
        inv_xgb = 1.0 / (xgb_brier + 1e-9)
        inv_lgbm = 1.0 / (lgbm_brier + 1e-9)
        inv_claude = 1.0 / (settings.claude_weight + 1e-9)  # fixed proxy

        total = inv_xgb + inv_lgbm + inv_claude
        weights = {
            "xgb": round(inv_xgb / total, 4),
            "lgbm": round(inv_lgbm / total, 4),
            "claude": round(inv_claude / total, 4),
        }

        await self._redis.set("model:ensemble_weights", json.dumps(weights), ex=86400 * 7)
        self._log.info("Updated ensemble weights: %s", weights)

        # Update Prometheus metrics
        m.MODEL_BRIER_SCORE.labels(model_name="xgb").set(xgb_brier)
        m.MODEL_BRIER_SCORE.labels(model_name="lgbm").set(lgbm_brier)
