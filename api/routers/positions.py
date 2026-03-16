from fastapi import APIRouter, Depends
from api.dependencies import get_pg
from api.services import postgres_service

router = APIRouter(tags=["positions"])


@router.get("/positions")
async def get_positions(pg=Depends(get_pg)):
    return await postgres_service.get_positions(pg)
