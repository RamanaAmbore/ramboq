"""
Replay / backtest control plane — `/api/replay/*`.

Feeds historical Kite OHLCV candles through the agent engine at an
accelerated playback rate. Available on both dev and prod branches
(gated by `cap_in_<branch>.replay`).

Endpoints
  GET  /api/replay/status         — driver snapshot
  POST /api/replay/start          — begin a replay run
  POST /api/replay/stop           — halt the replay
  GET  /api/replay/results        — agent fire results from the run
  GET  /api/replay/orders/recent  — recent mode='replay' algo orders
  POST /api/replay/clear          — wipe replay rows from agent_events + algo_orders
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import msgspec
from litestar import Controller, get, post
from litestar.exceptions import HTTPException
from sqlalchemy import delete as sql_delete, desc, select

from backend.api.algo.replay.driver import get_replay_driver
from backend.api.auth_guard import admin_guard, auth_or_demo_guard
from backend.api.database import async_session
from backend.api.models import AgentEvent, AlgoOrder
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReplayStartRequest(msgspec.Struct):
    symbols: list[str]
    date_from: str        # ISO date string YYYY-MM-DD
    date_to: str          # ISO date string YYYY-MM-DD
    interval: str = "5minute"
    rate_ms: int = 100
    agent_ids: Optional[list[int]] = None
    spread_pct: float = 0.10


class ReplayStatusResponse(msgspec.Struct):
    active: bool
    started_at: Optional[str]
    tick_index: int
    total_ticks: int
    rate_ms: int
    date_from: Optional[str]
    date_to: Optional[str]
    interval: str
    agent_ids: Optional[list[int]]
    symbols: list[str]
    results_count: int
    enabled: bool
    branch: str


class ReplayResultRow(msgspec.Struct):
    tick_index: int
    timestamp: Optional[str]
    agent_slug: str
    agent_name: str
    event_type: str
    detail: Optional[str]


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ReplayController(Controller):
    path = "/api/replay"
    guards = [admin_guard]

    @get("/status", guards=[auth_or_demo_guard])
    async def status(self) -> dict:
        from backend.shared.helpers.utils import is_enabled, config
        drv = get_replay_driver()
        snap = drv.snapshot()
        snap["enabled"] = is_enabled("replay")
        snap["branch"] = config.get("deploy_branch", "dev") or "dev"
        return snap

    @post("/start")
    async def start(self, data: ReplayStartRequest) -> dict:
        try:
            d_from = date.fromisoformat(data.date_from)
            d_to = date.fromisoformat(data.date_to)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date: {e}")

        drv = get_replay_driver()
        try:
            return drv.start(
                symbols=data.symbols,
                date_from=d_from,
                date_to=d_to,
                interval=data.interval,
                rate_ms=data.rate_ms,
                agent_ids=data.agent_ids,
                spread_pct=data.spread_pct,
            )
        except (RuntimeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @post("/stop")
    async def stop(self) -> dict:
        drv = get_replay_driver()
        return drv.stop()

    @get("/results")
    async def results(self) -> list[dict]:
        drv = get_replay_driver()
        return drv.results()

    @get("/orders/recent")
    async def recent_orders(self, limit: int = 50) -> list[dict]:
        limit = min(max(1, limit), 200)
        async with async_session() as s:
            rows = (await s.execute(
                select(AlgoOrder)
                .where(AlgoOrder.mode == "replay")
                .order_by(desc(AlgoOrder.created_at))
                .limit(limit)
            )).scalars().all()
        return [
            {
                "id": r.id,
                "account": r.account,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "side": r.transaction_type,
                "quantity": r.quantity,
                "initial_price": r.initial_price,
                "status": r.status,
                "mode": r.mode,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    @post("/clear")
    async def clear(self) -> dict:
        async with async_session() as s:
            r1 = await s.execute(
                sql_delete(AlgoOrder).where(AlgoOrder.mode == "replay")
            )
            await s.commit()
        return {"deleted_orders": r1.rowcount}
