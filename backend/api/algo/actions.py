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
            elif action_type == "close_position":
                # Live path: currently a stub — logs and returns. Real
                # broker wiring lands with the action runner. Sim path
                # never reaches here because sim_mode routes to
                # _sim_paper_trade above.
                await close_position(context, params)
            else:
                logger.warning(f"Agent [{agent.slug}]: unknown action type '{action_type}'")
                continue

            tag = "[SIM] " if sim_mode else ""
            logger.info(f"{tag}Agent [{agent.slug}]: action '{action_type}' completed")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_success", f"{tag}Action: {action_type}",
                            params, sim_mode=sim_mode)

        except Exception as e:
            tag = "[SIM] " if sim_mode else ""
            logger.error(f"{tag}Agent [{agent.slug}]: action '{action_type}' failed: {e}")
            from backend.api.algo.events import log_event
            await log_event(agent, "action_failed",
                            f"{tag}Action: {action_type} — {e}",
                            params, sim_mode=sim_mode)


def _sim_ltp_for(account: str, symbol: str) -> tuple[float | None, int | None]:
    """
    Look up the current simulated last_price + signed quantity for
    (account, symbol) from the SimDriver's per-symbol state. Used by
    paper-trade writers so the AlgoOrder row carries the LIMIT price the
    sim would have submitted to the broker.

    Returns (None, None) when the symbol isn't in the sim state — the
    writer then falls back to the price param or leaves the column null.
    """
    try:
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        for row in getattr(drv, "_positions_rows", []):
            if str(row.get("account")) == str(account) and \
               str(row.get("tradingsymbol")) == str(symbol):
                lp = row.get("last_price")
                qty = row.get("quantity")
                return (float(lp) if lp is not None else None,
                        int(qty)  if qty is not None else None)
    except Exception:
        pass
    return None, None


def _sim_positions_in_scope(params: dict) -> list[dict]:
    """
    Return the per-symbol position rows that a scope-level action like
    `chase_close_positions` would hit in real life. Used when a
    scope-only action fires in sim — we expand it into one paper-trade
    per actual position so the Order / Simulator logs show real
    account / symbol / qty / LTP instead of a placeholder.

    `params.scope`: 'total' (default) → every position in the sim
                    'account'         → positions filtered by params.account
    """
    scope = (params.get("scope") or "total").lower()
    acct_filter = str(params.get("account") or "") if scope == "account" else None
    try:
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        rows = getattr(drv, "_positions_rows", []) or []
        if acct_filter:
            rows = [r for r in rows if str(r.get("account")) == acct_filter]
        return list(rows)
    except Exception:
        return []


async def _write_sim_order(agent, action_type: str, resolved: dict):
    """
    Write ONE AlgoOrder row (mode='sim') + push a 'kind=order' entry to
    the sim driver's tick log so the Order + Simulator tabs both show
    the full order details. `resolved` must contain real
    account / symbol / side / qty / price — callers resolve these from
    either the action params (close_position, place_order) or from the
    sim's per-symbol state (chase_close_positions expands per-position).
    """
    from backend.api.database import async_session
    from backend.api.models import AlgoOrder

    account = resolved["account"]
    symbol  = resolved["symbol"]
    side    = resolved["side"]
    qty     = int(resolved["qty"] or 0)
    price   = resolved.get("price")
    exchange = resolved.get("exchange") or "NFO"

    # Human-readable print-style line — shows up as logger.warning AND as
    # the AlgoOrder.detail column AND inside the tick_log entry so the
    # operator sees the same sentence in all three places.
    price_str = f"@₹{price:,.2f}" if price is not None else "@MARKET"
    pretty = (f"[SIM] {agent.slug} → {action_type}: {side} {qty} "
              f"{symbol} {price_str} · acct={account}")
    logger.warning(pretty)

    try:
        async with async_session() as s:
            s.add(AlgoOrder(
                account=account, symbol=symbol, exchange=exchange,
                transaction_type=side, quantity=qty,
                initial_price=(float(price) if price is not None else None),
                status="simulated", engine="sim", mode="sim",
                detail=pretty,
            ))
            await s.commit()
    except Exception as e:
        logger.error(f"[SIM] paper-trade write failed: {e}")
        return

    try:
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        drv._tick_log.append({
            "ts":         __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "tick_index": drv.tick_index,
            "scenario":   drv.scenario_slug,
            "kind":       "order",
            "moves":      [],
            "changes":    [],
            "note":       pretty,
            "order": {
                "account": account, "symbol": symbol, "side": side, "qty": qty,
                "price":   (float(price) if price is not None else None),
                "agent":   agent.slug, "action": action_type,
            },
        })
    except Exception as e:
        logger.debug(f"[SIM] could not record order in tick_log: {e}")


async def _sim_paper_trade(agent, action_type: str, params: dict, context: dict):
    """
    Paper-trade dispatcher for sim-mode action fires.

    - `close_position` / `place_order` — params already specify
      account + symbol; write ONE AlgoOrder using those params, with
      the LIMIT price = sim's current LTP for that symbol.
    - `chase_close_positions` / `chase_close` — scope-level actions.
      Expand into ONE paper-trade per open position in scope, each
      carrying the real account / symbol / qty / LTP. Operators see a
      realistic picture of what the chase engine would have tried to
      close.
    - Non-order actions (emit_log / set_flag / monitor_order /
      deactivate_agent / cancel_* / send_summary) — no paper row,
      just the log_event that execute() already writes.
    """
    if action_type in {"chase_close", "chase_close_positions"}:
        positions = _sim_positions_in_scope(params)
        if not positions:
            # Scope matched nothing — still record one row so the fire is
            # visible in the logs, but make it obvious nothing closed.
            logger.warning(f"[SIM] {agent.slug} → {action_type}: scope matched 0 positions")
            await _write_sim_order(agent, action_type, {
                "account": str(params.get("account") or "TOTAL"),
                "symbol":  "(no positions in scope)",
                "side":    "SELL", "qty": 0, "price": None,
                "exchange": "NFO",
            })
            return
        for p in positions:
            qty_held = int(p.get("quantity") or 0)
            await _write_sim_order(agent, action_type, {
                "account":  str(p.get("account", "SIM")),
                "symbol":   str(p.get("tradingsymbol", "")),
                "side":     "SELL" if qty_held > 0 else "BUY",
                "qty":      abs(qty_held),
                "price":    p.get("last_price"),
                "exchange": str(p.get("exchange") or "NFO"),
            })
        return

    if action_type in {"place_order", "close_position"}:
        account = str(params.get("account") or "SIM")
        symbol  = str(params.get("symbol")  or f"{agent.slug}-{action_type}")
        ltp, qty_held = _sim_ltp_for(account, symbol)
        if params.get("side") in ("BUY", "SELL"):
            side = params.get("side")
        elif params.get("transaction_type") in ("BUY", "SELL"):
            side = params.get("transaction_type")
        elif qty_held is not None:
            side = "SELL" if qty_held > 0 else "BUY"
        else:
            side = "SELL"
        if params.get("quantity") is not None:
            qty = int(params.get("quantity") or 0)
        elif qty_held is not None:
            qty = abs(int(qty_held))
        else:
            qty = 0
        price = ltp if ltp is not None else params.get("price")
        await _write_sim_order(agent, action_type, {
            "account":  account,
            "symbol":   symbol,
            "side":     side,
            "qty":      qty,
            "price":    price,
            "exchange": str(params.get("exchange") or "NFO"),
        })
        return

    # Non-order action — no paper row. The log_event call in execute()
    # already captures the action_success event.


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


async def close_position(ctx, params: dict) -> dict:
    """
    One-shot close of a single position with a LIMIT order at current LTP.

    Live mode: wiring pending the action runner landing — logs the
    invocation so the pipeline is exercised end-to-end without touching
    the broker.

    Sim mode: dispatched through `_sim_paper_trade` upstream (execute() in
    this module routes on ctx['sim_mode']), which records an AlgoOrder
    with initial_price = sim's current LTP for the symbol. So this
    handler is the LIVE path only.
    """
    return _log_invoke("close_position", params)


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
