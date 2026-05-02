"""
HistoricalQuoteSource — feeds the PaperTradeEngine from pre-loaded OHLCV
candles during a replay / backtest session.

The ReplayDriver pre-loads all historical data at start time (one
`kite.historical_data()` call per symbol) and advances a per-symbol
pointer each tick. This source reads the current candle and derives
bid/ask from it.
"""

from __future__ import annotations

from backend.api.algo.quote.base import QuoteSource


class HistoricalQuoteSource(QuoteSource):
    """Reads bid/ask from pre-loaded candle data, keyed by symbol."""

    def __init__(self, spread_pct: float = 0.10) -> None:
        # Current candle slice — updated by the ReplayDriver before each
        # engine.step(). Key = tradingsymbol, value = candle dict with
        # at least 'close' (used as mid-price for bid/ask derivation).
        self._current_candles: dict[str, dict] = {}
        self._half_spread: float = max(0.0, spread_pct / 100.0) / 2.0

    def set_candles(self, candles: dict[str, dict]) -> None:
        """Called by ReplayDriver before each tick."""
        self._current_candles = candles

    def bid_ask_for_order(self, order: dict) -> tuple[float | None, float | None]:
        sym = str(order.get("symbol") or "")
        candle = self._current_candles.get(sym)
        if candle is None:
            return None, None

        # Use the candle's close as the mid-price. For intraday candles,
        # close is the last traded price within the interval — a reasonable
        # proxy for the "current" price during replay.
        mid = candle.get("close") or candle.get("last_price")
        if mid is None:
            return None, None
        mid = float(mid)
        return mid * (1.0 - self._half_spread), mid * (1.0 + self._half_spread)

    def on_fill(self, order: dict) -> None:
        # Replay doesn't track a mutable position book — fills are
        # informational. The ReplayDriver tracks fill events separately.
        pass
