"""
WebSocket endpoint — pushes live performance data to connected clients.

Background worker publishes to Redis pub/sub channel 'performance:update'.
This handler subscribes and fans out to all connected browser sessions.

Usage (client JS):
    const ws = new WebSocket("ws://localhost:8000/ws/performance");
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        // data.event === "performance_updated"
        // data.refreshed_at — display timestamp
        // Re-fetch from /api/holdings/, /api/positions/, /api/funds/ as needed
    };

Ping/pong for connection health:
    ws.send("ping")  →  receives "pong"
"""

import asyncio

from litestar import WebSocket, websocket as ws_handler
from litestar.exceptions import WebSocketDisconnect

from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

# Module-level registry — each active WS connection has a dedicated asyncio.Queue.
# broadcast() puts messages into every queue; each connection's send-loop drains it.
_connection_queues: set[asyncio.Queue] = set()


def broadcast(message: str) -> None:
    """Fan out a message to every connected WebSocket client (non-blocking)."""
    for q in list(_connection_queues):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass  # slow client — drop rather than block the broadcaster


@ws_handler("/ws/performance")
async def performance_ws_handler(socket: WebSocket) -> None:
    await socket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    _connection_queues.add(queue)
    logger.info(
        f"WS client connected: {socket.client}  total={len(_connection_queues)}"
    )

    async def _send_loop() -> None:
        """Wait for queued messages and push them to the client."""
        while True:
            msg = await queue.get()
            await socket.send_data(msg)

    async def _recv_loop() -> None:
        """Handle incoming frames — only ping/pong for now."""
        while True:
            data = await socket.receive_data(mode="text")
            if data == "ping":
                await socket.send_data("pong")

    send_task = asyncio.create_task(_send_loop())
    recv_task = asyncio.create_task(_recv_loop())

    try:
        _done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, WebSocketDisconnect, Exception):
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _connection_queues.discard(queue)
        logger.info(
            f"WS client disconnected: {socket.client}  total={len(_connection_queues)}"
        )
        try:
            await socket.close()
        except Exception:
            pass
