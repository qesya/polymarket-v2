from fastapi import APIRouter, Depends, Query
from api.dependencies import get_pg, get_redis, get_settings
from api.services import postgres_service, redis_service, prometheus_service

router = APIRouter(tags=["risk"])


@router.get("/risk/summary")
async def get_risk_summary(pg=Depends(get_pg), redis=Depends(get_redis), settings=Depends(get_settings)):
    portfolio, circuits, metrics = await _gather(pg, redis, settings)
    portfolio = portfolio or {}

    rejected = {}
    for key, val in metrics.items():
        if val.get("name") == "trades_rejected_risk_total":
            reason = val.get("labels", {}).get("reason", "unknown")
            rejected[reason] = rejected.get(reason, 0) + int(val["value"])

    return {
        "current_drawdown_pct":  portfolio.get("current_drawdown_pct", 0),
        "max_drawdown_pct":      0.20,
        "daily_pnl":             portfolio.get("daily_pnl", 0),
        "daily_loss_limit_pct":  0.08,
        "kelly_fraction":        0.25,
        "max_open_positions":    20,
        "current_open_positions": portfolio.get("open_position_count", 0),
        "circuit_breakers":      circuits,
        "rejection_reasons":     [{"reason": k, "count": v} for k, v in rejected.items()],
    }


@router.get("/risk/drawdown-history")
async def get_drawdown_history(days: int = Query(30, le=365), pg=Depends(get_pg)):
    return await postgres_service.get_drawdown_history(pg, days)


async def _gather(pg, redis, settings):
    import asyncio
    return await asyncio.gather(
        redis_service.get_portfolio(redis),
        redis_service.get_circuit_breakers(redis),
        prometheus_service.get_metrics(settings.prometheus_url),
    )
