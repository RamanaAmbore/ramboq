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
        context: market data context
    """
    for action in actions:
        action_type = action.get("type", "")
        params = action.get("params", {})

        try:
            if action_type == "chase_close":
                await _action_chase_close(context, params)
            elif action_type == "send_summary":
                await _action_send_summary(context, params)
            elif action_type == "place_order":
                await _action_place_order(context, params)
            else:
                logger.warning(f"Agent [{agent.slug}]: unknown action type '{action_type}'")
                continue

            logger.info(f"Agent [{agent.slug}]: action '{action_type}' completed")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_success", f"Action: {action_type}", params)

        except Exception as e:
            logger.error(f"Agent [{agent.slug}]: action '{action_type}' failed: {e}")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_failed", f"Action: {action_type} — {e}", params)


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
