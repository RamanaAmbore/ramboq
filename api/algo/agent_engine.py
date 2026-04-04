"""
Agent Engine — evaluates all active agents using Conditions → Alerts → Actions pipeline.

Called from background.py every refresh cycle with market data context.
Each agent's condition tree is evaluated. If triggered, alerts are dispatched
through configured channels and optional actions are executed.

The engine handles cooldown, state transitions, and WebSocket broadcasts.
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from api.algo.conditions import evaluate, EvalResult
from api.algo.events import dispatch, log_event
from api.algo.actions import execute
from api.database import async_session
from api.models import Agent
from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


# Built-in agents seeded on first startup
BUILTIN_AGENTS = [
    {
        "slug": "position_loss",
        "name": "Position Loss (Absolute)",
        "description": "Alert when day loss exceeds absolute threshold",
        "conditions": {"operator": "or", "rules": [
            {"field": "day_change_val", "op": "<", "value": -50000},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [],
        "scope": "per_account",
        "schedule": "market_hours",
        "cooldown_minutes": 30,
        "status": "active",
    },
    {
        "slug": "position_loss_pct",
        "name": "Position Loss (Percentage)",
        "description": "Alert when day loss exceeds percentage threshold",
        "conditions": {"field": "day_change_percentage", "op": "<", "value": -2.0},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [],
        "scope": "per_account",
        "schedule": "market_hours",
        "cooldown_minutes": 30,
        "status": "active",
    },
    {
        "slug": "negative_cash",
        "name": "Negative Cash Balance",
        "description": "Alert when cash balance goes below zero",
        "conditions": {"field": "cash", "op": "<", "value": 0},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [],
        "scope": "per_account",
        "schedule": "market_hours",
        "cooldown_minutes": 30,
        "status": "active",
    },
    {
        "slug": "negative_margin",
        "name": "Negative Available Margin",
        "description": "Alert when available margin goes below zero",
        "conditions": {"field": "avail_margin", "op": "<", "value": 0},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [],
        "scope": "per_account",
        "schedule": "market_hours",
        "cooldown_minutes": 30,
        "status": "active",
    },
    {
        "slug": "nse_open_summary",
        "name": "NSE Open Summary",
        "description": "Send portfolio summary 15 min after NSE market open",
        "conditions": {"operator": "and", "rules": [
            {"field": "nse_open", "op": "==", "value": True},
            {"field": "minutes_since_nse_open", "op": "==", "value": 15},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [{"type": "send_summary", "params": {"summary_type": "open", "segments": ["equity"]}}],
        "scope": "total",
        "schedule": "market_hours",
        "cooldown_minutes": 1440,
        "status": "active",
    },
    {
        "slug": "nse_close_summary",
        "name": "NSE Close Summary",
        "description": "Send portfolio summary 15 min after NSE market close",
        "conditions": {"operator": "and", "rules": [
            {"field": "nse_closed", "op": "==", "value": True},
            {"field": "minutes_since_nse_close", "op": ">=", "value": 15},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [{"type": "send_summary", "params": {"summary_type": "close", "segments": ["equity"]}}],
        "scope": "total",
        "schedule": "always",
        "cooldown_minutes": 1440,
        "status": "active",
    },
    {
        "slug": "mcx_open_summary",
        "name": "MCX Open Summary",
        "description": "Send portfolio summary 15 min after MCX market open",
        "conditions": {"operator": "and", "rules": [
            {"field": "mcx_open", "op": "==", "value": True},
            {"field": "minutes_since_mcx_open", "op": "==", "value": 15},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [{"type": "send_summary", "params": {"summary_type": "open", "segments": ["commodity"]}}],
        "scope": "total",
        "schedule": "market_hours",
        "cooldown_minutes": 1440,
        "status": "active",
    },
    {
        "slug": "mcx_close_summary",
        "name": "MCX Close Summary",
        "description": "Send portfolio summary 15 min after MCX market close",
        "conditions": {"operator": "and", "rules": [
            {"field": "mcx_closed", "op": "==", "value": True},
            {"field": "minutes_since_mcx_close", "op": ">=", "value": 15},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [{"type": "send_summary", "params": {"summary_type": "close", "segments": ["commodity"]}}],
        "scope": "total",
        "schedule": "always",
        "cooldown_minutes": 1440,
        "status": "active",
    },
    {
        "slug": "expiry_close",
        "name": "Expiry Auto-Close",
        "description": "Automatically close ITM option positions on expiry day",
        "conditions": {"operator": "and", "rules": [
            {"field": "is_expiry_day", "op": "==", "value": True},
            {"field": "has_itm_positions", "op": "==", "value": True},
        ]},
        "events": [
            {"channel": "telegram", "enabled": True},
            {"channel": "email", "enabled": True},
            {"channel": "log", "enabled": True},
        ],
        "actions": [{"type": "chase_close", "params": {"start_offset_hours": 2}}],
        "scope": "total",
        "schedule": "market_hours",
        "cooldown_minutes": 1440,
        "status": "active",
    },
]


async def seed_agents():
    """Insert built-in agents if they don't exist. Preserves existing config if already seeded."""
    async with async_session() as session:
        for agent_def in BUILTIN_AGENTS:
            result = await session.execute(
                select(Agent).where(Agent.slug == agent_def["slug"])
            )
            if result.scalar_one_or_none():
                continue
            agent = Agent(
                slug=agent_def["slug"],
                name=agent_def["name"],
                description=agent_def.get("description", ""),
                conditions=agent_def["conditions"],
                events=agent_def["events"],
                actions=agent_def["actions"],
                scope=agent_def.get("scope", "per_account"),
                schedule=agent_def.get("schedule", "market_hours"),
                cooldown_minutes=agent_def.get("cooldown_minutes", 30),
                status=agent_def.get("status", "active"),
                is_system=True,
            )
            session.add(agent)
        await session.commit()
    logger.info(f"Agent engine: {len(BUILTIN_AGENTS)} built-in agents verified")


def _build_context(sum_holdings, sum_positions, df_margins, now, seg_state: dict) -> dict:
    """Build the context dict for condition evaluation from market data."""
    from datetime import time as dtime
    from src.helpers.utils import config as app_config

    ctx = {"now": now}

    # Holdings summary (TOTAL row)
    if sum_holdings is not None and not sum_holdings.empty:
        total = sum_holdings[sum_holdings["account"] == "TOTAL"]
        if not total.empty:
            row = total.iloc[0]
            ctx["day_change_val"] = float(row.get("day_change_val", 0) or 0)
            ctx["day_change_percentage"] = float(row.get("day_change_percentage", 0) or 0)
            ctx["pnl"] = float(row.get("pnl", 0) or 0)
            ctx["cur_val"] = float(row.get("cur_val", 0) or 0)

    # Funds (TOTAL row)
    if df_margins is not None and not df_margins.empty:
        total = df_margins[df_margins["account"] == "TOTAL"]
        if not total.empty:
            row = total.iloc[0]
            ctx["cash"] = float(row.get("avail opening_balance", row.get("cash", 0)) or 0)
            ctx["avail_margin"] = float(row.get("net", row.get("avail_margin", 0)) or 0)
            ctx["used_margin"] = float(row.get("util debits", row.get("used_margin", 0)) or 0)

    # Market state per segment
    segments = app_config.get("market_segments", {})
    for seg_name, seg_cfg in segments.items():
        h, m = map(int, seg_cfg.get("hours_start", "09:15").split(":"))
        open_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        h, m = map(int, seg_cfg.get("hours_end", "15:30").split(":"))
        close_time = now.replace(hour=h, minute=m, second=0, microsecond=0)

        prefix = "nse" if seg_name == "equity" else "mcx"
        is_open = open_time <= now <= close_time
        ctx[f"{prefix}_open"] = is_open
        ctx[f"{prefix}_closed"] = now > close_time
        ctx[f"minutes_since_{prefix}_open"] = max(0, int((now - open_time).total_seconds() / 60)) if now >= open_time else 0
        ctx[f"minutes_since_{prefix}_close"] = max(0, int((now - close_time).total_seconds() / 60)) if now >= close_time else 0

    # Expiry detection
    ctx["is_expiry_day"] = False
    ctx["has_itm_positions"] = False

    return ctx


def _build_account_contexts(sum_holdings, sum_positions, df_margins, base_ctx: dict) -> list[dict]:
    """Build per-account contexts for agents with scope='per_account'."""
    contexts = []

    if sum_holdings is not None and not sum_holdings.empty:
        for _, row in sum_holdings.iterrows():
            account = str(row.get("account", ""))
            if account == "TOTAL":
                continue
            ctx = dict(base_ctx)
            ctx["account"] = account
            ctx["day_change_val"] = float(row.get("day_change_val", 0) or 0)
            ctx["day_change_percentage"] = float(row.get("day_change_percentage", 0) or 0)
            ctx["pnl"] = float(row.get("pnl", 0) or 0)

            # Find matching funds row
            if df_margins is not None and not df_margins.empty:
                acct_margin = df_margins[df_margins["account"] == account]
                if not acct_margin.empty:
                    mr = acct_margin.iloc[0]
                    ctx["cash"] = float(mr.get("avail opening_balance", mr.get("cash", 0)) or 0)
                    ctx["avail_margin"] = float(mr.get("net", mr.get("avail_margin", 0)) or 0)

            contexts.append(ctx)

    return contexts


async def run_cycle(context: dict, broadcast_fn=None):
    """
    Main agent evaluation cycle. Called from background.py every refresh.

    Args:
        context: dict with sum_holdings, sum_positions, df_margins, now, seg_state
        broadcast_fn: WebSocket broadcast function
    """
    now = context.get("now")
    if not now:
        return

    # Load active agents
    async with async_session() as session:
        result = await session.execute(
            select(Agent).where(Agent.status.in_(["active", "cooldown"]))
        )
        agents = result.scalars().all()

    if not agents:
        return

    # Build base context
    base_ctx = _build_context(
        context.get("sum_holdings"),
        context.get("sum_positions"),
        context.get("df_margins"),
        now,
        context.get("seg_state", {}),
    )

    for agent in agents:
        # Check cooldown
        if agent.status == "cooldown":
            if agent.last_triggered_at:
                elapsed = (datetime.now(timezone.utc) - agent.last_triggered_at).total_seconds() / 60
                if elapsed < agent.cooldown_minutes:
                    continue

        # Build evaluation contexts based on scope
        if agent.scope == "per_account":
            eval_contexts = _build_account_contexts(
                context.get("sum_holdings"),
                context.get("sum_positions"),
                context.get("df_margins"),
                base_ctx,
            )
        else:
            eval_contexts = [base_ctx]

        triggered = False
        for ctx in eval_contexts:
            result = evaluate(agent.conditions, ctx)
            if not result.triggered:
                continue

            triggered = True
            account = ctx.get("account", "ALL")
            result.condition_text = f"{result.condition_text} ({account})"

            # Broadcast state change
            if broadcast_fn:
                broadcast_fn("agent_state", {"slug": agent.slug, "status": "triggered"})

            # ALERT (always)
            await dispatch(agent, result, broadcast_fn)

            # ACTION (optional)
            if agent.actions:
                action_ctx = dict(context)
                action_ctx["account"] = account
                await execute(agent, agent.actions, action_ctx)

            break  # one trigger per cycle per agent

        # Update state
        async with async_session() as session:
            if triggered:
                await session.execute(
                    update(Agent).where(Agent.id == agent.id).values(
                        status="cooldown",
                        last_triggered_at=datetime.now(timezone.utc),
                        trigger_count=Agent.trigger_count + 1,
                    )
                )
            elif agent.status == "cooldown":
                await session.execute(
                    update(Agent).where(Agent.id == agent.id).values(status="active")
                )
            await session.commit()

        if broadcast_fn:
            new_status = "cooldown" if triggered else "active"
            broadcast_fn("agent_state", {"slug": agent.slug, "status": new_status})
