"""
Storage layer: PostgreSQL (asyncpg), Redis (async), ChromaDB.
Each function returns typed results using Pydantic models where applicable.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import asyncpg
import redis.asyncio as aioredis
import chromadb

from core.config import settings
from core.models import PortfolioState

logger = logging.getLogger(__name__)

# ── Connection pool singletons ────────────────────────────────────────────────
_pg_pool: Optional[asyncpg.Pool] = None
_redis_client = None
_chroma_client = None


async def get_pg_pool() -> asyncpg.Pool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            settings.postgres_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pg_pool


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


def get_chroma() -> chromadb.AsyncHttpClient:
    global _chroma_client
    if _chroma_client is None:
        host, port = settings.chroma_url.replace("http://", "").split(":")
        _chroma_client = chromadb.HttpClient(host=host, port=int(port))
    return _chroma_client


# ── PostgreSQL helpers ────────────────────────────────────────────────────────

async def upsert_market(market_data: Dict[str, Any]) -> None:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO markets (id, question, category, resolves_at, last_price_yes, last_volume_24h, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO UPDATE SET
                last_price_yes = EXCLUDED.last_price_yes,
                last_volume_24h = EXCLUDED.last_volume_24h,
                metadata = EXCLUDED.metadata
            """,
            market_data["id"],
            market_data["question"],
            market_data.get("category"),
            market_data.get("resolves_at"),
            market_data.get("price_yes"),
            market_data.get("volume_24h"),
            json.dumps(market_data.get("metadata", {})),
        )


async def insert_prediction(prediction: Dict[str, Any]) -> int:
    """Insert a prediction record and return the generated ID."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO predictions
                (market_id, p_yes_xgb, p_yes_lgbm, p_yes_claude, p_yes_ensemble,
                 edge, market_price, confidence, model_version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            prediction["market_id"],
            prediction.get("p_yes_xgb"),
            prediction.get("p_yes_lgbm"),
            prediction.get("p_yes_claude"),
            prediction["p_yes_ensemble"],
            prediction["edge"],
            prediction["market_price"],
            prediction["confidence"],
            prediction["model_version"],
        )
    return row["id"]


async def insert_trade(trade: Dict[str, Any]) -> int:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO trades
                (idempotency_key, market_id, prediction_id, side,
                 intended_shares, intended_price, dollar_size, status,
                 kelly_fraction, portfolio_value_at_trade)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            trade["idempotency_key"],
            trade["market_id"],
            trade.get("prediction_id"),
            trade["side"],
            trade["intended_shares"],
            trade["intended_price"],
            trade["dollar_size"],
            "PENDING",
            trade["kelly_fraction"],
            trade["portfolio_value_at_trade"],
        )
    if row is None:
        logger.warning("Duplicate trade ignored: %s", trade["idempotency_key"])
        return -1
    return row["id"]


async def update_trade_fill(trade_id: int, fill_data: Dict[str, Any]) -> None:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE trades SET
                order_id = $2,
                filled_shares = $3,
                fill_price = $4,
                slippage_bps = $5,
                status = $6,
                filled_at = $7
            WHERE id = $1
            """,
            trade_id,
            fill_data["order_id"],
            fill_data["filled_shares"],
            fill_data["fill_price"],
            fill_data["slippage_bps"],
            fill_data["status"],
            datetime.now(timezone.utc),
        )


async def fetch_unresolved_trades() -> List[asyncpg.Record]:
    """Fetch open trades for resolution polling."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT t.*, m.resolves_at, m.resolution
            FROM trades t
            JOIN markets m ON t.market_id = m.id
            WHERE t.status IN ('FILLED', 'PARTIAL')
              AND m.resolution IS NULL
            ORDER BY t.filled_at ASC
            """
        )


async def fetch_training_data(window_days: int = 90) -> List[asyncpg.Record]:
    """Fetch resolved trades for model retraining."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT p.*, m.resolution, t.pnl_realized
            FROM predictions p
            JOIN markets m ON p.market_id = m.id
            LEFT JOIN trades t ON t.prediction_id = p.id
            WHERE m.resolution IS NOT NULL
              AND p.created_at > NOW() - INTERVAL '$1 days'
            ORDER BY p.created_at DESC
            """,
            window_days,
        )


# ── Redis portfolio state ─────────────────────────────────────────────────────

PORTFOLIO_KEY = "portfolio:state"


async def get_portfolio_state() -> Optional[PortfolioState]:
    redis = await get_redis()
    raw = await redis.get(PORTFOLIO_KEY)
    if raw is None:
        return None
    return PortfolioState.model_validate_json(raw)


async def set_portfolio_state(state: PortfolioState) -> None:
    redis = await get_redis()
    await redis.setex(PORTFOLIO_KEY, 300, state.model_dump_json())


# ── ChromaDB narrative store ──────────────────────────────────────────────────

COLLECTION_NARRATIVES = "market_narratives"
COLLECTION_MISTAKES = "trade_mistakes"


def store_narrative_embedding(
    market_id: str,
    text: str,
    embedding: List[float],
    metadata: Dict[str, Any],
) -> str:
    """Store narrative embedding and return document ID."""
    chroma = get_chroma()
    collection = chroma.get_or_create_collection(COLLECTION_NARRATIVES)
    doc_id = hashlib.sha256(f"{market_id}:{text[:100]}".encode()).hexdigest()[:16]
    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{"market_id": market_id, **metadata}],
    )
    return doc_id


def query_similar_narratives(
    embedding: List[float],
    n_results: int = 5,
    filter_resolved: bool = True,
) -> Dict[str, Any]:
    """Find narratives similar to the given embedding."""
    chroma = get_chroma()
    collection = chroma.get_or_create_collection(COLLECTION_NARRATIVES)
    where = {"resolved": True} if filter_resolved else {}
    return collection.query(
        query_embeddings=[embedding],
        n_results=n_results,
        where=where if where else None,
    )


def store_mistake_embedding(
    trade_id: int,
    analysis_text: str,
    embedding: List[float],
    metadata: Dict[str, Any],
) -> str:
    chroma = get_chroma()
    collection = chroma.get_or_create_collection(COLLECTION_MISTAKES)
    doc_id = f"mistake_{trade_id}"
    collection.add(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[analysis_text],
        metadatas=[{"trade_id": trade_id, **metadata}],
    )
    return doc_id
