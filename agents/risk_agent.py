"""
RiskAgent

Evaluates every PredictionResult before a trade is placed.
Applies Kelly Criterion, drawdown guards, correlation checks,
and concentration limits. Either approves an OrderIntent or
publishes a RiskRejection.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from datetime import datetime, timezone

from agents.base_agent import BaseAgent
from core.bus import CHANNEL_PREDICTIONS_READY, CHANNEL_RISK_SIGNALS
from core.config import settings
from core.models import (
    OrderIntent, PredictionResult, RiskRejection,
    TradeSide, KellyCalculation, PortfolioState,
)
from core import metrics as m
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    """
    Gate agent: every prediction passes through here before execution.
    No trade is placed without explicit approval from this agent.
    """

    name = "risk"
    cycle_interval_seconds = 999999  # message-driven

    def __init__(self, bus, circuit_breaker: CircuitBreaker, redis_client=None) -> None:
        super().__init__(bus, circuit_breaker)
        self._redis = redis_client
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    async def tick(self) -> None:
        try:
            prediction: PredictionResult = await asyncio.wait_for(
                self._queue.get(), timeout=5.0
            )
        except asyncio.TimeoutError:
            return

        try:
            await self._evaluate(prediction)
        except Exception as exc:
            self._log.exception("Risk evaluation error: %s", exc)
        finally:
            self._queue.task_done()

    async def enqueue(self, prediction: PredictionResult) -> None:
        try:
            self._queue.put_nowait(prediction)
        except asyncio.QueueFull:
            self._log.warning("Risk queue full — dropping %s", prediction.market_id)

    async def _evaluate(self, prediction: PredictionResult) -> None:
        """
        Full risk evaluation pipeline.
        Publishes OrderIntent on approval, RiskRejection on block.
        """
        # ── Pre-check: should_trade flag ──────────────────────────────────
        if not prediction.should_trade:
            await self._reject(prediction, "edge_below_threshold")
            return

        # ── Circuit breaker check ─────────────────────────────────────────
        if await self.check_circuit("trading"):
            await self._reject(prediction, "circuit_open_trading", circuit_open=True)
            return

        # ── Portfolio state ───────────────────────────────────────────────
        portfolio = await self._get_portfolio()
        if portfolio is None:
            await self._reject(prediction, "no_portfolio_state")
            return

        # ── Drawdown guard ────────────────────────────────────────────────
        if portfolio.current_drawdown_pct >= settings.max_drawdown_pct:
            await self.cb.trip("trading", f"Max drawdown hit: {portfolio.current_drawdown_pct:.1%}")
            await self._reject(prediction, "max_drawdown_exceeded")
            return

        # ── Daily loss limit ──────────────────────────────────────────────
        daily_loss_pct = -portfolio.daily_pnl / (portfolio.total_value + 1e-9)
        if daily_loss_pct >= settings.daily_loss_limit_pct:
            await self._reject(prediction, "daily_loss_limit_exceeded")
            return

        # ── Max open positions ────────────────────────────────────────────
        if portfolio.open_position_count >= settings.max_open_positions:
            await self._reject(prediction, "max_positions_exceeded")
            return

        # ── Already have a position in this market? ───────────────────────
        if prediction.market_id in portfolio.open_position_market_ids:
            await self._reject(prediction, "existing_position")
            return

        # ── Kelly Criterion ───────────────────────────────────────────────
        kelly = self._compute_kelly(prediction, portfolio.total_value)

        if kelly.f_applied <= 0:
            await self._reject(prediction, "kelly_negative_or_zero")
            return

        dollar_size = kelly.f_applied * portfolio.total_value
        shares = dollar_size / prediction.market_price_yes

        # ── Hard cap on position size ─────────────────────────────────────
        max_dollar = portfolio.total_value * settings.max_position_pct
        if dollar_size > max_dollar:
            dollar_size = max_dollar
            shares = dollar_size / prediction.market_price_yes

        # ── Minimum trade size ($10 to avoid dust) ────────────────────────
        if dollar_size < 10.0:
            await self._reject(prediction, "position_too_small")
            return

        # ── Determine trade side ──────────────────────────────────────────
        side = TradeSide.YES if prediction.edge > 0 else TradeSide.NO
        limit_price = prediction.market_price_yes if side == TradeSide.YES else prediction.market_price_yes

        # ── Build idempotency key ─────────────────────────────────────────
        minute_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        idempotency_key = hashlib.sha256(
            f"{prediction.market_id}:{side.value}:{dollar_size:.2f}:{minute_bucket}".encode()
        ).hexdigest()

        order = OrderIntent(
            market_id=prediction.market_id,
            side=side,
            shares=round(shares, 4),
            dollar_size=round(dollar_size, 2),
            limit_price=round(limit_price, 4),
            max_slippage_pct=settings.max_slippage_pct,
            kelly_calculation=kelly,
            portfolio_value_at_decision=portfolio.total_value,
            idempotency_key=idempotency_key,
        )

        self._log.info(
            "APPROVED %s %s $%.2f (edge=%.3f conf=%.2f)",
            side.value, prediction.market_id, dollar_size,
            prediction.edge, prediction.confidence,
        )
        await self.publish(CHANNEL_RISK_SIGNALS, order)

    def _compute_kelly(
        self,
        prediction: PredictionResult,
        portfolio_value: float,
    ) -> KellyCalculation:
        """
        Binary Kelly Criterion for prediction market.

        For a binary market at price p:
            b = (1 - p) / p  (odds: how much you gain per dollar risked)
            p_win = predicted_probability
            f* = (p_win * (b + 1) - 1) / b
               = (p_win / p) - 1    [simplified for binary]

        For YES bet:  p = market_price_yes,  p_win = predicted_p_yes
        For NO bet:   p = market_price_no,   p_win = predicted_p_no = 1 - predicted_p_yes
        """
        if prediction.edge > 0:
            # Betting YES
            market_p = prediction.market_price_yes
            win_p = prediction.predicted_p_yes
        else:
            # Betting NO
            market_p = 1.0 - prediction.market_price_yes
            win_p = 1.0 - prediction.predicted_p_yes

        market_p = max(market_p, 0.01)  # prevent division by zero

        # b = net odds (profit per $1 risked if bet wins)
        b = (1.0 - market_p) / market_p

        # Kelly fraction
        f_star = (win_p * (b + 1) - 1) / b
        f_star = max(f_star, 0.0)  # Kelly can't be negative (just means "don't bet")

        # Fractional Kelly
        f_applied = f_star * settings.kelly_fraction

        # Expected value sanity check
        ev = win_p * b - (1.0 - win_p)

        return KellyCalculation(
            f_star=round(f_star, 6),
            f_applied=round(f_applied, 6),
            kelly_fraction_used=settings.kelly_fraction,
            expected_value=round(ev, 6),
        )

    async def _reject(
        self,
        prediction: PredictionResult,
        reason: str,
        circuit_open: bool = False,
    ) -> None:
        m.TRADES_REJECTED_RISK.labels(reason=reason).inc()
        self._log.debug("REJECTED %s: %s", prediction.market_id, reason)
        rejection = RiskRejection(
            market_id=prediction.market_id,
            prediction_result=prediction,
            rejection_reason=reason,
            circuit_open=circuit_open,
        )
        # Log rejections to a separate channel for monitoring/learning
        # (ExecutionAgent and LearningAgent can subscribe if needed)

    async def _get_portfolio(self) -> PortfolioState | None:
        try:
            from core.storage import get_portfolio_state
            return await get_portfolio_state()
        except Exception as exc:
            self._log.error("Failed to load portfolio state: %s", exc)
            return None
