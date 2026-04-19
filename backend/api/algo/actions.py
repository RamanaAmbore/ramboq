"""
Agent action executor — runs automated responses when an agent triggers.

Actions are stored in Agent.actions as a JSON list:
  [{"type": "chase_close", "params": {"exchange": "NFO"}}]

Empty list means alert-only (no action taken).
"""

from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


async def execute(agent, actions: list, context: dict):
    """
    Execute action chain sequentially.

    Args:
        agent: Agent DB row
        actions: list of action dicts from agent.actions
        context: market data context (contains `sim_mode` when fired by the
                 simulator — used to route to the sim paper-trade writer
                 instead of the real broker)
    """
    sim_mode = bool(context.get("sim_mode"))
    for action in actions:
        action_type = action.get("type", "")
        params = action.get("params", {})

        try:
            if sim_mode:
                # Simulation: skip the real broker, write a mode='sim' row
                # into algo_orders so the operator can see exactly what the
                # real path would have done.
                await _sim_paper_trade(agent, action_type, params, context)
            elif action_type == "chase_close":
                await _action_chase_close(context, params)
            elif action_type == "send_summary":
                await _action_send_summary(context, params)
            elif action_type == "place_order":
                await _action_place_order(context, params)
            else:
                logger.warning(f"Agent [{agent.slug}]: unknown action type '{action_type}'")
                continue

            tag = "[SIMULATOR] " if sim_mode else ""
            logger.info(f"{tag}Agent [{agent.slug}]: action '{action_type}' completed")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_success", f"{tag}Action: {action_type}",
                            params, sim_mode=sim_mode)

        except Exception as e:
            tag = "[SIMULATOR] " if sim_mode else ""
            logger.error(f"{tag}Agent [{agent.slug}]: action '{action_type}' failed: {e}")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_failed",
                            f"{tag}Action: {action_type} — {e}",
                            params, sim_mode=sim_mode)


async def _sim_paper_trade(agent, action_type: str, params: dict, context: dict):
    """
    Record a paper-trade row in algo_orders with mode='sim' for every action
    fired by a simulator run. Leaves no side-effect at the broker — visibility
    only.
    """
    from backend.api.database import async_session
    from backend.api.models import AlgoOrder

    detail = f"[SIMULATOR] agent={agent.slug} action={action_type} params={params}"
    logger.warning(f"[SIMULATOR] paper-trade: {detail}")

    if action_type not in {"place_order", "chase_close", "chase_close_positions"}:
        # Non-order actions (emit_log, set_flag, monitor_order, deactivate_agent,
        # send_summary, cancel_*) get logged above via log_event — no paper row.
        return

    try:
        async with async_session() as s:
            row = AlgoOrder(
                account=str(params.get("account") or "SIM"),
                symbol=str(params.get("symbol") or f"{agent.slug}-{action_type}"),
                exchange=str(params.get("exchange") or "NFO"),
                transaction_type=str(params.get("transaction_type") or "SELL"),
                quantity=int(params.get("quantity") or 0),
                status="simulated",
                engine="sim",
                mode="sim",
                detail=detail,
            )
            s.add(row)
            await s.commit()
    except Exception as e:
        logger.error(f"[SIMULATOR] paper-trade write failed: {e}")


async def _action_chase_close(context: dict, params: dict):
    """Close positions using the adaptive chase engine."""
    from backend.api.algo.expiry import ExpiryEngine

    engine = ExpiryEngine()
    to_close = engine.scan_positions()
    if to_close:
        await engine.close_positions(to_close)


async def _action_send_summary(context: dict, params: dict):
    """Send portfolio summary via existing send_summary."""
    from backend.shared.helpers.alert_utils import send_summary
    import asyncio

    segments = params.get("segments", ["equity", "commodity"])
    summary_type = params.get("summary_type", "open")

    sum_holdings = context.get("sum_holdings")
    sum_positions = context.get("sum_positions")
    df_margins = context.get("df_margins")
    ist_display = context.get("ist_display", "")

    if sum_holdings is None:
        return

    for seg_name in segments:
        label = seg_name.capitalize()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: send_summary(sum_holdings, sum_positions, ist_display,
                                 summary_type, label=label, df_margins=df_margins),
        )


async def _action_place_order(context: dict, params: dict):
    """Place an order using the chase engine."""
    from backend.api.algo.chase import chase_order, ChaseConfig

    cfg = ChaseConfig(
        exchange=params.get("exchange", "NFO"),
        product=params.get("product", "NRML"),
    )
    await chase_order(
        account=params.get("account", ""),
        symbol=params.get("symbol", ""),
        transaction_type=params.get("transaction_type", "SELL"),
        quantity=params.get("quantity", 0),
        cfg=cfg,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  NEW-GRAMMAR ACTION HANDLERS
#
#  Referenced by dotted path from the grammar_tokens seed (see grammar.py).
#  Each handler has the signature (ctx, params) → result dict.
#  Stubs at this phase — they log the invocation so the pipeline can be
#  exercised end-to-end before real broker calls land.
# ═══════════════════════════════════════════════════════════════════════════

def _log_invoke(action: str, params: dict) -> dict:
    logger.info(f"Agent action invoked: {action} params={params}")
    return {"action": action, "status": "logged", "params": params}


async def place_order(ctx, params: dict) -> dict:
    """Place a new broker order — wiring pending full action-runner landing."""
    return _log_invoke("place_order", params)


async def modify_order(ctx, params: dict) -> dict:
    return _log_invoke("modify_order", params)


async def cancel_order(ctx, params: dict) -> dict:
    return _log_invoke("cancel_order", params)


async def cancel_all_orders(ctx, params: dict) -> dict:
    return _log_invoke("cancel_all_orders", params)


async def chase_close_positions(ctx, params: dict) -> dict:
    """
    Close every open position in scope via the adaptive chase engine.
    Delegates to ExpiryEngine primitives once the action runner lands.
    """
    return _log_invoke("chase_close_positions", params)


async def monitor_order(ctx, params: dict) -> dict:
    return _log_invoke("monitor_order", params)


async def deactivate_agent(ctx, params: dict) -> dict:
    return _log_invoke("deactivate_agent", params)


async def set_flag(ctx, params: dict) -> dict:
    return _log_invoke("set_flag", params)


async def emit_log(ctx, params: dict) -> dict:
    level   = (params.get("level") or "info").lower()
    message = params.get("message", "")
    getattr(logger, level, logger.info)(f"Agent emit_log: {message}")
    return {"action": "emit_log", "status": "logged", "level": level, "message": message}
