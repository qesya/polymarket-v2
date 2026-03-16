from fastapi import APIRouter, Depends
from api.dependencies import get_redis, get_pg
from api.services import redis_service

router = APIRouter(tags=["markets"])


@router.get("/markets/candidates")
async def get_market_candidates(redis=Depends(get_redis), pg=Depends(get_pg)):
    candidates = await redis_service.get_latest_market_candidates(redis)
    if not candidates:
        # cold-start fallback: query active markets from DB
        async with pg.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id AS market_id, question, category,
                       last_price_yes AS price_yes,
                       last_volume_24h AS volume_24h,
                       0.5 AS opportunity_score
                FROM markets WHERE is_active = true
                ORDER BY last_volume_24h DESC NULLS LAST LIMIT 50
            """)
        candidates = [dict(r) for r in rows]
    return candidates
