"""
Bridges Redis pub/sub channels → WebSocket broadcasts.
Also polls Redis key-value state (circuit breakers, portfolio) for change detection.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from api.websocket_manager import WSManager

logger = logging.getLogger(__name__)

# Redis pub/sub channels → WS topics
CHANNEL_MAP = {
    "market.scan":         "market_candidate",
    "predictions.ready":   "prediction_result",
    "risk.signals":        "risk_signal",
    "execution.orders":    "trade_filled",
    "learning.events":     "learning_event",
    "circuit.breaker":     "circuit_changed",
}

CIRCUIT_KEYS = ["circuit:api", "circuit:trading", "circuit:model", "circuit:execution"]
PORTFOLIO_KEY = "portfolio:state"
POLL_INTERVAL = 5.0  # seconds


async def start_broadcaster(redis, manager: WSManager) -> None:
    """Entry point — starts all broadcaster tasks concurrently."""
    await asyncio.gather(
        _pubsub_listener(redis, manager),
        _state_poller(redis, manager),
        return_exceptions=True,
    )


async def _pubsub_listener(redis, manager: WSManager) -> None:
    """Subscribe to all trading channels and fan-out to WS clients."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(*CHANNEL_MAP.keys())
    logger.info("Broadcaster subscribed to %d channels", len(CHANNEL_MAP))

    try:
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            channel = raw["channel"]
            topic = CHANNEL_MAP.get(channel)
            if not topic:
                continue
            try:
                data = json.loads(raw["data"])
                await manager.broadcast(topic, {"type": topic, "payload": data})
            except Exception as exc:
                logger.debug("Broadcast error on %s: %s", channel, exc)
    except asyncio.CancelledError:
        await pubsub.unsubscribe()
        raise


async def _state_poller(redis, manager: WSManager) -> None:
    """
    Polls Redis key-value state every POLL_INTERVAL seconds.
    Broadcasts only when state changes (diff detection).
    """
    last_state: Dict[str, Any] = {}

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)

            # ── Circuit breakers ──────────────────────────────────────────
            for key in CIRCUIT_KEYS:
                raw = await redis.get(key)
                if raw != last_state.get(key):
                    last_state[key] = raw
                    if raw:
                        try:
                            data = json.loads(raw)
                            await manager.broadcast("circuit_changed", {
                                "type": "circuit_changed",
                                "payload": data,
                            })
                        except Exception:
                            pass

            # ── Portfolio state ───────────────────────────────────────────
            raw_portfolio = await redis.get(PORTFOLIO_KEY)
            if raw_portfolio != last_state.get(PORTFOLIO_KEY):
                last_state[PORTFOLIO_KEY] = raw_portfolio
                if raw_portfolio:
                    try:
                        data = json.loads(raw_portfolio)
                        await manager.broadcast("portfolio_update", {
                            "type": "portfolio_update",
                            "payload": data,
                        })
                    except Exception:
                        pass

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("State poller error: %s", exc)
