"""
System-level circuit breaker. Agents check this before taking action.
State persisted in Redis so all agent pods share the same view.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from core.models import CircuitBreakerState

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "circuit:"


class CircuitBreaker:
    """
    Thread-safe async circuit breaker backed by Redis.

    States:
        CLOSED (is_open=False): Normal operation
        OPEN   (is_open=True):  Blocked, no new actions

    Breaker names used in this system:
        "api"          — Polymarket API failures
        "trading"      — Drawdown / daily loss limit hit
        "model"        — Model staleness / degradation
        "execution"    — Order execution failures
    """

    def __init__(self, redis_client, failure_threshold: int = 3) -> None:
        self._redis = redis_client
        self._failure_threshold = failure_threshold

    async def is_open(self, name: str) -> bool:
        """Check if circuit is open (blocking). Fast path: O(1) Redis GET."""
        raw = await self._redis.get(f"{REDIS_KEY_PREFIX}{name}")
        if raw is None:
            return False
        state = CircuitBreakerState.model_validate_json(raw)
        return state.is_open

    async def trip(self, name: str, reason: str) -> None:
        """Open the circuit breaker — blocks all gated operations."""
        state = CircuitBreakerState(
            name=name,
            is_open=True,
            reason=reason,
            opened_at=datetime.now(timezone.utc),
        )
        await self._redis.set(
            f"{REDIS_KEY_PREFIX}{name}",
            state.model_dump_json(),
            ex=3600,  # auto-expire after 1h so a restart can recover
        )
        logger.warning("CIRCUIT OPEN: %s — %s", name, reason)

    async def reset(self, name: str) -> None:
        """Close the circuit breaker — resumes normal operation."""
        state = CircuitBreakerState(name=name, is_open=False)
        await self._redis.set(
            f"{REDIS_KEY_PREFIX}{name}",
            state.model_dump_json(),
            ex=86400,
        )
        logger.info("CIRCUIT CLOSED: %s", name)

    async def record_failure(self, name: str, error: str) -> None:
        """
        Increment failure counter. Auto-trip when threshold exceeded.
        Counter resets on success (call reset()) or after TTL.
        """
        counter_key = f"{REDIS_KEY_PREFIX}{name}:failures"
        count = await self._redis.incr(counter_key)
        await self._redis.expire(counter_key, 300)  # 5-minute window

        logger.warning("Circuit %s failure %d/%d: %s", name, count, self._failure_threshold, error)

        if count >= self._failure_threshold:
            await self.trip(name, f"Failure threshold exceeded ({count} failures): {error}")

    async def record_success(self, name: str) -> None:
        """Reset failure counter on successful operation."""
        counter_key = f"{REDIS_KEY_PREFIX}{name}:failures"
        await self._redis.delete(counter_key)

    async def get_state(self, name: str) -> CircuitBreakerState:
        raw = await self._redis.get(f"{REDIS_KEY_PREFIX}{name}")
        if raw is None:
            return CircuitBreakerState(name=name, is_open=False)
        return CircuitBreakerState.model_validate_json(raw)
