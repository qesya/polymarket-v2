from fastapi import APIRouter, Depends
from api.dependencies import get_pg, get_redis, get_settings
from api.services import redis_service, postgres_service, prometheus_service

router = APIRouter(tags=["overview"])


@router.get("/overview")
async def get_overview(pg=Depends(get_pg), redis=Depends(get_redis), settings=Depends(get_settings)):
    portfolio, circuits, win_stats, metrics = await _gather(pg, redis, settings)

    agent_health = prometheus_service.extract_agent_health(metrics)
    portfolio = portfolio or {}

    return {
        "portfolio_value":       portfolio.get("total_value", 0),
        "cash_available":        portfolio.get("cash_available", 0),
        "daily_pnl":             portfolio.get("daily_pnl", 0),
        "peak_value":            portfolio.get("peak_value", 0),
        "current_drawdown_pct":  portfolio.get("current_drawdown_pct", 0),
        "open_position_count":   portfolio.get("open_position_count", 0),
        "win_rate_30d":          win_stats.get("win_rate_30d", 0),
        "total_trades_30d":      win_stats.get("total_trades_30d", 0),
        "total_pnl_30d":         win_stats.get("total_pnl_30d", 0),
        "circuit_breakers":      circuits,
        "agent_health":          agent_health,
    }


async def _gather(pg, redis, settings):
    import asyncio
    return await asyncio.gather(
        redis_service.get_portfolio(redis),
        redis_service.get_circuit_breakers(redis),
        postgres_service.get_win_rate_30d(pg),
        prometheus_service.get_metrics(settings.prometheus_url),
    )
