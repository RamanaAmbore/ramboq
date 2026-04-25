"""
`/api/charts/*` — price-history + order-event feed for the chart panel.

Reads from in-memory rolling deques on `SimDriver` (mode=sim) and
`PaperTradeEngine` (mode=paper / mode=live), so there's no extra schema
or cleanup logic — the deques self-trim. Order-event markers are
derived from existing `AlgoOrder` rows (placed / chased / filled /
unfilled) so the chart shows where each chase started, how it crawled,
and where it terminated.

Endpoints
  GET  /api/charts/symbols?mode=sim|paper|live
       List symbols with at least one captured tick. Used by the
       chart panel's symbol picker.
  GET  /api/charts/price-history?mode=…&symbol=…&since=…
       Returns `{ticks: [...], events: [...]}`. Ticks come from the
       in-memory buffer; events come from algo_orders (one entry per
       lifecycle transition we can derive).
"""

from __future__ import annotations

from typing import Optional

import msgspec
from litestar import Controller, get
from litestar.exceptions import HTTPException
from sqlalchemy import desc, select

from backend.api.algo.paper import get_prod_paper_engine
from backend.api.algo.sim.driver import get_driver
from backend.api.auth_guard import admin_guard
from backend.api.database import async_session
from backend.api.models import AlgoOrder
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


_VALID_MODES = ("sim", "paper", "live")


class PriceTick(msgspec.Struct):
    ts:  str
    ltp: float
    bid: float | None
    ask: float | None


class OrderEvent(msgspec.Struct):
    """One lifecycle marker for the chart. Multiple events per AlgoOrder
    are emitted (placed → chased → terminal) so each transition shows up
    as its own marker on the price line."""
    ts:        str
    kind:      str          # placed | filled | unfilled | chased
    side:      str          # BUY / SELL
    price:     float | None # initial_price for placed/chased; fill_price for filled
    status:    str          # AlgoOrder.status at this transition
    order_id:  int
    attempts:  int
    detail:    str | None


class ChartResponse(msgspec.Struct):
    mode:       str
    symbol:     str
    # 'underlying' for spot tickers (NIFTY, BANKNIFTY, …), 'derivative'
    # for options/futures, 'other' for plain equity / unrecognised symbols.
    kind:       str
    # When `kind='derivative'`, the underlying name (e.g. 'NIFTY' for
    # NIFTY25APR22000CE). Lets the client render the underlying line on
    # the same chart for context. None otherwise.
    underlying: str | None
    ticks:      list[PriceTick]
    events:     list[OrderEvent]


def _classify_symbol(eng, symbol: str) -> tuple[str, str | None]:
    """
    Returns (kind, underlying) where kind ∈ {'underlying','derivative','other'}.
    Underlyings live in their own buffer on the engine; derivatives parse
    cleanly via the F&O regex; everything else is 'other'.
    """
    # Underlying check: the engine exposes a parallel _underlying_history
    # dict; if `symbol` is a key there, treat it as an underlying.
    und_buf = getattr(eng, "_underlying_history", None) or {}
    if symbol in und_buf:
        return ("underlying", None)

    from backend.api.algo.derivatives import parse_tradingsymbol
    parsed = parse_tradingsymbol(symbol)
    if parsed:
        return ("derivative", parsed["underlying"])
    return ("other", None)


def _engine_for_mode(mode: str):
    """Return the source object owning the price-history deques for `mode`.

    Live mode currently shares the prod paper engine because both run
    against `LiveQuoteSource`; once mode-3 grows its own state we can
    branch here.
    """
    if mode == "sim":
        return get_driver()
    return get_prod_paper_engine()


def _algo_order_events(rows: list[AlgoOrder]) -> list[OrderEvent]:
    """Derive lifecycle markers from a list of AlgoOrder rows. Each row
    yields up to two events: a 'placed' at created_at, and a terminal
    'filled' / 'unfilled' / 'chased' (still OPEN) at the latest known
    timestamp."""
    out: list[OrderEvent] = []
    for r in rows:
        side = r.transaction_type or "?"
        # Placed marker — every order has a created_at and an initial_price.
        if r.created_at:
            out.append(OrderEvent(
                ts=r.created_at.isoformat(),
                kind="placed",
                side=side,
                price=(float(r.initial_price) if r.initial_price is not None else None),
                status=r.status or "?",
                order_id=r.id,
                attempts=int(r.attempts or 0),
                detail=r.detail,
            ))
        # Terminal marker — choose by status.
        if r.status == "FILLED" and r.filled_at:
            out.append(OrderEvent(
                ts=r.filled_at.isoformat(),
                kind="filled",
                side=side,
                price=(float(r.fill_price) if r.fill_price is not None else None),
                status=r.status,
                order_id=r.id,
                attempts=int(r.attempts or 0),
                detail=r.detail,
            ))
        elif r.status == "UNFILLED":
            # No dedicated unfilled timestamp on the model — use filled_at if
            # present (chase engine sets it on terminal), else created_at as
            # a fallback so the marker still lands somewhere meaningful.
            ts = r.filled_at or r.created_at
            if ts:
                out.append(OrderEvent(
                    ts=ts.isoformat(),
                    kind="unfilled",
                    side=side,
                    price=(float(r.initial_price) if r.initial_price is not None else None),
                    status=r.status,
                    order_id=r.id,
                    attempts=int(r.attempts or 0),
                    detail=r.detail,
                ))
    out.sort(key=lambda e: e.ts)
    return out


class ChartsController(Controller):
    path   = "/api/charts"
    guards = [admin_guard]

    @get("/symbols")
    async def symbols(self, mode: str = "sim") -> dict:
        """List symbols with captured ticks, classified so the UI can
        render underlyings first and group derivatives by their root
        without making N extra calls. Symbols are returned sorted with
        underlyings first, then derivatives grouped by underlying, then
        anything else."""
        if mode not in _VALID_MODES:
            raise HTTPException(status_code=400,
                                detail=f"mode must be one of {_VALID_MODES}")
        eng     = _engine_for_mode(mode)
        symbols = eng.price_history_symbols()
        items   = []
        for sym in symbols:
            kind, und = _classify_symbol(eng, sym)
            items.append({"symbol": sym, "kind": kind, "underlying": und})
        # Sort: underlyings first (alpha), then derivatives grouped by
        # underlying (alpha within the group), then 'other' (alpha).
        kind_rank = {"underlying": 0, "derivative": 1, "other": 2}
        items.sort(key=lambda i: (
            kind_rank.get(i["kind"], 3),
            i.get("underlying") or "",
            i["symbol"],
        ))
        return {
            "mode":    mode,
            "symbols": [i["symbol"] for i in items],   # back-compat
            "items":   items,
        }

    @get("/price-history")
    async def price_history(self, mode: str = "sim", symbol: str = "",
                            since: Optional[str] = None,
                            limit: int = 600) -> ChartResponse:
        if mode not in _VALID_MODES:
            raise HTTPException(status_code=400,
                                detail=f"mode must be one of {_VALID_MODES}")
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")

        eng = _engine_for_mode(mode)
        raw_ticks = eng.price_history(symbol, since=since,
                                      limit=max(1, min(int(limit or 600), 600)))
        ticks = [PriceTick(ts=t["ts"], ltp=t["ltp"],
                           bid=t.get("bid"), ask=t.get("ask"))
                 for t in raw_ticks]

        # Classify the symbol so the UI can pick a colour scheme + decide
        # whether to render an underlying overlay.
        kind, underlying = _classify_symbol(eng, symbol)

        # Underlyings have no AlgoOrder events of their own — skip the
        # query for them. For derivatives we still pull recent rows so
        # placed/filled/unfilled markers land on the chart.
        events: list[OrderEvent] = []
        if kind != "underlying":
            async with async_session() as s:
                rows = (await s.execute(
                    select(AlgoOrder)
                    .where(AlgoOrder.mode == mode)
                    .where(AlgoOrder.symbol == symbol)
                    .order_by(desc(AlgoOrder.created_at))
                    .limit(50)
                )).scalars().all()
            events = _algo_order_events(list(rows))

        return ChartResponse(mode=mode, symbol=symbol, kind=kind,
                             underlying=underlying, ticks=ticks, events=events)
