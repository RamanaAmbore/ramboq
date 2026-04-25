"""
Paper trade engine — simulates the order lifecycle (place → modify →
fill / unfilled) against any `QuoteSource`.

This is the same fill/modify/unfilled state machine that previously
lived inside `SimDriver._chase_open_orders`, lifted out so it can be
shared between two consumers:

  - **Mode 1, simulator** — `SimDriver` constructs a PaperTradeEngine
    fed by `SimQuoteSource`. Each scenario tick applies fabricated
    moves, then calls `engine.step()` to walk the open-order book
    against the new bid/ask.
  - **Mode 2, real-data paper** — a singleton PaperTradeEngine fed by
    `LiveQuoteSource`. A standalone background tick (every ~5 s on
    main during market hours) calls `engine.step()` so paper orders
    fill at realistic live prices without ever hitting Kite's order
    endpoint.

The engine writes terminal state back to `algo_orders` (mode='sim' or
mode='paper' set by the caller) so the existing Order log surface
shows paper rows the same way it shows live and sim rows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Optional

from backend.api.algo.quote import QuoteSource
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class PaperTradeEngine:
    """
    Owns an in-memory open-order book and a chase loop. Constructor
    parameters:

      `quote_source`   — required; supplies bid/ask each tick.
      `label`          — short tag for log lines / detail strings
                         ("sim" or "paper"). Default "paper".
      `get_max_attempts` — zero-arg callable returning the chase cap.
                          Default reads `simulator.chase_max_attempts`
                          live so a /admin/settings tweak applies on
                          the next tick.
      `on_event`       — optional callback `(event_dict) → None` —
                         receives every chase event (fill / modify /
                         unfilled) so the simulator can forward them
                         into its tick log; mode 2 keeps its own.
    """

    def __init__(
        self,
        *,
        quote_source: QuoteSource,
        label: str = "paper",
        get_max_attempts: Optional[Callable[[], int]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._quote = quote_source
        self._label = label
        self._get_max = get_max_attempts or self._default_max_attempts
        self._on_event = on_event or (lambda evt: None)

        # Open paper orders. Each entry is the dict the caller registered
        # plus a runtime-managed `status` / `attempts` / `placed_at` set.
        self._open_orders: list[dict] = []
        # Tracks fire-and-forget DB-write tasks so a graceful shutdown
        # can await them.
        self._pending_updates: set = set()

    # ── Public surface ───────────────────────────────────────────────

    def register_open_order(self, order: dict) -> None:
        """
        Caller (the action handler) submits a paper order here after
        persisting the initial AlgoOrder row. Required fields:
            algo_order_id, account, symbol, side, qty,
            limit_price, initial_price, exchange,
            agent_slug, action_type
        The engine seeds status='OPEN' / attempts=0 / placed_at and
        owns the lifecycle from here on.
        """
        order.setdefault("status",    "OPEN")
        order.setdefault("attempts",  0)
        order.setdefault("placed_at", datetime.now().isoformat(timespec="seconds"))
        self._open_orders.append(order)

    def step(self) -> None:
        """
        One chase iteration. Walks every OPEN order, asks the quote
        source for its bid/ask, fills / modifies / marks unfilled. Safe
        to call from a sync simulator tick or from an async background
        loop (DB writes are scheduled via asyncio.create_task).
        """
        if not self._open_orders:
            return
        max_attempts = max(0, int(self._get_max() or 0))

        for order in list(self._open_orders):
            if order.get("status") != "OPEN":
                continue
            bid, ask = self._quote.bid_ask_for_order(order)
            if bid is None or ask is None:
                # Quote unavailable — flip to FILLED with a marker note.
                # Mirrors the simulator's "underlying position absent"
                # auto-close so stale orders can't accumulate.
                order["status"] = "FILLED"
                self._record_event(order, kind="fill",
                                   note="underlying position absent — auto-closed")
                continue

            side  = str(order.get("side") or "SELL").upper()
            limit = float(order.get("limit_price") or 0)

            fillable = (side == "SELL" and bid >= limit) or \
                       (side == "BUY"  and ask <= limit)
            if fillable:
                fill_price = bid if side == "SELL" else ask
                order["status"]     = "FILLED"
                order["fill_price"] = fill_price
                order["filled_at"]  = datetime.now().isoformat(timespec="seconds")
                self._record_event(order, kind="fill",
                                   note=f"filled @₹{fill_price:,.2f}")
                # Hand off to the quote source — sim removes the
                # filled position from its book; live is a no-op.
                self._quote.on_fill(order)
                continue

            # Not fillable — chase by re-quoting at the opposite side.
            if order.get("attempts", 0) >= max_attempts:
                order["status"] = "UNFILLED"
                self._record_event(order, kind="unfilled",
                                   note=f"gave up after {max_attempts} chase attempts")
                continue
            new_limit  = bid if side == "SELL" else ask
            prev_limit = limit
            order["limit_price"] = new_limit
            order["attempts"]    = int(order.get("attempts", 0)) + 1
            self._record_event(
                order, kind="modify",
                note=(f"chase #{order['attempts']} {side} "
                      f"₹{prev_limit:,.2f} → ₹{new_limit:,.2f}"),
            )

    async def tick_loop(self, interval_seconds: int = 5) -> None:
        """
        Mode-2 entry point — runs `step()` every `interval_seconds`
        until cancelled. Mode 1 doesn't call this; the simulator's
        scenario tick drives `step()` directly.
        """
        while True:
            try:
                self.step()
            except Exception as e:
                logger.error(f"PaperTradeEngine[{self._label}] step failed: {e}")
            await asyncio.sleep(max(1, interval_seconds))

    def has_open_orders(self) -> bool:
        return any(o.get("status") == "OPEN" for o in self._open_orders)

    def open_order_details(self) -> list[dict]:
        """Compact snapshot of in-flight chases for the UI."""
        return [
            {
                "account":       o.get("account"),
                "symbol":        o.get("symbol"),
                "side":          o.get("side"),
                "qty":           o.get("qty"),
                "limit_price":   o.get("limit_price"),
                "initial_price": o.get("initial_price"),
                "attempts":      o.get("attempts", 0),
                "status":        o.get("status"),
                "algo_order_id": o.get("algo_order_id"),
            }
            for o in self._open_orders
            if o.get("status") == "OPEN"
        ]

    def reset(self) -> None:
        """Wipe the open-order book — used by SimDriver.start()."""
        self._open_orders = []

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _default_max_attempts() -> int:
        from backend.shared.helpers.settings import get_int
        return get_int("simulator.chase_max_attempts", 5)

    def _record_event(self, order: dict, *, kind: str, note: str) -> None:
        """
        Persist a chase lifecycle event:
          1. Build the structured event payload (used by the on_event
             callback — sim forwards into its tick log).
          2. Log a one-line warning so operators tailing logs see the
             full chase history.
          3. Schedule a DB update on the AlgoOrder row so attempts /
             status / fill_price stay in sync without waiting for the
             terminal state.
        """
        tag = self._label.upper()
        evt = {
            "ts":         datetime.now().isoformat(timespec="seconds"),
            "kind":       kind,
            "label":      self._label,
            "note":       (f"[{tag}] {order.get('agent_slug','?')} · "
                           f"{order.get('action_type','?')}: "
                           f"{order.get('side')} {order.get('qty')} "
                           f"{order.get('symbol')} · {note}"),
            "order": {
                "account":       order.get("account"),
                "symbol":        order.get("symbol"),
                "side":          order.get("side"),
                "qty":           order.get("qty"),
                "limit_price":   order.get("limit_price"),
                "status":        order.get("status"),
                "attempts":      order.get("attempts"),
                "algo_order_id": order.get("algo_order_id"),
            },
        }
        try:
            self._on_event(evt)
        except Exception as e:
            logger.debug(f"PaperTradeEngine[{self._label}] on_event failed: {e}")

        logger.warning(
            f"[{tag}] order {kind} · {order.get('agent_slug','?')} · "
            f"{order.get('symbol')} {order.get('side')} "
            f"{order.get('qty')} · {note}"
        )

        if kind in ("fill", "unfilled", "modify") and order.get("algo_order_id"):
            try:
                task = asyncio.create_task(self._safe_update_algo_order(order, kind))
                self._pending_updates.add(task)
                task.add_done_callback(self._pending_updates.discard)
            except RuntimeError:
                # No event loop (sync `Step` button etc.) — DB will get
                # the terminal state from the next sync update path.
                pass

    async def _safe_update_algo_order(self, order: dict, kind: str) -> None:
        try:
            await self._update_algo_order(order, kind)
        except Exception as e:
            logger.warning(
                f"[{self._label.upper()}] _update_algo_order failed "
                f"(kind={kind}, id={order.get('algo_order_id')}): {e}"
            )

    async def _update_algo_order(self, order: dict, kind: str) -> None:
        from backend.api.database import async_session
        from backend.api.models  import AlgoOrder
        from sqlalchemy          import select as _select
        async with async_session() as s:
            row = (await s.execute(
                _select(AlgoOrder).where(AlgoOrder.id == order["algo_order_id"])
            )).scalar_one_or_none()
            if not row:
                return
            # Status transitions:
            #   modify   → stays OPEN (attempts + detail refresh)
            #   fill     → FILLED, fill_price + slippage + filled_at
            #   unfilled → UNFILLED, attempts frozen at the cap
            if kind == "fill":
                row.status = "FILLED"
            elif kind == "unfilled":
                row.status = "UNFILLED"
            row.attempts = int(order.get("attempts", 0))

            tag    = self._label.upper()
            side   = order.get("side") or "?"
            qty    = order.get("qty") or 0
            symbol = order.get("symbol") or "?"
            limit  = order.get("limit_price")
            agent  = order.get("agent_slug", "?")

            if kind == "modify":
                if limit is not None:
                    row.detail = (
                        f"[{tag}] {agent} {side} {qty} {symbol} · "
                        f"chase #{row.attempts} limit=₹{limit:,.2f}"
                    )
                else:
                    row.detail = (
                        f"[{tag}] {agent} {side} {qty} {symbol} · "
                        f"chase #{row.attempts}"
                    )
            elif kind == "fill" and order.get("fill_price") is not None:
                row.fill_price = float(order["fill_price"])
                initial = row.initial_price or 0
                if initial:
                    row.slippage = float(order["fill_price"]) - float(initial)
                row.filled_at = datetime.now()
                row.detail = (
                    f"[{tag}] {agent} {side} {qty} {symbol} · "
                    f"FILLED @₹{row.fill_price:,.2f} after {row.attempts} chase(s)"
                )
            elif kind == "unfilled":
                row.detail = (
                    f"[{tag}] {agent} {side} {qty} {symbol} · "
                    f"UNFILLED — gave up after {row.attempts} chase(s)"
                )
            await s.commit()
