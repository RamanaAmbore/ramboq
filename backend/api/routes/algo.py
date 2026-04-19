"""
Agents API routes and WebSocket.

GET  /api/algo/status     — current engine state
GET  /api/algo/positions  — positions flagged for closing
GET  /api/algo/orders     — active + completed chase orders
POST /api/algo/start      — manually trigger expiry close
POST /api/algo/stop       — stop all chase orders
POST /api/algo/chase      — chase a single order (reusable)
WS   /ws/algo             — real-time event stream
"""

import asyncio
import json

import msgspec
from litestar import Controller, WebSocket, get, post
from litestar import websocket as ws_handler
from litestar.exceptions import HTTPException, WebSocketDisconnect
from sqlalchemy import select

from backend.api.auth_guard import admin_guard
from backend.api.database import async_session
from backend.api.models import AlgoOrder, AlgoEvent
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

# Module-level state — shared across requests
_engine = None           # ExpiryEngine instance (when running)
_engine_task = None      # asyncio.Task running the engine
_ws_clients: set[asyncio.Queue] = set()


def _broadcast_event(event_type: str, detail: dict = None):
    """Push event to all connected WebSocket clients and log to DB."""
    msg = json.dumps({"event": event_type, **(detail or {})})
    for q in list(_ws_clients):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    # Also persist to DB (fire-and-forget)
    asyncio.get_event_loop().create_task(_persist_event(event_type, detail))


async def _persist_event(event_type: str, detail: dict = None):
    """Save event to algo_events table."""
    try:
        async with async_session() as session:
            event = AlgoEvent(
                event_type=event_type,
                detail=json.dumps(detail) if detail else None,
            )
            session.add(event)
            await session.commit()
    except Exception as e:
        logger.warning(f"Algo: failed to persist event: {e}")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChaseRequest(msgspec.Struct):
    account: str
    symbol: str
    transaction_type: str   # BUY or SELL
    quantity: int
    exchange: str = "NFO"
    product: str = "NRML"


class AlgoStatusResponse(msgspec.Struct):
    status: str
    pending_count: int
    closed_count: int
    failed_count: int
    total_slippage: float
    last_scan: str


class AlgoPositionInfo(msgspec.Struct):
    account: str
    symbol: str
    exchange: str
    instrument_type: str
    underlying: str
    strike: float
    quantity: int
    moneyness: str
    underlying_ltp: float
    needs_close: bool
    close_reason: str


class AlgoOrderInfo(msgspec.Struct):
    id: int
    account: str
    symbol: str
    exchange: str
    transaction_type: str
    quantity: int
    initial_price: float | None
    fill_price: float | None
    attempts: int
    slippage: float | None
    status: str
    engine: str
    detail: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AlgoController(Controller):
    path = "/api/algo"
    guards = [admin_guard]

    @get("/status")
    async def get_status(self) -> AlgoStatusResponse:
        if _engine:
            s = _engine.state
            return AlgoStatusResponse(
                status=s.status,
                pending_count=len(s.pending_chases),
                closed_count=len(s.closed),
                failed_count=len(s.failed),
                total_slippage=s.total_slippage,
                last_scan=s.last_scan,
            )
        return AlgoStatusResponse(
            status="idle", pending_count=0, closed_count=0,
            failed_count=0, total_slippage=0, last_scan="",
        )

    @get("/positions")
    async def get_positions(self) -> list[AlgoPositionInfo]:
        if not _engine:
            return []
        return [
            AlgoPositionInfo(
                account=p.account, symbol=p.tradingsymbol, exchange=p.exchange,
                instrument_type=p.instrument_type, underlying=p.underlying,
                strike=p.strike, quantity=p.quantity, moneyness=p.moneyness,
                underlying_ltp=p.underlying_ltp, needs_close=p.needs_close,
                close_reason=p.close_reason,
            )
            for p in _engine.state.positions
        ]

    @get("/orders")
    async def get_orders(self) -> list[AlgoOrderInfo]:
        async with async_session() as session:
            result = await session.execute(
                select(AlgoOrder).order_by(AlgoOrder.id.desc()).limit(100)
            )
            orders = result.scalars().all()
        return [
            AlgoOrderInfo(
                id=o.id, account=o.account, symbol=o.symbol, exchange=o.exchange,
                transaction_type=o.transaction_type, quantity=o.quantity,
                initial_price=o.initial_price, fill_price=o.fill_price,
                attempts=o.attempts, slippage=o.slippage, status=o.status,
                engine=o.engine, detail=o.detail,
                created_at=o.created_at.isoformat() if o.created_at else "",
            )
            for o in orders
        ]

    @post("/start")
    async def start_expiry(self) -> dict:
        global _engine, _engine_task

        if _engine_task and not _engine_task.done():
            raise HTTPException(status_code=409, detail="Expiry engine already running")

        from backend.api.algo.expiry import ExpiryEngine
        _engine = ExpiryEngine(on_event=_broadcast_event)
        _engine_task = asyncio.create_task(_engine.run())
        logger.info("Algo: expiry engine started manually")
        _broadcast_event("engine_started", {"trigger": "manual"})
        return {"detail": "Expiry engine started"}

    @post("/stop")
    async def stop_expiry(self) -> dict:
        global _engine, _engine_task

        if _engine_task and not _engine_task.done():
            _engine_task.cancel()
            try:
                await _engine_task
            except asyncio.CancelledError:
                pass
        _engine = None
        _engine_task = None
        logger.info("Algo: expiry engine stopped")
        _broadcast_event("engine_stopped", {"trigger": "manual"})
        return {"detail": "Expiry engine stopped"}

    @post("/chase")
    async def chase_single(self, data: ChaseRequest) -> dict:
        """Chase a single order using the adaptive limit engine."""
        from backend.api.algo.chase import chase_order, ChaseConfig

        cfg = ChaseConfig(exchange=data.exchange, product=data.product)
        result = await chase_order(
            account=data.account,
            symbol=data.symbol,
            transaction_type=data.transaction_type,
            quantity=data.quantity,
            cfg=cfg,
            on_event=_broadcast_event,
        )

        # Persist to DB
        async with async_session() as session:
            order = AlgoOrder(
                account=data.account, symbol=data.symbol, exchange=data.exchange,
                transaction_type=data.transaction_type, quantity=data.quantity,
                initial_price=result.initial_price, fill_price=result.fill_price,
                attempts=result.attempts, slippage=result.slippage,
                status=result.status.value, engine="manual",
                broker_order_id=result.order_id, detail=result.detail,
            )
            session.add(order)
            await session.commit()

        return {
            "status": result.status.value,
            "order_id": result.order_id,
            "fill_price": result.fill_price,
            "attempts": result.attempts,
            "slippage": result.slippage,
            "detail": result.detail,
        }


# ---------------------------------------------------------------------------
# WebSocket — real-time event stream
# ---------------------------------------------------------------------------

@ws_handler("/ws/algo")
async def algo_ws_handler(socket: WebSocket) -> None:
    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _ws_clients.add(queue)
    logger.info(f"Algo WS: client connected, total={len(_ws_clients)}")

    async def _send_loop():
        while True:
            msg = await queue.get()
            await socket.send_data(msg)

    async def _recv_loop():
        while True:
            data = await socket.receive_data(mode="text")
            if data == "ping":
                await socket.send_data("pong")

    send_task = asyncio.create_task(_send_loop())
    recv_task = asyncio.create_task(_recv_loop())

    try:
        _done, pending = await asyncio.wait(
            [send_task, recv_task], return_when=asyncio.FIRST_EXCEPTION,
        )
        for t in pending:
            t.cancel()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _ws_clients.discard(queue)
        logger.info(f"Algo WS: client disconnected, total={len(_ws_clients)}")
        try:
            await socket.close()
        except Exception:
            pass
