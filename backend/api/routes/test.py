"""
Market-simulation control plane — `/api/test/*`.

Every endpoint is admin-guarded AND additionally refuses to run on the
`main` branch (see `SimDriver.assert_dev`). Pairs with
`backend/api/algo/sim/driver.py` and `frontend/src/routes/(algo)/admin/test`.

Endpoints
  GET  /api/test/scenarios         — list available scenarios
  GET  /api/test/status            — driver snapshot (active / tick / etc)
  POST /api/test/start             — begin a scenario at a given cadence
  POST /api/test/stop              — halt the sim
  POST /api/test/step              — apply a single tick (deterministic debug)
  POST /api/test/run-cycle         — immediately run the agent engine against
                                     the current sim state (no waiting for the
                                     next background tick)
  POST /api/test/clear             — wipe test_mode rows from agent_events
                                     and algo_orders (handy between runs)
  GET  /api/test/events/recent     — recent test_mode agent events
  GET  /api/test/orders/recent     — recent test_mode algo orders
"""

from __future__ import annotations

from typing import Optional

import msgspec
from litestar import Controller, delete, get, post
from litestar.exceptions import HTTPException
from sqlalchemy import delete as sql_delete, desc, select

from backend.api.algo.sim.driver import (
    SimGuardError,
    get_driver,
    load_scenarios,
)
from backend.api.auth_guard import admin_guard
from backend.api.database import async_session
from backend.api.models import AgentEvent, AlgoOrder
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SimStartRequest(msgspec.Struct):
    scenario: str
    rate_ms: int = 2000


class SimScenarioInfo(msgspec.Struct):
    slug: str
    name: str
    description: str
    ticks: int


class TestEventInfo(msgspec.Struct):
    id: int
    agent_id: int
    event_type: str
    trigger_condition: str | None
    detail: str | None
    timestamp: str


class TestOrderInfo(msgspec.Struct):
    id: int
    account: str
    symbol: str
    exchange: str
    transaction_type: str
    quantity: int
    status: str
    engine: str
    created_at: str
    detail: str | None


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class TestController(Controller):
    """Simulation control plane. Prefix keeps every endpoint easy to spot."""

    path = "/api/test"
    guards = [admin_guard]

    @get("/scenarios")
    async def list_scenarios(self) -> list[SimScenarioInfo]:
        out = []
        for s in load_scenarios():
            out.append(SimScenarioInfo(
                slug=s.get("slug"),
                name=s.get("name") or s.get("slug"),
                description=s.get("description", ""),
                ticks=len(s.get("ticks", []) or []),
            ))
        return out

    @get("/status")
    async def status(self) -> dict:
        return get_driver().snapshot()

    @post("/start")
    async def start(self, data: SimStartRequest) -> dict:
        try:
            return get_driver().start(data.scenario, data.rate_ms)
        except SimGuardError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @post("/stop")
    async def stop(self) -> dict:
        return get_driver().stop()

    @post("/step")
    async def step(self) -> dict:
        try:
            return get_driver().step()
        except SimGuardError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @post("/run-cycle")
    async def run_cycle_now(self) -> dict:
        """
        Run the agent engine's `run_cycle` immediately against the current
        sim state. Useful for step-mode debugging — lets the operator advance
        one tick, then ask the engine to evaluate against the mutated state
        without waiting for the next background refresh.
        """
        try:
            drv = get_driver()
            if not drv.active and not drv.scenario:
                raise SimGuardError("No scenario active. Start or step first.")
            from backend.api.algo.agent_engine import run_cycle
            from backend.api.routes.algo import _broadcast_event
            from backend.shared.helpers.date_time_utils import timestamp_indian, timestamp_display

            sum_h, sum_p, df_m = drv.dataframes()
            ctx = {
                "sum_holdings":   sum_h,
                "sum_positions":  sum_p,
                "df_margins":     df_m,
                "now":            timestamp_indian(),
                "ist_display":    timestamp_display(),
                "seg_state":      {},
                "segments":       [],
                # Propagated into V2Context → picked up by _dispatch and actions
                "alert_state":    {"test_mode": True},
                "test_mode":      True,
            }
            await run_cycle(ctx, _broadcast_event)
            return {"ok": True, "sim": drv.snapshot()}
        except SimGuardError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @post("/clear")
    async def clear_test_rows(self) -> dict:
        """Delete every test_mode row from agent_events and algo_orders."""
        async with async_session() as s:
            ev = await s.execute(sql_delete(AgentEvent).where(AgentEvent.test_mode.is_(True)))
            od = await s.execute(sql_delete(AlgoOrder).where(AlgoOrder.mode == "test"))
            await s.commit()
        return {"events_deleted": ev.rowcount or 0, "orders_deleted": od.rowcount or 0}

    @get("/events/recent")
    async def recent_events(self, limit: Optional[int] = 50) -> list[TestEventInfo]:
        limit = max(1, min(int(limit or 50), 500))
        async with async_session() as s:
            rows = (await s.execute(
                select(AgentEvent)
                .where(AgentEvent.test_mode.is_(True))
                .order_by(desc(AgentEvent.timestamp))
                .limit(limit)
            )).scalars().all()
        return [
            TestEventInfo(
                id=r.id, agent_id=r.agent_id, event_type=r.event_type,
                trigger_condition=r.trigger_condition, detail=r.detail,
                timestamp=r.timestamp.isoformat() if r.timestamp else "",
            )
            for r in rows
        ]

    @get("/ticks/recent")
    async def recent_ticks(self, limit: Optional[int] = 100) -> list[dict]:
        """
        Rolling buffer of recent simulator ticks (oldest-first). Returned
        entries include the patch applied and a per-field diff so the UI
        can render a compact timeline. Empty when no sim has run since
        process start.
        """
        return get_driver().recent_ticks(int(limit or 100))

    @get("/orders/recent")
    async def recent_orders(self, limit: Optional[int] = 50) -> list[TestOrderInfo]:
        limit = max(1, min(int(limit or 50), 500))
        async with async_session() as s:
            rows = (await s.execute(
                select(AlgoOrder)
                .where(AlgoOrder.mode == "test")
                .order_by(desc(AlgoOrder.created_at))
                .limit(limit)
            )).scalars().all()
        return [
            TestOrderInfo(
                id=r.id, account=r.account, symbol=r.symbol, exchange=r.exchange,
                transaction_type=r.transaction_type, quantity=r.quantity,
                status=r.status, engine=r.engine,
                created_at=r.created_at.isoformat() if r.created_at else "",
                detail=r.detail,
            )
            for r in rows
        ]
