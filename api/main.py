"""
FastAPI dashboard backend.
Serves REST + WebSocket endpoints for the React dashboard.
Connects to Redis, PostgreSQL, and scrapes Prometheus metrics.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import Settings
from api.websocket_manager import WSManager
from api.services.broadcaster import start_broadcaster
from api.routers import overview, positions, trades, markets, models, risk, ws as ws_router

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────
    app.state.settings = settings

    app.state.pg_pool = await asyncpg.create_pool(
        settings.postgres_url,
        min_size=2,
        max_size=8,
        command_timeout=30,
    )

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5,
    )

    app.state.ws_manager = WSManager()

    # Start Redis → WebSocket broadcaster
    broadcaster_task = asyncio.create_task(
        start_broadcaster(app.state.redis, app.state.ws_manager)
    )
    app.state.broadcaster_task = broadcaster_task

    logger.info("Dashboard API started")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    broadcaster_task.cancel()
    await app.state.pg_pool.close()
    await app.state.redis.aclose()
    logger.info("Dashboard API shut down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Polymarket AI Trading Dashboard",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(overview.router, prefix="/api")
    app.include_router(positions.router, prefix="/api")
    app.include_router(trades.router, prefix="/api")
    app.include_router(markets.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(risk.router, prefix="/api")
    app.include_router(ws_router.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8080, reload=True, log_level="info")
