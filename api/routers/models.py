from fastapi import APIRouter, Depends
from api.dependencies import get_pg, get_redis, get_settings
from api.services import postgres_service, redis_service, prometheus_service

router = APIRouter(tags=["models"])


@router.get("/models/performance")
async def get_model_performance(pg=Depends(get_pg), redis=Depends(get_redis), settings=Depends(get_settings)):
    data, weights, metrics = await _gather(pg, redis, settings)
    versions = data.get("versions", [])

    xgb_brier = prometheus_service.extract_gauge(metrics, "model_brier_score", {"model_name": "xgb"})
    lgbm_brier = prometheus_service.extract_gauge(metrics, "model_brier_score", {"model_name": "lgbm"})

    # Fallback to latest DB version
    if not xgb_brier and versions:
        xgb_brier = versions[0].get("xgb_brier_score") or 0
    if not lgbm_brier and versions:
        lgbm_brier = versions[0].get("lgbm_brier_score") or 0

    return {
        "current_version": versions[0]["version"] if versions else "no model",
        "xgb_brier_score": xgb_brier,
        "lgbm_brier_score": lgbm_brier,
        "training_samples": versions[0]["training_samples"] if versions else 0,
        "deployed_at": str(versions[0]["deployed_at"]) if versions else None,
        "weights": weights,
        "calibration": data.get("calibration", []),
        "accuracy_history": data.get("accuracy_history", []),
        "version_history": versions,
    }


async def _gather(pg, redis, settings):
    import asyncio
    return await asyncio.gather(
        postgres_service.get_model_performance(pg),
        redis_service.get_ensemble_weights(redis),
        prometheus_service.get_metrics(settings.prometheus_url),
    )
