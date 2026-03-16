import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.dependencies import get_ws_manager

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

ALL_TOPICS = ["portfolio_update", "trade_filled", "circuit_changed",
              "market_candidate", "prediction_result", "agent_heartbeat"]


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    manager = get_ws_manager(ws)
    await manager.connect(ws)
    # Auto-subscribe to all topics on connect
    manager.subscribe(ws, ALL_TOPICS)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "subscribe":
                    manager.subscribe(ws, msg.get("topics", []))
                elif msg.get("type") == "unsubscribe":
                    manager.unsubscribe(ws, msg.get("topics", []))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as exc:
        logger.debug("WS error: %s", exc)
        manager.disconnect(ws)
