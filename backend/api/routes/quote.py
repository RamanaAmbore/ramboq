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

from backend.api.auth_guard import jwt_guard
from backend.shared.helpers.connections import Connections
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class QuoteResponse(msgspec.Struct):
    tradingsymbol: str
    exchange: str
    ltp: float
    tick_size: float
    bid: Optional[float] = None
    ask: Optional[float] = None


def _fetch_ltp(exchange: str, tradingsymbol: str) -> QuoteResponse:
    conns = Connections()
    account = next(iter(conns.conn))
    kite = conns.conn[account].kite
    key = f"{exchange}:{tradingsymbol}"
    data = kite.ltp([key])
    row = data.get(key) or {}
    ltp = float(row.get("last_price") or 0.0)

    # Also try to get depth if available
    bid = ask = None
    try:
        full = kite.quote([key]).get(key) or {}
        depth = full.get("depth") or {}
        buy = depth.get("buy") or []
        sell = depth.get("sell") or []
        if buy: bid = float(buy[0].get("price") or 0.0) or None
        if sell: ask = float(sell[0].get("price") or 0.0) or None
    except Exception:
        pass

    return QuoteResponse(
        tradingsymbol=tradingsymbol,
        exchange=exchange,
        ltp=ltp,
        tick_size=0.05,  # overridden by frontend from instruments cache
        bid=bid,
        ask=ask,
    )


class QuoteController(Controller):
    path = "/api/quote"
    guards = [jwt_guard]

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
