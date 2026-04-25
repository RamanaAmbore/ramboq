"""
SimQuoteSource — feeds the PaperTradeEngine from SimDriver's per-symbol
fabricated price state.

This is the existing simulator behaviour, lifted out of `SimDriver` so
the same chase / fill / modify / unfilled lifecycle can run against
either fabricated quotes (mode 1) or real Kite quotes (mode 2) without
duplicating the engine code.
"""

from __future__ import annotations

from backend.api.algo.quote.base import QuoteSource


class SimQuoteSource(QuoteSource):
    """Reads bid/ask from the simulator driver's `_positions_rows`."""

    def __init__(self, driver) -> None:
        # Held by reference (not snapshot) — every read sees the
        # driver's current state, including price moves applied earlier
        # in the same tick.
        self._driver = driver

    def bid_ask_for_order(self, order: dict) -> tuple[float | None, float | None]:
        acct  = str(order.get("account", ""))
        sym   = str(order.get("symbol", ""))
        for row in self._driver._positions_rows:
            if str(row.get("account", "")) == acct and \
               str(row.get("tradingsymbol", "")) == sym:
                bid = row.get("bid")
                ask = row.get("ask")
                return (
                    float(bid) if bid is not None else None,
                    float(ask) if ask is not None else None,
                )
        # Position closed out (e.g. a previous chase tick filled it) —
        # signal "no quote" so the engine auto-closes the order.
        return None, None

    def on_fill(self, order: dict) -> None:
        """Drop the filled position from the simulator's book so
        downstream ticks don't keep re-firing agents against a
        phantom long/short."""
        acct = str(order.get("account", ""))
        sym  = str(order.get("symbol", ""))
        self._driver._positions_rows = [
            r for r in self._driver._positions_rows
            if not (str(r.get("account", "")) == acct
                    and str(r.get("tradingsymbol", "")) == sym)
        ]
