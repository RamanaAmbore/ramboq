"""
Orders endpoints — Phase 2.

GET  /api/orders/           — list all orders across all accounts (cached 15s)
POST /api/orders/place      — place a new order for a specific account
PUT  /api/orders/{order_id} — modify an open order
DELETE /api/orders/{order_id} — cancel an open order
GET  /api/accounts/         — list accounts (masked display + unmasked ID for order form)
"""

import pandas as pd
from litestar import Controller, delete, get, post, put
from litestar.exceptions import HTTPException
from litestar.params import Parameter
from litestar.status_codes import HTTP_200_OK

from api.auth_guard import jwt_guard
from api.cache import get_or_fetch, invalidate
from api.schemas import (
    AccountInfo,
    AccountsResponse,
    CancelOrderResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    OrderRow,
    OrdersResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
)
from src.helpers.connections import Connections
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column, secrets

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
            kite   = kite_conn.get_kite_conn()
            masked = mask_column(pd.Series([account]))[0]
            for o in reversed(kite.orders() or []):
                rows.append(_row_from_dict(o, masked))
        except Exception as e:
            logger.error(f"Orders list failed for {account}: {e}")
    return OrdersResponse(rows=rows, refreshed_at=timestamp_display())


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
            raise HTTPException(status_code=500, detail=str(e))

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
            raise HTTPException(status_code=500, detail=str(e))

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
            raise HTTPException(status_code=500, detail=str(e))


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
