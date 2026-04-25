"""
QuoteSource ABC — contract every bid/ask supplier honours.

The PaperTradeEngine doesn't care where its quotes come from; it just
asks for `(bid, ask)` per open order each tick. SimQuoteSource pulls
from the simulator's per-symbol price state; LiveQuoteSource calls the
real broker's ltp/quote endpoint.

`on_fill` is the optional hook the engine calls after a fill so the
quote source can update its book. The simulator uses it to remove the
filled position from `_positions_rows`; live quotes don't track
positions and leave it as a no-op.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class QuoteSource(ABC):
    @abstractmethod
    def bid_ask_for_order(self, order: dict) -> tuple[float | None, float | None]:
        """
        Return `(bid, ask)` for the symbol an open paper order is
        chasing. Either side may be `None` if the source can't supply a
        price right now (symbol not in the book, broker call failed,
        etc.) — the engine treats `(None, None)` as "auto-close on the
        next sweep" so stale orders can't hang around forever.

        `order` is the dict the engine holds:
            {account, symbol, side, qty, limit_price, exchange, ...}
        """

    def on_fill(self, order: dict) -> None:
        """
        Called by the engine when an order fills against this source's
        book. Default: no-op (live quotes don't track positions).
        Simulator overrides to drop the filled symbol from
        `_positions_rows` so subsequent ticks don't re-trigger the same
        agent against a phantom position.
        """
        return None

    def prefetch_for(self, orders: list[dict]) -> None:
        """
        Optional bulk fetch — the engine calls this once at the start
        of `step()` so sources that hit a remote API can batch instead
        of round-tripping per order. Default: no-op (in-memory
        sources read directly from local state in `bid_ask_for_order`).

        The LiveQuoteSource override groups orders by account, calls
        `broker.quote([key1, key2, ...])` once per account, and caches
        the result so `bid_ask_for_order` becomes a dict lookup.
        """
        return None
