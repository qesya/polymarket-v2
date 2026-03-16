"""
System entry point.

Starts all agents as asyncio tasks, wires up inter-agent message routing,
initializes infrastructure connections, starts Prometheus metrics server.

Usage:
    python main.py              # start full system
    python main.py --dry-run    # scanner + prediction only, no execution
    python main.py --retrain    # trigger model retraining and exit
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from typing import List

import anthropic
import redis.asyncio as aioredis

from core.config import settings
from core.bus import (
    RedisMessageBus,
    CHANNEL_MARKET_SCAN,
    CHANNEL_RESEARCH_JOBS,
    CHANNEL_PREDICTIONS_READY,
    CHANNEL_RISK_SIGNALS,
)
from core.circuit_breaker import CircuitBreaker
from core.models import MarketCandidate, ResearchSummary, PredictionResult, OrderIntent
from core.metrics import start_metrics_server
from agents.market_scanner import MarketScannerAgent
from agents.research_agent import ResearchAgent
from agents.prediction_agent import PredictionAgent
from agents.risk_agent import RiskAgent
from agents.execution_agent import ExecutionAgent
from agents.learning_agent import LearningAgent
from utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def main(dry_run: bool = False, retrain_only: bool = False) -> None:
    configure_logging()
    start_metrics_server(port=8001)

    # ── Infrastructure connections ────────────────────────────────────────
    redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5,
        retry_on_timeout=True,
    )

    bus = RedisMessageBus(redis_client)
    cb = CircuitBreaker(redis_client)

    # ── Anthropic client (optional) ───────────────────────────────────────
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        logger.info("Claude API connected: %s", settings.claude_model)
    else:
        logger.warning("No ANTHROPIC_API_KEY — Claude augmentation disabled")

    # ── One-shot retrain mode ─────────────────────────────────────────────
    if retrain_only:
        agent = LearningAgent(bus, cb, anthropic_client=claude_client, redis_client=redis_client)
        await agent.trigger_retrain()
        await redis_client.aclose()
        return

    # ── Agent instantiation ───────────────────────────────────────────────
    scanner = MarketScannerAgent(bus, cb)
    researcher = ResearchAgent(bus, cb, redis_client=redis_client, anthropic_client=claude_client)
    predictor = PredictionAgent(bus, cb, anthropic_client=claude_client, redis_client=redis_client)
    risk_agent = RiskAgent(bus, cb, redis_client=redis_client)
    execution = ExecutionAgent(bus, cb, redis_client=redis_client) if not dry_run else None
    learner = LearningAgent(bus, cb, anthropic_client=claude_client, redis_client=redis_client)

    # ── Message routing (pub/sub → agent queues) ──────────────────────────
    async def route_market_scan(candidate: MarketCandidate) -> None:
        """Scanner → Research + Prediction cache"""
        predictor.cache_market(candidate)
        await researcher.enqueue(candidate)

    async def route_research_jobs(summary: ResearchSummary) -> None:
        """Research → Prediction"""
        await predictor.enqueue(summary)

    async def route_predictions(prediction: PredictionResult) -> None:
        """Prediction → Risk"""
        await risk_agent.enqueue(prediction)

    async def route_risk_signals(order: OrderIntent) -> None:
        """Risk → Execution"""
        if execution:
            await execution.enqueue(order)
        else:
            logger.info(
                "[DRY RUN] Would execute: %s %s $%.2f (edge=%.3f)",
                order.side.value, order.market_id,
                order.dollar_size, order.kelly_calculation.expected_value,
            )

    # ── Assemble task list ────────────────────────────────────────────────
    tasks: List[asyncio.Task] = [
        asyncio.create_task(scanner.run(), name="scanner"),
        asyncio.create_task(researcher.run(), name="researcher"),
        asyncio.create_task(predictor.run(), name="predictor"),
        asyncio.create_task(risk_agent.run(), name="risk"),
        asyncio.create_task(learner.run(), name="learner"),

        # Bus subscribers (each runs its own loop)
        asyncio.create_task(
            bus.subscribe(CHANNEL_MARKET_SCAN, MarketCandidate, route_market_scan),
            name="sub_market_scan",
        ),
        asyncio.create_task(
            bus.subscribe(CHANNEL_RESEARCH_JOBS, ResearchSummary, route_research_jobs),
            name="sub_research",
        ),
        asyncio.create_task(
            bus.subscribe(CHANNEL_PREDICTIONS_READY, PredictionResult, route_predictions),
            name="sub_predictions",
        ),
        asyncio.create_task(
            bus.subscribe(CHANNEL_RISK_SIGNALS, OrderIntent, route_risk_signals),
            name="sub_risk",
        ),
    ]

    if execution:
        tasks.append(asyncio.create_task(execution.run(), name="execution"))

    logger.info(
        "System started — %d agents running%s",
        len(tasks),
        " [DRY RUN]" if dry_run else "",
    )

    # ── Graceful shutdown handler ─────────────────────────────────────────
    def _shutdown(sig_name: str) -> None:
        logger.info("Received %s — shutting down", sig_name)
        for task in tasks:
            task.cancel()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig.name: _shutdown(s))

    # ── Wait for all tasks ────────────────────────────────────────────────
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("All agents stopped")
    finally:
        await redis_client.aclose()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket AI Trading System")
    parser.add_argument("--dry-run", action="store_true", help="Run without executing trades")
    parser.add_argument("--retrain", action="store_true", help="Trigger model retraining and exit")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, retrain_only=args.retrain))
