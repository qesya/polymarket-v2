"""
Redis message bus for inter-agent communication.
Agents publish Pydantic models as JSON; subscribers deserialize back to typed objects.
Also provides Celery task dispatch for CPU-bound work (model retraining, postmortems).
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Type
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Redis channels (single source of truth for all agents)
CHANNEL_MARKET_SCAN = "market.scan"
CHANNEL_RESEARCH_JOBS = "research.jobs"
CHANNEL_PREDICTIONS_READY = "predictions.ready"
CHANNEL_RISK_SIGNALS = "risk.signals"
CHANNEL_EXECUTION_ORDERS = "execution.orders"
CHANNEL_LEARNING_EVENTS = "learning.events"
CHANNEL_CIRCUIT_BREAKER = "circuit.breaker"


class RedisMessageBus:
    """
    Async Redis pub/sub bus with typed Pydantic message deserialization.

    Usage:
        bus = RedisMessageBus(redis_client)
        await bus.publish(CHANNEL_MARKET_SCAN, market_candidate)

        async for msg in bus.subscribe(CHANNEL_MARKET_SCAN, MarketCandidate):
            process(msg)
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        self._pubsub = None

    async def publish(self, channel: str, payload: BaseModel) -> None:
        """Serialize Pydantic model to JSON and publish to channel."""
        try:
            data = payload.model_dump_json()
            await self._redis.publish(channel, data)
            logger.debug("Published to %s: %s bytes", channel, len(data))
        except Exception as e:
            logger.error("Bus publish error on %s: %s", channel, e)
            raise

    async def subscribe(
        self,
        channel: str,
        model_class: Type[BaseModel],
        handler: Callable[[BaseModel], Coroutine],
    ) -> None:
        """
        Subscribe to a channel and invoke handler for each message.
        Runs indefinitely — call as an asyncio task.
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        logger.info("Subscribed to channel: %s", channel)

        try:
            async for raw_msg in pubsub.listen():
                if raw_msg["type"] != "message":
                    continue
                try:
                    obj = model_class.model_validate_json(raw_msg["data"])
                    await handler(obj)
                except Exception as e:
                    logger.error(
                        "Handler error on channel %s: %s | data=%s",
                        channel, e, raw_msg.get("data", "")[:200],
                    )
        finally:
            await pubsub.unsubscribe(channel)

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Read a JSON value from Redis key-value store (not pub/sub)."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        """Write a JSON-serializable value to Redis with TTL."""
        await self._redis.setex(key, ttl_seconds, json.dumps(value))

    async def setnx(self, key: str, value: str, ttl_seconds: int = 300) -> bool:
        """Set key only if not exists. Returns True if key was set (not duplicate)."""
        result = await self._redis.set(key, value, nx=True, ex=ttl_seconds)
        return result is not None


# ── Celery app for heavy async work ──────────────────────────────────────────

def create_celery_app(broker_url: str):
    """
    Create a Celery app for CPU-bound tasks (retraining, postmortem analysis).
    Called from worker process, not from async agents.
    """
    from celery import Celery
    app = Celery("polymarket", broker=broker_url, backend=broker_url)
    app.config_from_object({
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "task_track_started": True,
        "task_acks_late": True,           # re-queue on worker crash
        "worker_prefetch_multiplier": 1,  # one task at a time per worker (retrain is heavy)
        "task_routes": {
            "model.trainer.run_nightly_retrain": {"queue": "retrain"},
            "agents.learning_agent.run_postmortem": {"queue": "postmortem"},
        },
    })
    return app
