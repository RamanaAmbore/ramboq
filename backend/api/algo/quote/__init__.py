"""
Quote sources — broker-agnostic suppliers of bid/ask for an open order.

Lets the `PaperTradeEngine` ([backend/api/algo/paper.py]) run the same
fill / modify / unfilled lifecycle against fabricated prices (mode 1,
the simulator) AND against real Kite ticks (mode 2, paper-on-prod).

Public API:

    from backend.api.algo.quote import QuoteSource, SimQuoteSource, LiveQuoteSource
"""

from backend.api.algo.quote.base       import QuoteSource
from backend.api.algo.quote.sim        import SimQuoteSource
from backend.api.algo.quote.live       import LiveQuoteSource
from backend.api.algo.quote.historical import HistoricalQuoteSource

__all__ = ["QuoteSource", "SimQuoteSource", "LiveQuoteSource", "HistoricalQuoteSource"]
