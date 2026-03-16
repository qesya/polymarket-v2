"""
BaseAgent ABC. All agents inherit from this.
Provides: Redis pub/sub integration, Prometheus metrics, circuit breaker checks,
structured logging, and the main asyncio run loop.
"""
from __future__ import annotations
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel

from core import metrics as m
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Every concrete agent must:
      - set self.name (used in metrics + logs)
      - implement process(message) for reactive message handling
      - implement tick() for proactive polling (called every cycle_interval_seconds)

    The run() loop handles:
      - Subscribing to Redis channels (if subscribe_channels set)
      - Calling tick() on interval
      - Recording cycle duration in Prometheus
      - Catching and counting exceptions without crashing the loop
    """

    name: str = "base"
    cycle_interval_seconds: float = 60.0

    def __init__(self, bus, circuit_breaker: CircuitBreaker) -> None:
        self.bus = bus
        self.cb = circuit_breaker
        self._running = False
        self._log = logging.getLogger(f"agent.{self.name}")

    @abstractmethod
    async def tick(self) -> None:
        """
        Called every cycle_interval_seconds.
        Use for proactive scanning / polling independent of bus messages.
        """
        ...

    async def process(self, message: BaseModel) -> Optional[BaseModel]:
        """
        Called when a message arrives on a subscribed channel.
        Return a result to auto-publish on self.publish_channel.
        Default: no-op (agents that don't subscribe override this).
        """
        return None

    async def run(self) -> None:
        """Main agent loop. Call as an asyncio task."""
        self._running = True
        self._log.info("Agent %s starting", self.name)

        while self._running:
            start = time.perf_counter()
            try:
                await self.tick()
            except asyncio.CancelledError:
                self._log.info("Agent %s cancelled", self.name)
                break
            except Exception as exc:
                m.AGENT_ERRORS.labels(
                    agent_name=self.name,
                    error_type=type(exc).__name__,
                ).inc()
                self._log.exception("Agent %s tick error: %s", self.name, exc)
                # Back off before retrying to avoid tight error loops
                await asyncio.sleep(min(self.cycle_interval_seconds, 10.0))
                continue
            finally:
                elapsed = time.perf_counter() - start
                m.AGENT_CYCLE_DURATION.labels(agent_name=self.name).observe(elapsed)

            await asyncio.sleep(self.cycle_interval_seconds)

    async def stop(self) -> None:
        self._running = False

    async def publish(self, channel: str, payload: BaseModel) -> None:
        """Helper: publish to bus with error counting."""
        try:
            await self.bus.publish(channel, payload)
        except Exception as exc:
            m.AGENT_ERRORS.labels(
                agent_name=self.name, error_type="publish_error"
            ).inc()
            self._log.error("Publish error to %s: %s", channel, exc)

    async def check_circuit(self, breaker_name: str) -> bool:
        """Returns True if circuit is open (operation should be blocked)."""
        is_open = await self.cb.is_open(breaker_name)
        if is_open:
            self._log.warning("Circuit %s is OPEN — skipping operation", breaker_name)
            m.CIRCUIT_BREAKER_STATE.labels(breaker_name=breaker_name).set(1)
        else:
            m.CIRCUIT_BREAKER_STATE.labels(breaker_name=breaker_name).set(0)
        return is_open
