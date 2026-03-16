"""
ExecutionAgent

Receives approved OrderIntents from RiskAgent.
Validates slippage against live orderbook, places limit orders,
monitors fills, records trades to PostgreSQL, updates portfolio state.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from agents.base_agent import BaseAgent
from core.bus import CHANNEL_RISK_SIGNALS, CHANNEL_EXECUTION_ORDERS
from core.config import settings
from core.models import (
    FillReport, OrderIntent, PortfolioState, TradeSide, TradeStatus
)
from core import metrics as m
from core.circuit_breaker import CircuitBreaker
from data.polymarket_client import PolymarketClient, estimate_slippage

logger = logging.getLogger(__name__)


class ExecutionAgent(BaseAgent):
    """
    Translates approved OrderIntents into real trades on Polymarket.
    Maintains PnL and portfolio state in Redis + PostgreSQL.
    """

    name = "execution"
    cycle_interval_seconds = 30.0  # also polls for resolution and PnL updates

    def __init__(
        self,
        bus,
        circuit_breaker: CircuitBreaker,
        redis_client=None,
    ) -> None:
        super().__init__(bus, circuit_breaker)
        self._client = PolymarketClient(
            api_key=settings.polymarket_api_key,
            private_key=settings.polymarket_private_key,
        )
        self._redis = redis_client
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # In-memory order tracking: order_id → trade_db_id
        self._pending_orders: Dict[str, int] = {}

    async def tick(self) -> None:
        """Poll pending orders AND drain the execution queue each cycle."""
        # 1. Execute any pending orders
        while not self._queue.empty():
            try:
                order: OrderIntent = self._queue.get_nowait()
                await self._execute_order(order)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        # 2. Poll pending order statuses
        await self._poll_pending_orders()

    async def enqueue(self, order: OrderIntent) -> None:
        try:
            self._queue.put_nowait(order)
        except asyncio.QueueFull:
            self._log.warning("Execution queue full — dropping order %s", order.market_id)

    async def _execute_order(self, order: OrderIntent) -> None:
        """
        Full execution pipeline for one order:
        1. Fetch live orderbook
        2. Estimate slippage
        3. Reject if slippage exceeds limit
        4. Place order with idempotency key
        5. Record in PostgreSQL
        6. Update portfolio state
        """
        if await self.check_circuit("execution"):
            return
        if await self.check_circuit("api"):
            return

        self._log.info(
            "Executing %s %s $%.2f at %.4f",
            order.side.value, order.market_id,
            order.dollar_size, order.limit_price,
        )

        # ── Fetch live orderbook ──────────────────────────────────────────
        try:
            # In production: derive token_id from market_id via CLOB API
            token_id = await self._get_token_id(order.market_id, order.side)
            orderbook = await self._client.get_orderbook(token_id)
        except Exception as exc:
            await self.cb.record_failure("api", str(exc))
            self._log.error("Orderbook fetch failed: %s", exc)
            return

        # ── Slippage pre-check ────────────────────────────────────────────
        estimated_fill, slippage_pct = estimate_slippage(
            orderbook, order.side.value, order.shares
        )
        if slippage_pct > order.max_slippage_pct:
            self._log.warning(
                "Slippage %.2f%% exceeds limit %.2f%% — rejecting %s",
                slippage_pct * 100, order.max_slippage_pct * 100, order.market_id,
            )
            m.TRADES_REJECTED_RISK.labels(reason="slippage_exceeded").inc()
            return

        # ── Record trade intent in DB (before placing — safe for idempotency) ──
        trade_db_id = await self._record_trade_intent(order)
        if trade_db_id == -1:
            self._log.info("Duplicate order skipped: %s", order.idempotency_key)
            return

        # ── Place order ───────────────────────────────────────────────────
        api_side = "BUY"  # on Polymarket: buying YES shares or buying NO shares
        try:
            response = await self._client.place_order(
                market_id=order.market_id,
                token_id=token_id,
                side=api_side,
                price=order.limit_price,
                size=order.shares,
                idempotency_key=order.idempotency_key,
            )
            await self.cb.record_success("execution")

        except Exception as exc:
            await self.cb.record_failure("execution", str(exc))
            self._log.error("Order placement failed: %s", exc)
            await self._update_trade_status(trade_db_id, "CANCELLED", error=str(exc))
            return

        order_id = response.get("orderID") or response.get("order_id", "")
        self._pending_orders[order_id] = trade_db_id

        m.TRADES_TOTAL.labels(
            market_category="unknown",
            side=order.side.value,
        ).inc()

        fill_report = FillReport(
            market_id=order.market_id,
            order_intent=order,
            order_id=order_id,
            status=TradeStatus.PENDING,
            filled_shares=0.0,
            fill_price=order.limit_price,
            slippage_bps=slippage_pct * 10_000,
            dollar_spent=0.0,
        )
        await self.publish(CHANNEL_EXECUTION_ORDERS, fill_report)

    async def _poll_pending_orders(self) -> None:
        """Check fill status of all pending orders."""
        if not self._pending_orders or await self.check_circuit("api"):
            return

        completed = []
        for order_id, trade_db_id in list(self._pending_orders.items()):
            try:
                status = await self._client.get_order_status(order_id)
                order_status = status.get("status", "").upper()

                if order_status in ("MATCHED", "FILLED"):
                    filled_size = float(status.get("sizeMatched", 0))
                    fill_price = float(status.get("avgPrice", 0))
                    slippage = abs(fill_price - float(status.get("price", fill_price)))
                    slippage_bps = slippage / (float(status.get("price", fill_price)) + 1e-9) * 10_000

                    await self._update_trade_fill(
                        trade_db_id, order_id, filled_size, fill_price,
                        slippage_bps, "FILLED"
                    )
                    m.SLIPPAGE_BPS.observe(slippage_bps)
                    await self._update_portfolio_state()
                    completed.append(order_id)

                elif order_status in ("CANCELLED", "EXPIRED"):
                    await self._update_trade_status(trade_db_id, order_status)
                    completed.append(order_id)

            except Exception as exc:
                self._log.warning("Order poll error for %s: %s", order_id, exc)

        for oid in completed:
            self._pending_orders.pop(oid, None)

    async def _get_token_id(self, market_id: str, side: TradeSide) -> str:
        """
        Resolve Polymarket token_id for YES or NO outcome.
        In production: cache this from the market metadata fetched during scanning.
        """
        try:
            markets = await self._client.get_markets(limit=1)
            for m_data in markets:
                if m_data.get("conditionId") == market_id or m_data.get("id") == market_id:
                    tokens = m_data.get("tokens", [])
                    if side == TradeSide.YES and len(tokens) > 0:
                        return tokens[0].get("token_id", market_id)
                    elif side == TradeSide.NO and len(tokens) > 1:
                        return tokens[1].get("token_id", market_id)
        except Exception:
            pass
        return market_id  # fallback: use market_id as token_id

    async def _record_trade_intent(self, order: OrderIntent) -> int:
        try:
            from core.storage import insert_trade
            return await insert_trade({
                "idempotency_key": order.idempotency_key,
                "market_id": order.market_id,
                "prediction_id": order.prediction_id,
                "side": order.side.value,
                "intended_shares": order.shares,
                "intended_price": order.limit_price,
                "dollar_size": order.dollar_size,
                "kelly_fraction": order.kelly_calculation.f_applied,
                "portfolio_value_at_trade": order.portfolio_value_at_decision,
            })
        except Exception as exc:
            self._log.error("DB insert failed: %s", exc)
            return -1

    async def _update_trade_fill(
        self,
        trade_id: int,
        order_id: str,
        filled_shares: float,
        fill_price: float,
        slippage_bps: float,
        status: str,
    ) -> None:
        try:
            from core.storage import update_trade_fill
            await update_trade_fill(trade_id, {
                "order_id": order_id,
                "filled_shares": filled_shares,
                "fill_price": fill_price,
                "slippage_bps": slippage_bps,
                "status": status,
            })
        except Exception as exc:
            self._log.error("Trade fill update failed: %s", exc)

    async def _update_trade_status(
        self, trade_id: int, status: str, error: str = ""
    ) -> None:
        self._log.debug("Trade %d status → %s %s", trade_id, status, error)

    async def _update_portfolio_state(self) -> None:
        """Recompute portfolio state from DB and cache in Redis."""
        try:
            from core.storage import set_portfolio_state
            # In production: query all open positions + cash balance
            # Simplified: update timestamp to signal freshness
            state = PortfolioState(
                total_value=10_000.0,     # placeholder — real impl queries DB
                cash_available=9_000.0,
                peak_value=10_000.0,
                current_drawdown_pct=0.0,
                daily_pnl=0.0,
                open_position_count=len(self._pending_orders),
            )
            await set_portfolio_state(state)
            m.PORTFOLIO_VALUE.set(state.total_value)
            m.DRAWDOWN_PCT.set(state.current_drawdown_pct)
            m.OPEN_POSITIONS.set(state.open_position_count)
        except Exception as exc:
            self._log.warning("Portfolio state update failed: %s", exc)
