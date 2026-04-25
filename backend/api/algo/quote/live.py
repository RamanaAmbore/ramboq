"""
LiveQuoteSource — real broker bid/ask for the mode-2 paper engine.

Calls the broker's quote endpoint via the `Broker` adapter so the same
engine that fills sim orders against fabricated prices can fill paper
orders against live Kite ticks. Bid/ask is derived from the broker's
returned depth when present, otherwise from `last_price` ± half of
`simulator.default_spread_pct` (same knob the simulator uses).
"""

from __future__ import annotations

from backend.api.algo.quote.base import QuoteSource
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class LiveQuoteSource(QuoteSource):
    """Bid/ask from `broker.quote(...)` (preferred) or `broker.ltp(...)`
    (fallback). Constructs the Kite-style key `EXCHANGE:tradingsymbol`
    from the order dict and asks the per-account `Broker` adapter for
    a quote. Reads `simulator.default_spread_pct` per call so live
    tuning via /admin/settings takes effect on the next tick."""

    def bid_ask_for_order(self, order: dict) -> tuple[float | None, float | None]:
        from backend.shared.brokers      import get_broker
        from backend.shared.helpers.settings import get_float

        account  = str(order.get("account") or "")
        symbol   = str(order.get("symbol") or "")
        exchange = str(order.get("exchange") or "NFO")
        if not (account and symbol):
            return None, None

        key = f"{exchange}:{symbol}"
        try:
            broker = get_broker(account)
            quote  = broker.quote([key]).get(key) or {}
        except Exception as e:
            logger.debug(f"Live quote failed for {key} on {account}: {e}")
            return None, None

        # Prefer real depth from the broker's quote response.
        depth = quote.get("depth") or {}
        buy_book  = depth.get("buy")  or []
        sell_book = depth.get("sell") or []
        bid = buy_book[0].get("price")  if buy_book  else None
        ask = sell_book[0].get("price") if sell_book else None
        if bid and ask:
            return float(bid), float(ask)

        # Fall back to LTP ± half-spread when depth is empty (illiquid
        # contract, off-hours, etc.). Same default the simulator uses.
        ltp = quote.get("last_price")
        if ltp is None:
            return None, None
        spread = max(0.0, get_float("simulator.default_spread_pct", 0.10) / 100.0)
        half   = spread / 2.0
        ltp    = float(ltp)
        return ltp * (1.0 - half), ltp * (1.0 + half)
