from typing import Optional
from fastapi import APIRouter, Depends, Query
from api.dependencies import get_pg
from api.services import postgres_service

router = APIRouter(tags=["trades"])


@router.get("/trades")
async def get_trades(
    status: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    pg=Depends(get_pg),
):
    return await postgres_service.get_trades(pg, status=status, side=side, limit=limit, offset=offset)
