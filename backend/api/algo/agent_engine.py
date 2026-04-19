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

from backend.api.algo.conditions import evaluate, EvalResult
from backend.api.algo.events import dispatch, log_event
from backend.api.algo.actions import execute
from backend.api.algo.agent_evaluator import Context as V2Context, evaluate as v2_evaluate
from backend.api.database import async_session
from backend.api.models import Agent
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config as app_config

logger = get_logger(__name__)


# Module-level per-agent suppression state for v2-grammar agents.
# Keyed by agent slug: {'ts': datetime, 'pnl': float, 'pct': float}.
# Survives across ticks but is wiped daily by _maybe_reset_v2_state below.
_V2_LAST_ALERT: dict[str, dict] = {}
_V2_LAST_RESET_DATE = None


def _maybe_reset_v2_state(today):
    """Wipe v2 suppression state once per new trading day."""
    global _V2_LAST_RESET_DATE
    if _V2_LAST_RESET_DATE != today:
        _V2_LAST_RESET_DATE = today
        _V2_LAST_ALERT.clear()


# ---------------------------------------------------------------------------
# v2 condition-tree helpers
# ---------------------------------------------------------------------------

def _is_v2_conditions(cond) -> bool:
    """
    True when `cond` uses the new grammar (metric/scope leaves, or
    all/any/not composites). v1 agents use `field` leaves and `operator/rules`
    composites — those stay on the legacy evaluator.
    """
    if not isinstance(cond, dict):
        return False
    if 'all' in cond or 'any' in cond or 'not' in cond:
        return True
    return 'metric' in cond and 'scope' in cond


def _v2_has_rate_metric(cond) -> bool:
    """
    Walk the tree looking for any leaf whose metric is a rate_* metric. When
    present, the engine applies the opening-gap baseline gate to the whole
    agent. This keeps the per-agent config simple — operator does not have
    to set a baseline flag; the engine infers it from the tree.
    """
    if not isinstance(cond, dict):
        return False
    for key in ('all', 'any'):
        if key in cond:
            return any(_v2_has_rate_metric(c) for c in (cond.get(key) or []))
    if 'not' in cond:
        return _v2_has_rate_metric(cond['not'])
    m = cond.get('metric', '') or ''
    return '_rate_' in m


def _v2_baseline_live(alert_state, now, offset_min: float) -> bool:
    start = alert_state.get('session_start') if alert_state else None
    if not start:
        return False
    from datetime import timedelta
    return (now - start) >= timedelta(minutes=offset_min)


def _v2_build_evalresult(matches, agent_name: str) -> EvalResult:
    """
    Wrap v2 matches into an EvalResult so the existing dispatch() function
    (which renders the Telegram/email body) can consume them unchanged.
    """
    # Compact one-liner per match: "scope metric=value (threshold)"
    lines = []
    for m in matches[:10]:  # cap — long lists get truncated
        val = m.get('value')
        try:
            val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
        except Exception:
            val_str = str(val)
        lines.append(
            f"{m.get('scope','?')} {m.get('metric','?')}={val_str} "
            f"({m.get('op','?')} {m.get('threshold','?')})"
        )
    if len(matches) > 10:
        lines.append(f"... +{len(matches) - 10} more")
    condition_text = " | ".join(lines) or agent_name
    return EvalResult(
        triggered=bool(matches),
        condition_text=condition_text,
        detail={'matches': matches, 'grammar': 'v2'},
    )


# ─── v2 rich-body Telegram + email ────────────────────────────────────────
#
# For v2 agents we bypass the generic dispatch() body and use the same
# narrow-mobile Telegram format + coloured HTML email table that the legacy
# alert_utils engine already produces. Keeping the user-facing shape
# consistent across both engines makes parity testing trivial — the
# operator can spot-diff two messages and only care about the agent slug.

def _v2_match_to_alertrow(match: dict) -> dict:
    """
    Convert a v2 evaluator match into the alert-row dict shape consumed by
    alert_utils._tg_alert_body / _email_alert_body.
    """
    scope_tok = match.get('scope', '') or ''
    metric    = match.get('metric', '') or ''
    row       = match.get('row')      or {}
    value     = match.get('value')
    threshold = match.get('threshold')

    # section — derived from scope token prefix
    if scope_tok.startswith('holdings'):
        section = 'Holdings'
    elif scope_tok.startswith('positions'):
        section = 'Positions'
    else:
        section = 'Funds'

    # kind — derived from metric token. Drives row colour / label.
    if   metric in ('cash',):                kind = 'negative_cash'
    elif metric in ('avail_margin',):        kind = 'negative_margin'
    elif '_rate_abs' in metric:              kind = 'rate_abs'
    elif '_rate_pct' in metric:              kind = 'rate_pct'
    elif metric.endswith('_pct') or metric == 'pnl_pct':  kind = 'static_pct'
    else:                                    kind = 'static_abs'

    # pnl — section-appropriate ₹ value. For rate alerts we still want the
    # current raw pnl/day_val shown, plus the rate value in rate_val.
    if section == 'Holdings':
        pnl = float(row.get('day_change_val', 0) or 0)
        pct = float(row.get('day_change_percentage', 0) or 0) if row.get('day_change_percentage') is not None else None
    elif section == 'Positions':
        pnl = float(row.get('pnl', 0) or 0)
        pct = None  # computed later only when we have used_margin
    else:  # Funds
        if metric == 'cash':
            pnl = float(row.get('avail opening_balance', 0) or 0)
        elif metric == 'avail_margin':
            pnl = float(row.get('net', 0) or 0)
        else:
            pnl = float(value or 0)
        pct = None

    rate_val = value if kind in ('rate_abs', 'rate_pct') else None

    # threshold display — format with units appropriate to the kind
    try:
        thr = float(threshold)
        if kind in ('static_pct', 'rate_pct'):
            thr_str = f"{thr:.2f}%" + ("/min" if kind == 'rate_pct' else "")
        elif kind in ('static_abs', 'rate_abs', 'negative_cash', 'negative_margin'):
            thr_str = f"-₹{abs(thr):,.0f}" + ("/min" if kind == 'rate_abs' else "")
        else:
            thr_str = str(threshold)
    except Exception:
        thr_str = str(threshold)

    scope_label = str(row.get('account', 'TOTAL'))

    return dict(
        section=section, scope=scope_label, kind=kind,
        pnl=pnl, pct=pct, rate_val=rate_val, threshold=thr_str,
    )


async def _v2_send_rich_alert(agent, matches, now):
    """
    Render the v2 alert as the same narrow-TG + HTML-table format the legacy
    engine uses, and send through Telegram + email via alert_utils's own
    dispatcher (which already branch-tags and honours is_enabled gates).
    Returns True when at least one channel was attempted.
    """
    # Late import avoids the agent_engine → alert_utils cycle at import time.
    from backend.shared.helpers.alert_utils import (
        _tg_alert_body, _email_alert_body, _dispatch,
    )
    from backend.shared.helpers.date_time_utils import timestamp_display

    rows = [_v2_match_to_alertrow(m) for m in matches]
    if not rows:
        return False

    # Sort Holdings → Positions → Funds, per-account before TOTAL (same as
    # alert_utils).
    order = {'Holdings': 0, 'Positions': 1, 'Funds': 2}
    rows.sort(key=lambda r: (order.get(r['section'], 9),
                              0 if r['scope'] != 'TOTAL' else 1,
                              r['scope']))

    tg_body    = _tg_alert_body(rows)
    email_html = _email_alert_body(rows)
    subject    = f"Agent {agent.slug}"
    try:
        _dispatch('alert', timestamp_display(), tg_body, email_html, subject)
    except Exception as e:
        logger.error(f"Agent [{agent.slug}] rich alert send failed: {e}")
        return False
    return True


def _v2_should_suppress(agent, matches, now, cfg) -> bool:
    """
    Per-agent suppression for v2 grammar. Matches the semantics of the old
    alert_utils _suppress gate: re-fire requires cooldown elapsed AND a
    material change in the worst-case value across matches.
    """
    from datetime import timedelta

    # Use the WORST (smallest / most-negative) value across matches as the
    # representative loss number for delta comparisons.
    worst_val = None
    for m in matches:
        v = m.get('value')
        if v is None:
            continue
        if worst_val is None or v < worst_val:
            worst_val = v
    if worst_val is None:
        return False  # no useful value — allow fire

    prev = _V2_LAST_ALERT.get(agent.slug)
    if not prev:
        return False
    if (now - prev['ts']) < timedelta(minutes=cfg['cooldown_min']):
        return True
    abs_moved = abs(worst_val - prev.get('val', 0)) >= cfg['suppress_delta_abs']
    pct_moved = False  # v2 matches carry a single number; pct-delta omitted by design
    return not (abs_moved or pct_moved)


def _v2_record(agent, matches, now) -> None:
    worst_val = None
    for m in matches:
        v = m.get('value')
        if v is None:
            continue
        if worst_val is None or v < worst_val:
            worst_val = v
    _V2_LAST_ALERT[agent.slug] = {'ts': now, 'val': worst_val if worst_val is not None else 0.0}


def _v2_cfg():
    """Read the small set of gate/suppression parameters from backend_config.yaml."""
    g = app_config.get
    return {
        'rate_window_min':       float(g('alert_rate_window_min', 10)),
        'baseline_offset_min':   float(g('alert_baseline_offset_min', 15)),
        'cooldown_min':          float(g('alert_cooldown_minutes', 30)),
        'suppress_delta_abs':    float(g('alert_suppress_delta_abs', 15000)),
        'suppress_delta_pct':    float(g('alert_suppress_delta_pct', 0.5)),
    }


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
        "status": "inactive",
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
        "status": "inactive",
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
        "status": "inactive",
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
        "status": "inactive",
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


# ═══════════════════════════════════════════════════════════════════════════
#  New-grammar loss-rule agents
# ═══════════════════════════════════════════════════════════════════════════
#
# Every risk rule from alert_utils' hard-coded engine is expressed here as an
# Agent row whose `conditions` is a v2 grammar tree (metric/scope/op/value).
# Seeded INACTIVE so they do not duplicate the alerts still coming out of
# alert_utils.check_and_alert. Activate one at a time from the /algo UI to
# run it under the new evaluator; when all parity is confirmed, retire the
# corresponding arm in alert_utils.
#
# Notify channels + cooldown come from the same defaults used today.
# Suppression deltas and the baseline-gate offset are engine-wide settings
# still read from backend_config.yaml (alert_suppress_delta_abs,
# alert_suppress_delta_pct, alert_baseline_offset_min).

_LOSS_AGENTS = [
    # ── Holdings: static % floors ────────────────────────────────────────
    dict(slug="loss-hold-acct-static-pct",
         name="Holdings per-account day loss ≥ 3%",
         description="Fires when any individual account's holdings day loss crosses the per-account % floor.",
         conditions={"metric": "day_pct", "scope": "holdings.any_acct", "op": "<=", "value": -3.0},
         scope="total",  # scope token inside the condition already handles per-account
         ),
    dict(slug="loss-hold-total-static-pct",
         name="Holdings total day loss ≥ 5%",
         description="Fires when the portfolio total holdings day loss crosses the total % floor.",
         conditions={"metric": "day_pct", "scope": "holdings.total", "op": "<=", "value": -5.0},
         scope="total",
         ),

    # ── Positions: static % floors ───────────────────────────────────────
    dict(slug="loss-pos-acct-static-pct",
         name="Positions per-account loss ≥ 2% of margin",
         description="Fires when any account's positions pnl is ≤ −2% of that account's used margin.",
         conditions={"metric": "pnl_pct", "scope": "positions.any_acct", "op": "<=", "value": -2.0},
         scope="total",
         ),
    dict(slug="loss-pos-total-static-pct",
         name="Positions total loss ≥ 2% of margin",
         description="Fires when the portfolio total positions pnl is ≤ −2% of total used margin.",
         conditions={"metric": "pnl_pct", "scope": "positions.total", "op": "<=", "value": -2.0},
         scope="total",
         ),

    # ── Positions: static ₹ floors ───────────────────────────────────────
    dict(slug="loss-pos-acct-static-abs",
         name="Positions per-account loss ≥ ₹30,000",
         description="Fires when any account's positions pnl is ≤ −₹30,000.",
         conditions={"metric": "pnl", "scope": "positions.any_acct", "op": "<=", "value": -30000},
         scope="total",
         ),
    dict(slug="loss-pos-total-static-abs",
         name="Positions total loss ≥ ₹50,000",
         description="Fires when the portfolio total positions pnl is ≤ −₹50,000.",
         conditions={"metric": "pnl", "scope": "positions.total", "op": "<=", "value": -50000},
         scope="total",
         ),

    # ── Rate-of-change: holdings ────────────────────────────────────────
    dict(slug="loss-hold-acct-rate-abs",
         name="Holdings per-account bleeding ≥ ₹2k/min",
         description="Fires when any account's holdings day-change rate of loss is steeper than ₹2,000/min.",
         conditions={"metric": "day_rate_abs", "scope": "holdings.any_acct", "op": "<=", "value": -2000},
         scope="total",
         ),
    dict(slug="loss-hold-total-rate-abs",
         name="Holdings total bleeding ≥ ₹4k/min",
         description="Fires when the portfolio total holdings day-change rate of loss is steeper than ₹4,000/min.",
         conditions={"metric": "day_rate_abs", "scope": "holdings.total", "op": "<=", "value": -4000},
         scope="total",
         ),
    dict(slug="loss-hold-any-rate-pct",
         name="Holdings bleeding ≥ 0.15 %/min",
         description="Fires on any scope whose holdings %-of-value day rate is worse than 0.15 %/min.",
         conditions={"any": [
             {"metric": "day_rate_pct", "scope": "holdings.any_acct", "op": "<=", "value": -0.15},
             {"metric": "day_rate_pct", "scope": "holdings.total",    "op": "<=", "value": -0.15},
         ]},
         scope="total",
         ),

    # ── Rate-of-change: positions ────────────────────────────────────────
    dict(slug="loss-pos-acct-rate-abs",
         name="Positions per-account bleeding ≥ ₹3k/min",
         description="Fires when any account's positions pnl rate of loss is steeper than ₹3,000/min.",
         conditions={"metric": "pnl_rate_abs", "scope": "positions.any_acct", "op": "<=", "value": -3000},
         scope="total",
         ),
    dict(slug="loss-pos-total-rate-abs",
         name="Positions total bleeding ≥ ₹6k/min",
         description="Fires when the portfolio total positions pnl rate of loss is steeper than ₹6,000/min.",
         conditions={"metric": "pnl_rate_abs", "scope": "positions.total", "op": "<=", "value": -6000},
         scope="total",
         ),
    dict(slug="loss-pos-any-rate-pct",
         name="Positions bleeding ≥ 0.25 %/min",
         description="Fires on any scope whose positions %-of-margin rate is worse than 0.25 %/min.",
         conditions={"any": [
             {"metric": "pnl_rate_pct", "scope": "positions.any_acct", "op": "<=", "value": -0.25},
             {"metric": "pnl_rate_pct", "scope": "positions.total",    "op": "<=", "value": -0.25},
         ]},
         scope="total",
         ),

    # ── Funds: operational negatives ────────────────────────────────────
    dict(slug="loss-funds-cash-negative",
         name="Account cash has gone negative",
         description="Fires when any account's cash balance dips below zero.",
         conditions={"metric": "cash", "scope": "funds.any_acct", "op": "<", "value": 0},
         scope="total",
         ),
    dict(slug="loss-funds-margin-negative",
         name="Account available margin has gone negative",
         description="Fires when any account's available margin dips below zero.",
         conditions={"metric": "avail_margin", "scope": "funds.any_acct", "op": "<", "value": 0},
         scope="total",
         ),
]


# Enrich each row with the common notify + cooldown shape so BUILTIN_AGENTS
# keeps its existing keys; the engine's scheduler reads these fields.
_LOSS_AGENT_DEFAULTS = dict(
    events=[
        {"channel": "telegram", "enabled": True},
        {"channel": "email",    "enabled": True},
        {"channel": "log",      "enabled": True},
    ],
    actions=[],                 # notify-only. Attach actions via admin UI later.
    schedule="market_hours",
    cooldown_minutes=30,
    status="inactive",          # activated manually per rule during migration
)

for _a in _LOSS_AGENTS:
    for _k, _v in _LOSS_AGENT_DEFAULTS.items():
        _a.setdefault(_k, _v)
BUILTIN_AGENTS.extend(_LOSS_AGENTS)


async def seed_agents():
    """
    Insert built-in agents if missing. For existing system agents, sync
    schedule and (for inactive-by-default definitions) status — without
    overwriting user-tuned conditions/cooldown/events/actions.
    """
    async with async_session() as session:
        for agent_def in BUILTIN_AGENTS:
            result = await session.execute(
                select(Agent).where(Agent.slug == agent_def["slug"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                # Always sync schedule (new field enforcement)
                if existing.schedule != agent_def.get("schedule", "market_hours"):
                    existing.schedule = agent_def.get("schedule", "market_hours")
                # Force status to "inactive" only when the built-in definition
                # says inactive (keeps user-disabled agents disabled too).
                if agent_def.get("status") == "inactive" and existing.status == "active":
                    existing.status = "inactive"
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
    from backend.shared.helpers.utils import config as app_config

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

    # Market state per segment (with holiday awareness)
    from backend.shared.helpers.broker_apis import fetch_holidays

    segments = app_config.get("market_segments", {})
    for seg_name, seg_cfg in segments.items():
        h, m = map(int, seg_cfg.get("hours_start", "09:15").split(":"))
        open_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        h, m = map(int, seg_cfg.get("hours_end", "15:30").split(":"))
        close_time = now.replace(hour=h, minute=m, second=0, microsecond=0)

        prefix = "nse" if seg_name == "equity" else "mcx"
        holiday_exchange = seg_cfg.get("holiday_exchange", "NSE")

        # Check if today is a holiday or weekend
        try:
            holidays = fetch_holidays(holiday_exchange)
        except Exception:
            holidays = set()

        is_holiday = now.date() in holidays
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
        in_time_range = open_time <= now <= close_time
        is_open = in_time_range and not is_holiday and not is_weekend

        ctx[f"{prefix}_open"] = is_open
        ctx[f"{prefix}_closed"] = (now > close_time) and not is_holiday and not is_weekend
        ctx[f"{prefix}_holiday"] = is_holiday
        ctx[f"minutes_since_{prefix}_open"] = max(0, int((now - open_time).total_seconds() / 60)) if now >= open_time and is_open else 0
        ctx[f"minutes_since_{prefix}_close"] = max(0, int((now - close_time).total_seconds() / 60)) if now > close_time and not is_holiday else 0

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

    # Determine whether NSE/MCX are currently open (for schedule filtering)
    nse_open_flag = bool(base_ctx.get("nse_open"))
    mcx_open_flag = bool(base_ctx.get("mcx_open"))
    any_market_open = nse_open_flag or mcx_open_flag

    for agent in agents:
        # Enforce schedule: "market_hours" agents only run while some market is open
        if agent.schedule == "market_hours" and not any_market_open:
            continue
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

        # ──────────────────────────────────────────────────────────────────
        # v2 grammar dispatch: metric/scope leaves or all/any/not composites
        # go through backend.api.algo.agent_evaluator. Baseline gate and
        # suppression are applied here rather than inside the evaluator so
        # the evaluator stays a pure tree walker.
        # ──────────────────────────────────────────────────────────────────
        if _is_v2_conditions(agent.conditions):
            alert_state = context.get("alert_state") or {}
            _maybe_reset_v2_state(now.date() if hasattr(now, 'date') else None)
            cfg = _v2_cfg()

            # Baseline gate: skip every rate-based agent for the first N min
            # of the session to avoid the opening-gap firing rate alerts.
            if _v2_has_rate_metric(agent.conditions) and not _v2_baseline_live(
                    alert_state, now, cfg['baseline_offset_min']):
                continue

            v2_ctx = V2Context(
                sum_holdings=context.get("sum_holdings"),
                sum_positions=context.get("sum_positions"),
                df_margins=context.get("df_margins"),
                alert_state=alert_state,
                now=now,
                segments=context.get("segments", []),
                rate_window_min=cfg['rate_window_min'],
                agent=agent,
            )

            try:
                matches = v2_evaluate(agent.conditions, v2_ctx)
            except Exception as e:
                logger.error(f"Agent [{agent.slug}] v2 evaluate failed: {e}")
                matches = []

            if matches and not _v2_should_suppress(agent, matches, now, cfg):
                triggered = True
                result = _v2_build_evalresult(matches, agent.name)
                _v2_record(agent, matches, now)

                if broadcast_fn:
                    broadcast_fn("agent_state", {"slug": agent.slug, "status": "triggered"})

                # Send the rich narrow-TG + coloured HTML table message via
                # alert_utils._dispatch. Fall back to the generic dispatch()
                # path on any failure so the log / WebSocket channel still
                # carries a record of the fire.
                rich_sent = await _v2_send_rich_alert(agent, matches, now)
                if not rich_sent:
                    await dispatch(agent, result, broadcast_fn)
                else:
                    from backend.api.algo.events import log_event
                    await log_event(agent, 'triggered', result.condition_text)
                    if broadcast_fn:
                        broadcast_fn('agent_alert', {
                            'slug': agent.slug,
                            'message': result.condition_text,
                            'timestamp': now.isoformat(),
                        })

                if agent.actions:
                    action_ctx = dict(context)
                    action_ctx["account"] = "TOTAL"
                    await execute(agent, agent.actions, action_ctx)
        else:
            # Legacy v1 path — unchanged.
            for ctx in eval_contexts:
                result = evaluate(agent.conditions, ctx)
                if not result.triggered:
                    continue

                triggered = True
                account = ctx.get("account", "ALL")
                result.condition_text = f"{result.condition_text} ({account})"

                if broadcast_fn:
                    broadcast_fn("agent_state", {"slug": agent.slug, "status": "triggered"})
                await dispatch(agent, result, broadcast_fn)
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
