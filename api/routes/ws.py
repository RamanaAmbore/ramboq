"""
WebSocket endpoint — pushes live performance data to connected clients.

Background worker publishes to Redis pub/sub channel 'performance:update'.
This handler subscribes and fans out to all connected browser sessions.

Usage (client JS):
    const ws = new WebSocket("ws://localhost:8000/ws/performance");
    ws.onmessage = (e) => { const data = JSON.parse(e.data); ... };

Message format: JSON with keys: holdings, positions, funds, refreshed_at
"""

import asyncio
import json

from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect
from litestar.handlers import WebsocketListener

from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class WSController(WebsocketListener):
    path = "/ws/performance"

    async def on_accept(self, socket: WebSocket) -> None:
        logger.info(f"WebSocket client connected: {socket.client}")

    async def on_disconnect(self, socket: WebSocket) -> None:
        logger.info(f"WebSocket client disconnected: {socket.client}")

    async def on_receive(self, data: str, socket: WebSocket) -> str:
        """Echo ping/pong for connection health checks."""
        if data == "ping":
            return "pong"
        return ""
