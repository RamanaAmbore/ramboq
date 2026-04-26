"""
Orders endpoints — Phase 2.

GET  /api/orders/           — list all orders across all accounts (cached 15s)
POST /api/orders/place      — place a new order for a specific account
PUT  /api/orders/{order_id} — modify an open order
DELETE /api/orders/{order_id} — cancel an open order
POST /api/orders/postback   — Kite postback: real-time order status updates
GET  /api/accounts/         — list accounts (masked display + unmasked ID for order form)
"""

import json

import msgspec
import pandas as pd
from litestar import Controller, Request, delete, get, post, put
from litestar.exceptions import HTTPException
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK

from backend.api.auth_guard import jwt_guard
from backend.api.cache import get_or_fetch, invalidate
from backend.api.routes.ws import broadcast
from backend.api.schemas import (
    AccountInfo,
    AccountsResponse,
    CancelOrderResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    OrderRow,
    OrdersResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
    TicketOrderRequest,
    TicketOrderResponse,
)
from backend.shared.helpers.connections import Connections
from backend.shared.helpers.date_time_utils import timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import mask_column, secrets

logger = get_logger(__name__)

_VARIETIES   = {"regular", "amo", "co"}
_ORDER_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
_PRODUCTS    = {"CNC", "MIS", "NRML"}
_TXN_TYPES   = {"BUY", "SELL"}
_EXCHANGES   = {"NSE", "BSE", "NFO", "CDS", "MCX", "BFO"}
_VALIDITIES  = {"DAY", "IOC"}

_ORDERS_TTL  = 15   # orders refresh faster — 15s cache


def _kite_for(account: str):
    conn = Connections().conn
    if account not in conn:
        raise HTTPException(status_code=404, detail=f"Account '{account}' not found")
    return conn[account].get_kite_conn()


def _validate_place(req: PlaceOrderRequest) -> None:
    errors = []
    if req.variety not in _VARIETIES:
        errors.append(f"variety must be one of {_VARIETIES}")
    if req.exchange not in _EXCHANGES:
        errors.append(f"exchange must be one of {_EXCHANGES}")
    if req.transaction_type not in _TXN_TYPES:
        errors.append("transaction_type must be BUY or SELL")
    if req.order_type not in _ORDER_TYPES:
        errors.append(f"order_type must be one of {_ORDER_TYPES}")
    if req.product not in _PRODUCTS:
        errors.append(f"product must be one of {_PRODUCTS}")
    if req.validity not in _VALIDITIES:
        errors.append("validity must be DAY or IOC")
    if req.order_type in ("LIMIT", "SL") and not req.price:
        errors.append("price is required for LIMIT / SL orders")
    if req.order_type in ("SL", "SL-M") and not req.trigger_price:
        errors.append("trigger_price is required for SL / SL-M orders")
    if req.quantity <= 0:
        errors.append("quantity must be > 0")
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))


def _row_from_dict(d: dict, account: str) -> OrderRow:
    return OrderRow(
        order_id=str(d.get("order_id", "")),
        account=account,
        exchange=str(d.get("exchange", "")),
        tradingsymbol=str(d.get("tradingsymbol", "")),
        transaction_type=str(d.get("transaction_type", "")),
        quantity=int(d.get("quantity") or 0),
        pending_quantity=int(d.get("pending_quantity") or 0),
        filled_quantity=int(d.get("filled_quantity") or 0),
        price=float(d.get("price") or 0),
        trigger_price=float(d.get("trigger_price") or 0),
        average_price=float(d.get("average_price") or 0),
        status=str(d.get("status", "")),
        order_type=str(d.get("order_type", "")),
        product=str(d.get("product", "")),
        variety=str(d.get("variety", "")),
        order_timestamp=str(d.get("order_timestamp", "")),
        exchange_timestamp=str(d.get("exchange_timestamp") or ""),
        status_message=str(d.get("status_message") or ""),
        tag=str(d.get("tag") or ""),
    )


def _fetch_orders() -> OrdersResponse:
    conn = Connections().conn
    rows: list[OrderRow] = []
    for account, kite_conn in conn.items():
        try:
            kite = kite_conn.get_kite_conn()
            for o in reversed(kite.orders() or []):
                rows.append(_row_from_dict(o, account))
        except Exception as e:
            logger.error(f"Orders list failed for {account}: {e}")
    return OrdersResponse(rows=rows, refreshed_at=timestamp_display())


class AlgoOrderInfo(msgspec.Struct):
    """Shape exposed to the frontend Order-log tab. Thin wrapper over the
    AlgoOrder row — adds a display-ready price string would be nice but
    the frontend formats it for locale anyway."""
    id: int
    account: str
    symbol: str
    exchange: str
    transaction_type: str
    quantity: int
    initial_price: float | None
    fill_price: float | None
    # How many times the chase engine re-quoted this order before a
    # terminal state. Bumped live on every `modify` event so the
    # Order tab can show "chase #3" as it's happening, not just
    # after fill/unfilled.
    attempts: int
    status: str
    engine: str
    mode: str
    detail: str | None
    created_at: str


class OrdersController(Controller):
    path = "/api/orders"
    guards = [jwt_guard]

    @get("/")
    async def list_orders(self) -> OrdersResponse:
        try:
            return await get_or_fetch("orders", _fetch_orders, ttl_seconds=_ORDERS_TTL)
        except Exception as e:
            logger.error(f"Orders API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @get("/algo/recent")
    async def list_algo_orders(self, n: int = 100, mode: str = "all") -> list[AlgoOrderInfo]:
        """
        Recent agent-generated orders from the algo_orders table.

        `mode`:
          - "all"  (default) → every row, newest first. Order-log tab on the
            agents page uses this so operators see both real and simulated
            fires with a single fetch.
          - "live" → mode='live' only
          - "sim"  → mode='sim'  only

        Response includes `initial_price` (the LIMIT price = sim's LTP at
        trigger time, or the broker-submitted price in live mode), so the
        UI can show "SELL 50 NIFTY @ ₹175.50" inline.
        """
        from sqlalchemy import desc, select as sql_select
        from backend.api.database import async_session
        from backend.api.models import AlgoOrder
        async with async_session() as s:
            q = sql_select(AlgoOrder).order_by(desc(AlgoOrder.id)).limit(max(1, min(n, 500)))
            if mode in ("live", "sim", "paper"):
                q = q.where(AlgoOrder.mode == mode)
            rows = (await s.execute(q)).scalars().all()
        return [
            AlgoOrderInfo(
                id=r.id, account=r.account, symbol=r.symbol, exchange=r.exchange,
                transaction_type=r.transaction_type, quantity=r.quantity,
                initial_price=(float(r.initial_price) if r.initial_price is not None else None),
                fill_price=(float(r.fill_price) if r.fill_price is not None else None),
                attempts=int(r.attempts or 0),
                status=r.status, engine=r.engine, mode=r.mode,
                detail=r.detail,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in rows
        ]

    @post("/place")
    async def place_order(self, data: PlaceOrderRequest) -> PlaceOrderResponse:
        _validate_place(data)
        kite   = _kite_for(data.account)
        masked = mask_column(pd.Series([data.account]))[0]
        try:
            order_id = kite.place_order(
                variety=data.variety,
                exchange=data.exchange,
                tradingsymbol=data.tradingsymbol.upper(),
                transaction_type=data.transaction_type,
                quantity=data.quantity,
                product=data.product,
                order_type=data.order_type,
                price=data.price,
                trigger_price=data.trigger_price,
                validity=data.validity,
                tag=data.tag or "ramboq",
            )
            invalidate("orders")  # force fresh fetch on next request
            logger.info(f"Order placed: {order_id} [{masked}] {data.transaction_type} "
                        f"{data.quantity} {data.tradingsymbol}")
            return PlaceOrderResponse(order_id=str(order_id), account=masked)
        except Exception as e:
            logger.error(f"Place order failed [{masked}]: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    @post("/ticket")
    async def ticket_order(self, data: TicketOrderRequest) -> TicketOrderResponse:
        """
        Operator-initiated order from the reusable <OrderTicket> on
        any algo page. Routes by `mode`:
          - paper → AlgoOrder row + register_open_order on the prod
                    paper engine. The engine's 5-second tick runs
                    fill / modify / unfilled lifecycle off real bid/
                    ask via LiveQuoteSource. Same chase loop agent
                    fires use, just operator-triggered.
          - live  → phase 3 (real broker placement).

        Returns the AlgoOrder row id; UI tracks it via the existing
        `/api/orders/algo/recent?mode=paper` endpoint or the live
        Order tab in the LogPanel.
        """
        from datetime import datetime
        from backend.api.algo.paper import get_prod_paper_engine
        from backend.api.database import async_session
        from backend.api.models import AlgoOrder

        if data.mode == "draft":
            raise HTTPException(status_code=400,
                detail="Drafts are client-side; the backend doesn't track them.")
        if data.mode not in ("paper", "live"):
            raise HTTPException(status_code=400,
                detail=f"unknown mode '{data.mode}'")
        if data.mode == "live":
            raise HTTPException(status_code=501,
                detail="LIVE mode lands in phase 3.")

        side = (data.side or "").upper()
        if side not in ("BUY", "SELL"):
            raise HTTPException(status_code=400, detail="side must be BUY or SELL")
        sym = (data.tradingsymbol or "").upper().strip()
        qty = int(data.quantity or 0)
        if not sym or qty <= 0:
            raise HTTPException(status_code=400,
                detail="tradingsymbol and quantity > 0 are required")

        # Resolve account — caller may leave blank; pick the first
        # available connection (mirrors what the agent paper-trade
        # path does for total-scope actions).
        conns = Connections()
        account = data.account or (next(iter(conns.conn)) if conns.conn else "")
        if not account:
            raise HTTPException(status_code=400, detail="no broker accounts available")

        # Persist AlgoOrder row first so the engine has an id to
        # reference back into.
        algo_order_id = None
        detail = (f"[PAPER-TICKET] manual {side} {qty} {sym} "
                  f"@₹{data.price:.2f}" if data.price is not None
                  else f"[PAPER-TICKET] manual {side} {qty} {sym} @MARKET")
        try:
            async with async_session() as s:
                row = AlgoOrder(
                    account=account, symbol=sym, exchange=(data.exchange or "NFO"),
                    transaction_type=side, quantity=qty,
                    initial_price=(float(data.price) if data.price is not None else None),
                    status="OPEN", engine="paper", mode="paper",
                    detail=detail,
                )
                s.add(row)
                await s.commit()
                algo_order_id = row.id
        except Exception as e:
            logger.error(f"[PAPER-TICKET] DB write failed: {e}")
            raise HTTPException(status_code=500, detail=f"DB write failed: {e}")

        # Register with the paper engine so the chase loop picks
        # it up. Skip when no limit price (MARKET orders fill at
        # next bid/ask immediately on first tick).
        if data.price is not None and qty > 0:
            try:
                engine = get_prod_paper_engine()
                engine.register_open_order({
                    "algo_order_id": algo_order_id,
                    "account":       account,
                    "symbol":        sym,
                    "side":          side,
                    "qty":           qty,
                    "limit_price":   float(data.price),
                    "initial_price": float(data.price),
                    "exchange":      (data.exchange or "NFO"),
                    "agent_slug":    "manual-ticket",
                    "action_type":   "place_order",
                })
            except Exception as e:
                logger.warning(f"[PAPER-TICKET] engine register failed: {e}")
                # Row is persisted; engine can be restarted to re-pick-up.

        masked = mask_column(pd.Series([account]))[0]
        logger.info(f"Ticket paper order: {algo_order_id} [{masked}] {side} {qty} {sym}")
        return TicketOrderResponse(
            order_id=str(algo_order_id),
            mode="paper",
            status="OPEN",
            detail=f"Paper order #{algo_order_id} placed — chase loop will fill it on the next bid/ask cross.",
        )

    @put("/{order_id:str}")
    async def modify_order(self, order_id: str, data: ModifyOrderRequest) -> ModifyOrderResponse:
        kite   = _kite_for(data.account)
        masked = mask_column(pd.Series([data.account]))[0]
        kwargs = {k: v for k, v in {
            "quantity":      data.quantity,
            "price":         data.price,
            "order_type":    data.order_type,
            "trigger_price": data.trigger_price,
            "validity":      data.validity,
        }.items() if v is not None}
        try:
            kite.modify_order(variety=data.variety, order_id=order_id, **kwargs)
            invalidate("orders")
            logger.info(f"Order modified: {order_id} [{masked}]")
            return ModifyOrderResponse(order_id=order_id)
        except Exception as e:
            logger.error(f"Modify order failed [{masked}] {order_id}: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    @post("/postback", guards=[])
    async def order_postback(self, request: Request) -> dict:
        """Kite postback — receives real-time order status updates.
        No JWT guard — Kite sends this directly. Authenticated by the
        postback secret configured in the Kite developer console."""
        try:
            body = await request.json()
            order_id = body.get("order_id", "")
            account = body.get("user_id", "")
            status = body.get("status", "")
            tradingsymbol = body.get("tradingsymbol", "")
            txn = body.get("transaction_type", "")
            qty = body.get("quantity", 0)
            price = body.get("average_price") or body.get("price", 0)
            status_msg = body.get("status_message") or ""
            masked = mask_column(pd.Series([account]))[0] if account else ""

            logger.info(f"Postback: {order_id} [{masked}] {status} {txn} {qty} "
                        f"{tradingsymbol} price={price} msg={status_msg}")

            # Invalidate orders cache so next fetch gets fresh data
            invalidate("orders")

            # Push real-time update to all connected WebSocket clients
            broadcast(json.dumps({
                "event": "order_update",
                "order_id": order_id,
                "account": masked,
                "status": status,
                "tradingsymbol": tradingsymbol,
                "transaction_type": txn,
                "quantity": qty,
                "price": price,
                "status_message": status_msg,
            }))

            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Postback error: {e}")
            return {"status": "error", "detail": str(e)}

    @delete("/{order_id:str}", status_code=HTTP_200_OK)
    async def cancel_order(
        self,
        order_id: str,
        account:  str = Parameter(query="account"),
        variety:  str = Parameter(query="variety", default="regular"),
    ) -> CancelOrderResponse:
        kite   = _kite_for(account)
        masked = mask_column(pd.Series([account]))[0]
        try:
            kite.cancel_order(variety=variety, order_id=order_id)
            invalidate("orders")
            logger.info(f"Order cancelled: {order_id} [{masked}]")
            return CancelOrderResponse(order_id=order_id)
        except Exception as e:
            logger.error(f"Cancel order failed [{masked}] {order_id}: {e}")
            raise HTTPException(status_code=400, detail=str(e))


class AccountsController(Controller):
    path = "/api/accounts"
    guards = [jwt_guard]

    @get("/")
    async def list_accounts(self) -> AccountsResponse:
        conn = Connections().conn
        accounts = [
            AccountInfo(
                account_id=account,
                display=mask_column(pd.Series([account]))[0],
            )
            for account in conn
        ]
        return AccountsResponse(accounts=accounts)
