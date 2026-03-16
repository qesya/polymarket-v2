from __future__ import annotations
import json
from typing import Any, Dict, Optional


async def get_portfolio(redis) -> Optional[Dict]:
    raw = await redis.get("portfolio:state")
    return json.loads(raw) if raw else None


async def get_circuit_breakers(redis) -> Dict[str, Any]:
    names = ["api", "trading", "model", "execution"]
    result = {}
    for name in names:
        raw = await redis.get(f"circuit:{name}")
        result[name] = json.loads(raw) if raw else {"name": name, "is_open": False, "reason": ""}
    return result


async def get_ensemble_weights(redis) -> Dict[str, float]:
    raw = await redis.get("model:ensemble_weights")
    if raw:
        return json.loads(raw)
    return {"xgb": 0.45, "lgbm": 0.35, "claude": 0.20}


async def get_latest_market_candidates(redis) -> list:
    """Read cached market candidates (written by broadcaster from scan channel)."""
    raw = await redis.get("dashboard:market_candidates")
    return json.loads(raw) if raw else []


async def set_market_candidates(redis, candidates: list) -> None:
    await redis.setex("dashboard:market_candidates", 120, json.dumps(candidates))
