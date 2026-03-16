from __future__ import annotations
import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """
    Manages WebSocket connections with topic-based subscriptions.
    Thread-safe for asyncio use.
    """

    def __init__(self) -> None:
        # topic → set of subscribed websockets
        self._subscriptions: Dict[str, Set[WebSocket]] = defaultdict(set)
        # websocket → set of subscribed topics (for cleanup on disconnect)
        self._client_topics: Dict[WebSocket, Set[str]] = defaultdict(set)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        logger.debug("WS client connected")

    def disconnect(self, ws: WebSocket) -> None:
        for topic in self._client_topics.get(ws, set()):
            self._subscriptions[topic].discard(ws)
        self._client_topics.pop(ws, None)
        logger.debug("WS client disconnected")

    def subscribe(self, ws: WebSocket, topics: list[str]) -> None:
        for topic in topics:
            self._subscriptions[topic].add(ws)
            self._client_topics[ws].add(topic)

    def unsubscribe(self, ws: WebSocket, topics: list[str]) -> None:
        for topic in topics:
            self._subscriptions[topic].discard(ws)
            self._client_topics[ws].discard(topic)

    async def broadcast(self, topic: str, payload: dict) -> None:
        """Send a message to all subscribers of a topic."""
        message = json.dumps({"topic": topic, "ts": _utcnow(), **payload})
        dead = set()
        for ws in list(self._subscriptions.get(topic, set())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            self.disconnect(ws)


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
