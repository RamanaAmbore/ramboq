"""
Agent CRUD API + terminal interpreter.

GET  /api/agents/               — list all agents
GET  /api/agents/types          — available condition fields, operators, action types
GET  /api/agents/{slug}         — single agent detail
POST /api/agents/               — create new agent
PUT  /api/agents/{slug}         — update agent config
PUT  /api/agents/{slug}/activate   — activate
PUT  /api/agents/{slug}/deactivate — deactivate
DELETE /api/agents/{slug}       — delete (non-system only)
GET  /api/agents/{slug}/events  — event history
POST /api/agents/interpret      — terminal command parser
"""

import json

import msgspec
from litestar import Controller, delete, get, post, put
from litestar.exceptions import HTTPException
from sqlalchemy import select

from api.auth_guard import admin_guard
from api.database import async_session
from api.models import Agent, AgentEvent
from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AgentInfo(msgspec.Struct):
    id: int
    slug: str
    name: str
    description: str | None
    conditions: dict
    events: list
    actions: list
    scope: str
    schedule: str | None
    cooldown_minutes: int
    status: str
    last_triggered_at: str | None
    trigger_count: int
    last_error: str | None
    is_system: bool


class AgentCreateRequest(msgspec.Struct):
    slug: str
    name: str
    conditions: dict
    events: list
    actions: list = []
    description: str = ""
    scope: str = "per_account"
    schedule: str = "market_hours"
    cooldown_minutes: int = 30


class AgentUpdateRequest(msgspec.Struct):
    name: str | None = None
    description: str | None = None
    conditions: dict | None = None
    events: list | None = None
    actions: list | None = None
    scope: str | None = None
    schedule: str | None = None
    cooldown_minutes: int | None = None


class AgentEventInfo(msgspec.Struct):
    id: int
    agent_id: int
    event_type: str
    trigger_condition: str | None
    detail: str | None
    timestamp: str


class InterpretRequest(msgspec.Struct):
    command: str


class InterpretResponse(msgspec.Struct):
    output: str
    success: bool = True


# Available fields for condition builder
CONDITION_FIELDS = [
    {"key": "day_change_val", "label": "Day P&L (₹)", "type": "number", "category": "holdings"},
    {"key": "day_change_percentage", "label": "Day P&L (%)", "type": "number", "category": "holdings"},
    {"key": "pnl", "label": "Total P&L (₹)", "type": "number", "category": "holdings"},
    {"key": "pnl_percentage", "label": "Total P&L (%)", "type": "number", "category": "holdings"},
    {"key": "cur_val", "label": "Current Value (₹)", "type": "number", "category": "holdings"},
    {"key": "cash", "label": "Cash Balance (₹)", "type": "number", "category": "funds"},
    {"key": "avail_margin", "label": "Available Margin (₹)", "type": "number", "category": "funds"},
    {"key": "used_margin", "label": "Used Margin (₹)", "type": "number", "category": "funds"},
    {"key": "collateral", "label": "Collateral (₹)", "type": "number", "category": "funds"},
    {"key": "nse_open", "label": "NSE Market Open", "type": "boolean", "category": "market"},
    {"key": "nse_closed", "label": "NSE Market Closed", "type": "boolean", "category": "market"},
    {"key": "mcx_open", "label": "MCX Market Open", "type": "boolean", "category": "market"},
    {"key": "mcx_closed", "label": "MCX Market Closed", "type": "boolean", "category": "market"},
    {"key": "minutes_since_nse_open", "label": "Minutes Since NSE Open", "type": "number", "category": "market"},
    {"key": "minutes_since_nse_close", "label": "Minutes Since NSE Close", "type": "number", "category": "market"},
    {"key": "minutes_since_mcx_open", "label": "Minutes Since MCX Open", "type": "number", "category": "market"},
    {"key": "minutes_since_mcx_close", "label": "Minutes Since MCX Close", "type": "number", "category": "market"},
    {"key": "is_expiry_day", "label": "Is Expiry Day", "type": "boolean", "category": "expiry"},
    {"key": "has_itm_positions", "label": "Has ITM Positions", "type": "boolean", "category": "expiry"},
]

CONDITION_OPERATORS = [">", "<", ">=", "<=", "==", "!="]
ACTION_TYPES = ["chase_close", "send_summary", "place_order"]
EVENT_CHANNELS = ["telegram", "email", "websocket", "log"]


def _agent_to_info(a: Agent) -> AgentInfo:
    return AgentInfo(
        id=a.id, slug=a.slug, name=a.name, description=a.description,
        conditions=a.conditions or {}, events=a.events or [],
        actions=a.actions or [], scope=a.scope,
        schedule=a.schedule, cooldown_minutes=a.cooldown_minutes,
        status=a.status,
        last_triggered_at=a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        trigger_count=a.trigger_count, last_error=a.last_error,
        is_system=a.is_system,
    )


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AgentController(Controller):
    path = "/api/agents"
    guards = [admin_guard]

    @get("/")
    async def list_agents(self) -> list[AgentInfo]:
        async with async_session() as session:
            result = await session.execute(select(Agent).order_by(Agent.id))
            agents = result.scalars().all()
        return [_agent_to_info(a) for a in agents]

    @get("/types")
    async def get_types(self) -> dict:
        return {
            "fields": CONDITION_FIELDS,
            "operators": CONDITION_OPERATORS,
            "action_types": ACTION_TYPES,
            "event_channels": EVENT_CHANNELS,
        }

    @get("/{slug:str}")
    async def get_agent(self, slug: str) -> AgentInfo:
        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
        return _agent_to_info(agent)

    @post("/")
    async def create_agent(self, data: AgentCreateRequest) -> dict:
        async with async_session() as session:
            existing = await session.execute(select(Agent).where(Agent.slug == data.slug))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Agent '{data.slug}' already exists")
            agent = Agent(
                slug=data.slug, name=data.name, description=data.description,
                conditions=data.conditions, events=data.events, actions=data.actions,
                scope=data.scope, schedule=data.schedule,
                cooldown_minutes=data.cooldown_minutes, status="inactive",
            )
            session.add(agent)
            await session.commit()
        logger.info(f"Agent created: {data.slug}")
        return {"detail": f"Agent '{data.slug}' created"}

    @put("/{slug:str}")
    async def update_agent(self, slug: str, data: AgentUpdateRequest) -> dict:
        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
            for field in ('name', 'description', 'conditions', 'events', 'actions',
                          'scope', 'schedule', 'cooldown_minutes'):
                val = getattr(data, field, None)
                if val is not None:
                    setattr(agent, field, val)
            await session.commit()
        logger.info(f"Agent updated: {slug}")
        return {"detail": f"Agent '{slug}' updated"}

    @put("/{slug:str}/activate", status_code=200)
    async def activate_agent(self, slug: str) -> dict:
        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
            agent.status = "active"
            await session.commit()
        return {"detail": f"Agent '{slug}' activated"}

    @put("/{slug:str}/deactivate", status_code=200)
    async def deactivate_agent(self, slug: str) -> dict:
        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
            agent.status = "inactive"
            await session.commit()
        return {"detail": f"Agent '{slug}' deactivated"}

    @delete("/{slug:str}", status_code=200)
    async def delete_agent(self, slug: str) -> dict:
        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
            if agent.is_system:
                raise HTTPException(status_code=403, detail="Cannot delete system agent")
            await session.delete(agent)
            await session.commit()
        return {"detail": f"Agent '{slug}' deleted"}

    @get("/{slug:str}/events")
    async def get_events(self, slug: str, n: int = 50) -> list[AgentEventInfo]:
        async with async_session() as session:
            agent_result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = agent_result.scalar_one_or_none()
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{slug}' not found")
            result = await session.execute(
                select(AgentEvent)
                .where(AgentEvent.agent_id == agent.id)
                .order_by(AgentEvent.id.desc())
                .limit(n)
            )
            events = result.scalars().all()
        return [
            AgentEventInfo(
                id=e.id, agent_id=e.agent_id, event_type=e.event_type,
                trigger_condition=e.trigger_condition, detail=e.detail,
                timestamp=e.timestamp.isoformat() if e.timestamp else "",
            )
            for e in events
        ]

    @get("/events/recent")
    async def get_recent_events(self, n: int = 100) -> list[AgentEventInfo]:
        async with async_session() as session:
            result = await session.execute(
                select(AgentEvent).order_by(AgentEvent.id.desc()).limit(n)
            )
            events = result.scalars().all()
        return [
            AgentEventInfo(
                id=e.id, agent_id=e.agent_id, event_type=e.event_type,
                trigger_condition=e.trigger_condition, detail=e.detail,
                timestamp=e.timestamp.isoformat() if e.timestamp else "",
            )
            for e in events
        ]

    @post("/interpret")
    async def interpret(self, data: InterpretRequest) -> InterpretResponse:
        """Parse and execute a terminal agent command."""
        parts = data.command.strip().split()
        if not parts or parts[0].lower() != "agent":
            return InterpretResponse(output="Usage: agent <command> [args]", success=False)

        action = parts[1].lower() if len(parts) > 1 else "help"

        if action == "list":
            return await self._cmd_list()
        elif action == "status" and len(parts) > 2:
            return await self._cmd_status(parts[2])
        elif action == "activate" and len(parts) > 2:
            await self.activate_agent(parts[2])
            return InterpretResponse(output=f"Agent '{parts[2]}' activated")
        elif action == "deactivate" and len(parts) > 2:
            await self.deactivate_agent(parts[2])
            return InterpretResponse(output=f"Agent '{parts[2]}' deactivated")
        elif action == "events" and len(parts) > 2:
            return await self._cmd_events(parts[2])
        elif action == "config" and len(parts) > 2:
            return await self._cmd_config(parts[2:])
        elif action == "help":
            return InterpretResponse(output=self._help_text())
        else:
            return InterpretResponse(output=f"Unknown command: agent {action}\n\n{self._help_text()}", success=False)

    async def _cmd_list(self) -> InterpretResponse:
        agents = await self.list_agents()
        if not agents:
            return InterpretResponse(output="No agents configured.")
        lines = [f"{'SLUG':<22} {'NAME':<28} {'STATUS':<12} {'TRIGGERS':<8} {'LAST TRIGGERED'}"]
        lines.append("-" * 90)
        for a in agents:
            last = a.last_triggered_at[:16] if a.last_triggered_at else "—"
            lines.append(f"{a.slug:<22} {a.name:<28} {a.status:<12} {a.trigger_count:<8} {last}")
        return InterpretResponse(output="\n".join(lines))

    async def _cmd_status(self, slug: str) -> InterpretResponse:
        try:
            a = await self.get_agent(slug)
        except HTTPException:
            return InterpretResponse(output=f"Agent '{slug}' not found", success=False)
        lines = [
            f"Agent: {a.name} ({a.slug})",
            f"Status: {a.status}",
            f"Scope: {a.scope} | Schedule: {a.schedule} | Cooldown: {a.cooldown_minutes}m",
            f"Triggers: {a.trigger_count} | Last: {a.last_triggered_at or '—'}",
            f"Conditions: {json.dumps(a.conditions, indent=2)}",
            f"Events: {json.dumps(a.events)}",
            f"Actions: {json.dumps(a.actions) if a.actions else 'Alert only'}",
        ]
        if a.last_error:
            lines.append(f"Last Error: {a.last_error}")
        return InterpretResponse(output="\n".join(lines))

    async def _cmd_events(self, slug: str) -> InterpretResponse:
        try:
            events = await self.get_events(slug, n=20)
        except HTTPException:
            return InterpretResponse(output=f"Agent '{slug}' not found", success=False)
        if not events:
            return InterpretResponse(output=f"No events for agent '{slug}'")
        lines = [f"{'TIME':<20} {'TYPE':<18} {'CONDITION'}"]
        lines.append("-" * 70)
        for e in events:
            t = e.timestamp[:19] if e.timestamp else ""
            cond = e.trigger_condition or "—"
            lines.append(f"{t:<20} {e.event_type:<18} {cond[:50]}")
        return InterpretResponse(output="\n".join(lines))

    async def _cmd_config(self, parts: list) -> InterpretResponse:
        slug = parts[0]
        kv_pairs = parts[1:]
        if not kv_pairs:
            return await self._cmd_status(slug)

        async with async_session() as session:
            result = await session.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                return InterpretResponse(output=f"Agent '{slug}' not found", success=False)

            conditions = agent.conditions or {}
            for kv in kv_pairs:
                if "=" not in kv:
                    continue
                key, val = kv.split("=", 1)
                # Update leaf condition value
                if "rules" in conditions:
                    for rule in conditions.get("rules", []):
                        if rule.get("field") == key:
                            try:
                                rule["value"] = float(val) if "." in val else int(val)
                            except ValueError:
                                rule["value"] = val
                elif conditions.get("field") == key:
                    try:
                        conditions["value"] = float(val) if "." in val else int(val)
                    except ValueError:
                        conditions["value"] = val

            agent.conditions = conditions
            await session.commit()

        return InterpretResponse(output=f"Agent '{slug}' config updated")

    def _help_text(self) -> str:
        return """Agent Commands:
  agent list                        — list all agents
  agent status <slug>               — detailed agent info
  agent activate <slug>             — activate agent
  agent deactivate <slug>           — deactivate agent
  agent events <slug>               — recent events
  agent config <slug> key=value     — update condition params
  agent help                        — this help"""
