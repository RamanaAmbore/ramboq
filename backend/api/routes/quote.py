"""
Market quote endpoint — returns LTP + tick-size for a single instrument.
Used by the frontend command bar to suggest LIMIT prices around current price.

GET /api/quote/?exchange=NSE&tradingsymbol=RELIANCE  → { ltp, tick_size }
"""

from typing import Optional

import msgspec
from litestar import Controller, get
from litestar.exceptions import HTTPException
from litestar.params import Parameter

from backend.api.auth_guard import auth_or_demo_guard
from backend.shared.helpers.connections import Connections
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class DepthLevel(msgspec.Struct):
    price: float
    quantity: int
    orders: int = 0


class QuoteResponse(msgspec.Struct):
    tradingsymbol: str
    exchange: str
    ltp: float
    tick_size: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    depth_buy: list[DepthLevel] = []
    depth_sell: list[DepthLevel] = []
    volume: int = 0


def _fetch_ltp(exchange: str, tradingsymbol: str) -> QuoteResponse:
    conns = Connections()
    account = next(iter(conns.conn))
    kite = conns.conn[account].get_kite_conn()
    key = f"{exchange}:{tradingsymbol}"

    bid = ask = None
    depth_buy: list[DepthLevel] = []
    depth_sell: list[DepthLevel] = []
    volume = 0
    ltp = 0.0

    try:
        full = kite.quote([key]).get(key) or {}
        ltp = float(full.get("last_price") or 0.0)
        volume = int(full.get("volume") or 0)
        depth = full.get("depth") or {}
        for level in (depth.get("buy") or [])[:5]:
            p, q, o = float(level.get("price") or 0), int(level.get("quantity") or 0), int(level.get("orders") or 0)
            if p > 0:
                depth_buy.append(DepthLevel(price=p, quantity=q, orders=o))
        for level in (depth.get("sell") or [])[:5]:
            p, q, o = float(level.get("price") or 0), int(level.get("quantity") or 0), int(level.get("orders") or 0)
            if p > 0:
                depth_sell.append(DepthLevel(price=p, quantity=q, orders=o))
        if depth_buy:
            bid = depth_buy[0].price
        if depth_sell:
            ask = depth_sell[0].price
    except Exception as e:
        # Fallback to ltp-only
        logger.warning(f"Quote depth failed for {key}: {e}")
        try:
            data = kite.ltp([key])
            row = data.get(key) or {}
            ltp = float(row.get("last_price") or 0.0)
        except Exception as e2:
            logger.error(f"Quote LTP fallback failed for {key}: {e2}")

    return QuoteResponse(
        tradingsymbol=tradingsymbol,
        exchange=exchange,
        ltp=ltp,
        tick_size=0.05,
        bid=bid,
        ask=ask,
        depth_buy=depth_buy,
        depth_sell=depth_sell,
        volume=volume,
    )


class QuoteController(Controller):
    path = "/api/quote"
    guards = [auth_or_demo_guard]

    @get("/")
    async def get_quote(
        self,
        exchange: str = Parameter(required=True),
        tradingsymbol: str = Parameter(required=True),
    ) -> QuoteResponse:
        try:
            return _fetch_ltp(exchange, tradingsymbol)
        except Exception as e:
            logger.error(f"Quote API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
