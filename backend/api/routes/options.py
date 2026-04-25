"""
`/api/options/*` — options analytics for the /admin/options dashboard.

Computes Greeks, payoff curves, risk metrics (max profit / max loss /
breakeven / POP), theoretical-vs-market discrepancy, and historical
candles for any single-leg option position. Three input modes:

  - `live`         — read qty/avg/LTP from a real broker position
  - `sim`          — read from the SimDriver's `_positions_rows`
  - `hypothetical` — operator-specified symbol + qty; LTP fetched from
                     broker for theoretical analysis before they take
                     the trade.

Underlying spot, current LTP, and historical candles are fetched via
`get_price_broker()` so they honor the `connections.price_account`
setting in /admin/settings — operators centralize "which Kite handle do
we hammer for shared market data" in one place.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import msgspec
from litestar import Controller, get
from litestar.exceptions import HTTPException

from backend.api.algo.derivatives import (
    DEFAULT_RISK_FREE,
    black_scholes,
    days_to_expiry,
    greeks,
    implied_vol,
    parse_tradingsymbol,
    payoff_curve,
    risk_metrics,
    underlying_ltp_key,
)
from backend.api.auth_guard import admin_guard
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


_VALID_MODES = ("live", "sim", "hypothetical")


# ── Schemas ───────────────────────────────────────────────────────────

class OptionGreeks(msgspec.Struct):
    delta: float
    gamma: float
    theta: float        # per day
    vega:  float        # per 1 % IV
    rho:   float        # per 1 % rate


class OptionRisk(msgspec.Struct):
    max_profit: float | None      # None = unlimited
    max_loss:   float | None
    breakeven:  float
    pop:        float             # 0..1
    long_short: str               # 'long' / 'short' / 'flat'


class PayoffPoint(msgspec.Struct):
    spot:         float
    today_value:  float
    expiry_value: float


class OptionAnalyticsResponse(msgspec.Struct):
    # Identification
    mode:          str
    symbol:        str
    underlying:    str
    opt_type:      str            # CE / PE
    strike:        float
    expiry:        str            # ISO date
    days_to_expiry: float

    # Position
    account:       str | None
    qty:           int
    avg_cost:      float          # entry premium per share

    # Pricing block
    spot:          float
    ltp:           float
    iv:            float
    theoretical:   float          # BS at current spot/IV/DTE
    discrepancy:   float          # ltp - theoretical
    discrepancy_pct: float        # %

    # Greeks (per share + position-scaled)
    greeks_per_share: OptionGreeks
    greeks_position:  OptionGreeks

    # Risk + payoff curve
    risk:    OptionRisk
    payoff:  list[PayoffPoint]


class HistoricalBar(msgspec.Struct):
    ts:     str
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int


class HistoricalResponse(msgspec.Struct):
    symbol:           str
    instrument_token: int | None
    interval:         str
    bars:             list[HistoricalBar]


# ── Resolvers ─────────────────────────────────────────────────────────

def _resolve_position(mode: str, symbol: str, qty: Optional[int],
                     account: Optional[str], avg_cost: Optional[float]
                     ) -> tuple[int, str | None, float]:
    """
    Resolve (qty, account, avg_cost) for the requested mode. Hypothetical
    mode lets the operator pre-trade-analyze any symbol with a default qty
    of 1 lot (or the lot size if we can derive it).
    """
    if mode == "hypothetical":
        # Default qty = 1 share long; operator can override via query.
        return (int(qty) if qty is not None else 1,
                account, float(avg_cost) if avg_cost is not None else 0.0)

    if mode == "sim":
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        for r in drv._positions_rows:
            if str(r.get("tradingsymbol", "")).upper() == symbol.upper():
                return (
                    int(r.get("quantity") or 0),
                    str(r.get("account") or "—"),
                    float(r.get("average_price") or 0),
                )
        raise HTTPException(status_code=404,
                            detail=f"sim has no position '{symbol}'")

    # mode == "live"
    if not account:
        raise HTTPException(status_code=400,
                            detail="live mode requires `account`.")
    from backend.shared.brokers.registry import get_broker
    try:
        positions = get_broker(account).positions() or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"broker positions fetch failed: {e}")
    nets = positions.get("net") or positions.get("day") or []
    for p in nets:
        if str(p.get("tradingsymbol", "")).upper() == symbol.upper():
            return (
                int(p.get("quantity") or 0),
                account,
                float(p.get("average_price") or 0),
            )
    raise HTTPException(status_code=404,
                        detail=f"account {account!r} has no position '{symbol}'")


def _resolve_spot(underlying: str, override: Optional[float]) -> float:
    """Spot price for the underlying. Override > sim-known spot > live ltp."""
    if override is not None:
        return float(override)
    # If a sim is running and knows this underlying, use it (operators
    # analyzing a sim position see consistent numbers).
    try:
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        if drv.active and underlying in drv._underlyings:
            return float(drv._underlyings[underlying])
    except Exception:
        pass

    from backend.shared.brokers.registry import get_price_broker
    key  = underlying_ltp_key(underlying)
    resp = get_price_broker().ltp([key]) or {}
    quote = resp.get(key) or {}
    ltp = quote.get("last_price")
    if ltp is None:
        raise HTTPException(status_code=502,
                            detail=f"spot for {underlying} unavailable from broker")
    return float(ltp)


def _resolve_ltp(symbol: str, mode: str, account: Optional[str],
                 override: Optional[float]) -> float:
    """Current LTP for the option contract itself."""
    if override is not None:
        return float(override)
    if mode == "sim":
        from backend.api.algo.sim.driver import get_driver
        for r in get_driver()._positions_rows:
            if str(r.get("tradingsymbol", "")).upper() == symbol.upper():
                lp = r.get("last_price")
                if lp is not None:
                    return float(lp)
        raise HTTPException(status_code=404,
                            detail=f"sim has no LTP for '{symbol}'")

    # live + hypothetical → broker quote
    from backend.shared.brokers.registry import get_price_broker
    key = f"NFO:{symbol}"
    try:
        resp = get_price_broker().ltp([key]) or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"broker ltp fetch failed: {e}")
    q = resp.get(key) or {}
    ltp = q.get("last_price")
    if ltp is None:
        raise HTTPException(status_code=404,
                            detail=f"LTP for '{symbol}' not returned by broker")
    return float(ltp)


# ── Controller ────────────────────────────────────────────────────────

class OptionsController(Controller):
    path   = "/api/options"
    guards = [admin_guard]

    @get("/analytics")
    async def analytics(self, mode: str = "live", symbol: str = "",
                        account: Optional[str] = None,
                        qty: Optional[int] = None,
                        avg_cost: Optional[float] = None,
                        spot: Optional[float] = None,
                        ltp: Optional[float] = None,
                        iv: Optional[float] = None,
                        span_pct: float = 0.10,
                        points: int = 51) -> OptionAnalyticsResponse:
        """
        Full analytics bundle for one option position. Single round-trip
        — Greeks, theoretical price, discrepancy, risk metrics, payoff
        curve all computed in-process. The frontend renders this as the
        side panel + payoff chart on /admin/options.
        """
        if mode not in _VALID_MODES:
            raise HTTPException(status_code=400,
                                detail=f"mode must be one of {_VALID_MODES}")
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")

        sym    = symbol.upper().strip()
        parsed = parse_tradingsymbol(sym)
        if not parsed or parsed.get("kind") != "opt":
            raise HTTPException(
                status_code=400,
                detail=f"'{sym}' isn't a recognised option contract. "
                       f"Futures and equities aren't supported by this endpoint."
            )

        qty_resolved, acct_resolved, avg_resolved = _resolve_position(
            mode, sym, qty, account, avg_cost)
        S        = _resolve_spot(parsed["underlying"], spot)
        ltp_val  = _resolve_ltp(sym, mode, acct_resolved or account, ltp)

        T_yrs = days_to_expiry(parsed["expiry"]) / 365.0
        # IV: explicit override > calibrate from current LTP > default
        if iv is not None and iv > 0:
            sigma = float(iv)
        else:
            sigma = implied_vol(ltp_val, S, parsed["strike"], T_yrs,
                                DEFAULT_RISK_FREE, parsed["opt_type"])

        theo = black_scholes(S, parsed["strike"], T_yrs,
                             DEFAULT_RISK_FREE, sigma, parsed["opt_type"])
        disc = ltp_val - theo
        disc_pct = (disc / theo * 100.0) if theo else 0.0

        g_per = greeks(S, parsed["strike"], T_yrs,
                       DEFAULT_RISK_FREE, sigma, parsed["opt_type"])
        # Position-scaled Greeks: multiply by signed qty so a short put's
        # delta reads negative correctly.
        g_pos = {k: v * qty_resolved for k, v in g_per.items()}

        # Use avg_cost if non-zero (real position); fall back to current
        # LTP as the cost basis for hypothetical analysis ("what would
        # buying this RIGHT NOW look like?").
        entry = avg_resolved if avg_resolved > 0 else ltp_val
        risk = risk_metrics(
            S=S, K=parsed["strike"], T_years=T_yrs,
            r=DEFAULT_RISK_FREE, sigma=sigma,
            opt_type=parsed["opt_type"], qty=qty_resolved,
            entry_price=entry,
        )
        curve = payoff_curve(
            S=S, K=parsed["strike"], T_years=T_yrs,
            r=DEFAULT_RISK_FREE, sigma=sigma,
            opt_type=parsed["opt_type"], qty=qty_resolved,
            entry_price=entry,
            span_pct=max(0.01, min(float(span_pct), 0.5)),
            points=max(11, min(int(points), 101)),
        )

        # Sanitize +inf in JSON — msgspec will choke; the API surface
        # uses null and the UI renders "∞".
        def _finite_or_null(x: float) -> float | None:
            return None if x == float("inf") or x == float("-inf") else x

        return OptionAnalyticsResponse(
            mode=mode,
            symbol=sym,
            underlying=parsed["underlying"],
            opt_type=parsed["opt_type"],
            strike=parsed["strike"],
            expiry=parsed["expiry"].isoformat(),
            days_to_expiry=days_to_expiry(parsed["expiry"]),
            account=acct_resolved,
            qty=qty_resolved,
            avg_cost=entry,
            spot=S, ltp=ltp_val, iv=sigma,
            theoretical=theo,
            discrepancy=disc,
            discrepancy_pct=disc_pct,
            greeks_per_share=OptionGreeks(**g_per),
            greeks_position=OptionGreeks(**g_pos),
            risk=OptionRisk(
                max_profit=_finite_or_null(risk["max_profit"]),
                max_loss=_finite_or_null(risk["max_loss"]),
                breakeven=risk["breakeven"],
                pop=risk["pop"],
                long_short=risk["long_short"],
            ),
            payoff=[PayoffPoint(**p) for p in curve],
        )

    @get("/historical")
    async def historical(self, symbol: str = "", days: int = 30,
                         interval: str = "day",
                         exchange: str = "NFO") -> HistoricalResponse:
        """
        Daily / hourly / minute candles from Kite. `interval` ∈ {day,
        60minute, 30minute, 15minute, 5minute, minute}. Underlyings get
        their NSE spot history; options + futures use NFO.

        The instrument-token lookup hits the broker's instruments dump
        for the relevant exchange — that response is large but already
        cached by the InstrumentsController (TTL 24h via `get_or_fetch`),
        so a warm cache makes this endpoint cheap.
        """
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        sym  = symbol.upper().strip()
        days = max(1, min(int(days), 90))

        valid_intervals = ("day", "60minute", "30minute", "15minute", "5minute", "minute")
        if interval not in valid_intervals:
            raise HTTPException(status_code=400,
                                detail=f"interval must be one of {valid_intervals}")

        # Instrument-token lookup. For an option/future we use NFO; for
        # an underlying name (NIFTY) we'd have to map to NSE:NIFTY 50,
        # which Kite returns under exchange='NSE' with tradingsymbol
        # 'NIFTY 50'. Operators usually want the contract chart, not the
        # spot — keep this simple: caller passes a tradingsymbol; we look
        # it up on `exchange`.
        from backend.shared.brokers.registry import get_price_broker
        broker = get_price_broker()
        token: int | None = None
        try:
            insts = broker.instruments(exchange) or []
            for inst in insts:
                if str(inst.get("tradingsymbol") or "").upper() == sym:
                    token = int(inst.get("instrument_token"))
                    break
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"instrument lookup failed: {e}")
        if not token:
            raise HTTPException(status_code=404,
                                detail=f"instrument token for '{sym}' on '{exchange}' not found")

        # Kite historical_data returns list[dict] with OHLCV.
        try:
            kite = broker.kite  # type: ignore[attr-defined]
            to_d   = datetime.now()
            from_d = to_d - timedelta(days=days)
            raw    = kite.historical_data(token, from_d, to_d, interval) or []
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"historical_data failed: {e}")

        bars = [
            HistoricalBar(
                ts=str(b["date"]) if not isinstance(b.get("date"), datetime)
                                  else b["date"].isoformat(),
                open=float(b.get("open") or 0),
                high=float(b.get("high") or 0),
                low=float(b.get("low") or 0),
                close=float(b.get("close") or 0),
                volume=int(b.get("volume") or 0),
            )
            for b in raw
        ]
        return HistoricalResponse(symbol=sym, instrument_token=token,
                                  interval=interval, bars=bars)
