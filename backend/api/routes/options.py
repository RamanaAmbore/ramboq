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
from litestar import Controller, get, post
from litestar.exceptions import HTTPException

from backend.api.algo.derivatives import (
    DEFAULT_IV,
    DEFAULT_RISK_FREE,
    black_scholes,
    days_to_expiry,
    find_breakevens,
    greeks,
    implied_vol,
    multileg_extremes,
    multileg_greeks,
    multileg_payoff_curve,
    multileg_pop,
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

    # Provenance — lets the UI flag stale data with a yellow chip.
    # ltp_source ∈ {'override','sim','live','close','depth','avg_cost'}
    # spot_source ∈ {'override','sim','live','close','depth'}
    # iv_source  ∈ {'override','calibrated','default'}
    ltp_source:   str
    spot_source:  str
    iv_source:    str


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


# Multi-leg strategy schemas. Each leg can come from any source — live
# broker, simulator, or operator imagination. The route resolves missing
# LTPs by hitting the broker; sim legs supply ltp inline so no broker
# round-trip is needed for them.
class StrategyLeg(msgspec.Struct):
    symbol:    str
    qty:       int                       # signed: + long, − short
    avg_cost:  float | None = None       # per-share entry premium; defaults to ltp
    ltp:       float | None = None       # current premium; fetched from broker if absent
    iv:        float | None = None       # IV override; calibrated from ltp otherwise


class StrategyRequest(msgspec.Struct):
    legs:     list[StrategyLeg]
    spot:     float | None = None        # spot override; sim or broker otherwise
    span_pct: float = 0.10               # ±span around current spot
    points:   int   = 51


class LegDetail(msgspec.Struct):
    symbol:       str
    opt_type:     str
    strike:       float
    qty:          int
    avg_cost:     float
    ltp:          float
    iv:           float
    theoretical:  float
    discrepancy:  float
    greeks:       OptionGreeks
    # Provenance per leg — UI flags any leg whose LTP came from a fallback
    # (close / avg_cost) so the operator knows which numbers to trust.
    ltp_source:   str = "live"
    iv_source:    str = "calibrated"


class StrategyRisk(msgspec.Struct):
    max_profit:  float                   # numerical max — only as wide as the curve
    max_loss:    float
    breakevens:  list[float]
    pop:         float                   # 0..1


class StrategyResponse(msgspec.Struct):
    underlying:        str
    expiry:            str
    days_to_expiry:    float
    spot:              float
    net_cost:          float             # signed: + paid, − collected
    net_qty:           int               # ∑ signed qty (just for the header)
    iv_proxy:          float             # qty-weighted IV used by POP
    aggregate_greeks:  OptionGreeks
    risk:              StrategyRisk
    payoff:            list[PayoffPoint]
    legs:              list[LegDetail]


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


def _ltp_from_quote(q: dict) -> tuple[Optional[float], str]:
    """
    Pick the best price out of a Kite quote dict. Order:
      1. last_price (live, freshest)
      2. ohlc.close (previous-day close — stale but real)
      3. depth mid (bid+ask)/2 if both present
    Returns `(price, source)` where source ∈ {'live','close','depth','none'}.
    """
    if not q:
        return (None, "none")
    lp = q.get("last_price")
    if lp not in (None, 0, 0.0):
        return (float(lp), "live")
    ohlc  = q.get("ohlc") or {}
    close = ohlc.get("close")
    if close not in (None, 0, 0.0):
        return (float(close), "close")
    depth = q.get("depth") or {}
    buy   = (depth.get("buy")  or [{}])[0]
    sell  = (depth.get("sell") or [{}])[0]
    bid   = buy.get("price")
    ask   = sell.get("price")
    if bid and ask and bid > 0 and ask > 0:
        return ((float(bid) + float(ask)) / 2.0, "depth")
    return (None, "none")


def _resolve_spot(underlying: str, override: Optional[float]
                  ) -> tuple[float, str]:
    """Spot for the underlying. Returns `(spot, source)` so the caller
    can flag stale data in the response. Sources: 'override' | 'sim' |
    'live' | 'close' | 'depth'. Raises 502 only if every source fails."""
    if override is not None:
        return (float(override), "override")
    try:
        from backend.api.algo.sim.driver import get_driver
        drv = get_driver()
        if drv.active and underlying in drv._underlyings:
            return (float(drv._underlyings[underlying]), "sim")
    except Exception:
        pass

    from backend.shared.brokers.registry import get_price_broker
    key = underlying_ltp_key(underlying)
    try:
        resp = get_price_broker().quote([key]) or {}
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"broker quote for {underlying} failed: {e}")
    px, src = _ltp_from_quote(resp.get(key) or {})
    if px is None:
        raise HTTPException(status_code=502,
                            detail=f"spot for {underlying} unavailable from broker")
    return (px, src)


def _resolve_ltp(symbol: str, mode: str, account: Optional[str],
                 override: Optional[float],
                 avg_cost_hint: Optional[float] = None
                 ) -> tuple[float, str]:
    """
    LTP for an option contract with full fallback chain:
      override > sim-row > broker quote(last_price > close > depth-mid)
                  > avg_cost_hint > 502.
    Returns `(price, source)` so the UI can flag stale prices. Sources:
    'override' | 'sim' | 'live' | 'close' | 'depth' | 'avg_cost'.
    """
    if override is not None:
        return (float(override), "override")

    if mode == "sim":
        from backend.api.algo.sim.driver import get_driver
        for r in get_driver()._positions_rows:
            if str(r.get("tradingsymbol", "")).upper() == symbol.upper():
                lp = r.get("last_price")
                if lp not in (None, 0, 0.0):
                    return (float(lp), "sim")
        # Sim mode but no row — operator may be requesting a contract
        # outside the sim. Fall through to broker fallbacks (handy when
        # the sim is paused but real-data analytics are still useful).

    from backend.shared.brokers.registry import get_price_broker
    key = f"NFO:{symbol}"
    try:
        resp = get_price_broker().quote([key]) or {}
    except Exception as e:
        logger.warning(f"options LTP quote() failed for {symbol}: {e}")
        resp = {}
    price, src = _ltp_from_quote(resp.get(key) or {})
    if price is not None:
        return (price, src)

    # Final fallbacks — if the operator told us what they paid, use that
    # so the payoff still draws something useful even when the broker
    # has nothing to say (illiquid contract, off-hours, weekend).
    if avg_cost_hint is not None and avg_cost_hint > 0:
        return (float(avg_cost_hint), "avg_cost")
    raise HTTPException(
        status_code=502,
        detail=(f"No LTP available for '{symbol}' from any source "
                f"(broker quote, sim, avg_cost). "
                f"Pass `ltp=<value>` to override.")
    )


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
        S, spot_src = _resolve_spot(parsed["underlying"], spot)
        # Pass avg_cost as a last-resort fallback so a stale broker
        # quote on an illiquid contract still produces a usable payoff.
        ltp_val, ltp_src = _resolve_ltp(
            sym, mode, acct_resolved or account, ltp,
            avg_cost_hint=avg_resolved if avg_resolved > 0 else avg_cost,
        )

        T_yrs = days_to_expiry(parsed["expiry"]) / 365.0
        # IV: explicit override > calibrate from current LTP > default
        if iv is not None and iv > 0:
            sigma     = float(iv)
            iv_src    = "override"
        else:
            calibrated = implied_vol(ltp_val, S, parsed["strike"], T_yrs,
                                     DEFAULT_RISK_FREE, parsed["opt_type"])
            # implied_vol returns DEFAULT_IV (0.15) on bracket failure or
            # near-intrinsic / degenerate inputs; treat that as the
            # "default" source so the UI can flag it.
            if (calibrated == DEFAULT_IV
                or ltp_src in ("close", "depth", "avg_cost")):
                sigma  = calibrated
                iv_src = "default" if calibrated == DEFAULT_IV else "calibrated"
            else:
                sigma  = calibrated
                iv_src = "calibrated"

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
            ltp_source=ltp_src,
            spot_source=spot_src,
            iv_source=iv_src,
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

    # ── Multi-leg strategy analytics (POST) ────────────────────────────

    @post("/strategy-analytics")
    async def strategy_analytics(self, data: "StrategyRequest") -> "StrategyResponse":
        """
        Aggregate analytics for a multi-leg single-underlying strategy
        (vertical spread, iron condor, butterfly, strangle, etc.).
        Accepts a list of legs; v1 requires every leg to share the same
        underlying and same expiry.

        Per-leg `ltp` and `avg_cost` are optional — if provided (e.g.
        legs sourced from the simulator), they're used directly; if
        missing, the broker is hit for the current LTP and `avg_cost`
        falls back to the LTP (treats the leg as "what if I open this
        right now").
        """
        if not data.legs:
            raise HTTPException(status_code=400, detail="legs is required")

        # ── 1. Resolve metadata + LTP per leg ─────────────────────────
        resolved_legs: list[dict] = []
        underlyings: set[str] = set()
        expiries: set[str]    = set()
        from backend.shared.brokers.registry import get_price_broker

        # Bulk quote fetch — for legs without operator-supplied ltp, hit
        # broker.quote() once (richer than ltp(): includes ohlc.close +
        # depth, so the per-leg fallback can pick `close` when no live
        # last_price is on the wire — handy for off-hours / illiquid).
        need_quote: dict[str, str] = {}   # nfo_key → leg_symbol
        for leg in data.legs:
            sym = (leg.symbol or "").upper().strip()
            if not sym:
                raise HTTPException(status_code=400, detail="leg.symbol is required")
            parsed = parse_tradingsymbol(sym)
            if not parsed or parsed.get("kind") != "opt":
                raise HTTPException(
                    status_code=400,
                    detail=f"'{sym}' isn't a recognised option contract."
                )
            underlyings.add(parsed["underlying"])
            expiries.add(parsed["expiry"].isoformat())
            if leg.ltp is None:
                need_quote[f"NFO:{sym}"] = sym

        if len(underlyings) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"All legs must share an underlying; got {sorted(underlyings)}"
            )
        if len(expiries) > 1:
            raise HTTPException(
                status_code=400,
                detail=(f"All legs must share an expiry (v1 doesn't support "
                        f"calendar / diagonal spreads); got {sorted(expiries)}")
            )
        underlying = next(iter(underlyings))

        quote_resp: dict = {}
        if need_quote:
            try:
                quote_resp = get_price_broker().quote(list(need_quote.keys())) or {}
            except Exception as e:
                # Don't fail the whole request — sim legs and operator
                # overrides + per-leg fallbacks (avg_cost) can still
                # produce useful output. Surface a warning so the UI can
                # flag the legs whose LTP came from a fallback.
                logger.warning(f"Strategy quote() failed: {e}")

        # ── 2. Resolve spot (request override > sim > broker) ─────────
        S: float
        if data.spot is not None and data.spot > 0:
            S = float(data.spot)
        else:
            try:
                from backend.api.algo.sim.driver import get_driver
                drv = get_driver()
                if drv.active and underlying in drv._underlyings:
                    S = float(drv._underlyings[underlying])
                else:
                    raise RuntimeError("no sim spot")
            except Exception:
                key = underlying_ltp_key(underlying)
                try:
                    resp = get_price_broker().ltp([key]) or {}
                except Exception as e:
                    raise HTTPException(status_code=502,
                        detail=f"underlying spot unavailable: {e}")
                q = resp.get(key) or {}
                lp = q.get("last_price")
                if lp is None:
                    raise HTTPException(status_code=502,
                        detail=f"spot for {underlying} unavailable")
                S = float(lp)

        # ── 3. Build resolved-leg list with σ calibrated per leg ──────
        T_yrs_shared = 0.0
        sigma_weight_num = 0.0
        sigma_weight_den = 0.0
        leg_details: list[dict] = []
        for leg in data.legs:
            sym = leg.symbol.upper().strip()
            parsed = parse_tradingsymbol(sym)
            T_yrs = days_to_expiry(parsed["expiry"]) / 365.0
            T_yrs_shared = T_yrs
            qty   = int(leg.qty or 0)
            if qty == 0:
                raise HTTPException(status_code=400,
                    detail=f"leg '{sym}' has qty=0")

            # LTP fallback chain — return `(price, source)` so the UI can
            # flag stale legs. Order:
            #   operator override → broker live/close/depth → avg_cost → fail
            ltp_val: Optional[float]
            ltp_source: str
            if leg.ltp is not None and leg.ltp > 0:
                ltp_val, ltp_source = float(leg.ltp), "override"
            else:
                q = quote_resp.get(f"NFO:{sym}") or {}
                ltp_val, ltp_source = _ltp_from_quote(q)
            # Fallback to operator's avg_cost if no broker price was usable.
            if ltp_val is None and leg.avg_cost is not None and leg.avg_cost > 0:
                ltp_val, ltp_source = float(leg.avg_cost), "avg_cost"
            if ltp_val is None or ltp_val <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=(f"Leg '{sym}' has no usable price. Pass `ltp` "
                            f"or `avg_cost` in the leg body (sim positions "
                            f"and illiquid contracts often need this).")
                )

            # σ fallback — operator override > calibrate > default IV.
            # When the LTP came from a fallback (close/avg_cost) the
            # calibration uses a stale price, so flag iv_source as
            # 'default' so the UI doesn't treat the σ as authoritative.
            iv_source: str
            if leg.iv is not None and leg.iv > 0:
                sig = float(leg.iv)
                iv_source = "override"
            else:
                sig = implied_vol(ltp_val, S, parsed["strike"], T_yrs,
                                  DEFAULT_RISK_FREE, parsed["opt_type"])
                if sig == DEFAULT_IV or ltp_source not in ("override", "live", "sim"):
                    iv_source = "default" if sig == DEFAULT_IV else "calibrated"
                else:
                    iv_source = "calibrated"

            # Cost basis: operator > LTP fallback (just-opened semantics)
            entry = float(leg.avg_cost) if leg.avg_cost is not None else ltp_val

            # Theoretical for the leg + per-share Greeks (UI shows them).
            theo = black_scholes(S, parsed["strike"], T_yrs,
                                 DEFAULT_RISK_FREE, sig, parsed["opt_type"])
            g_per = greeks(S, parsed["strike"], T_yrs,
                           DEFAULT_RISK_FREE, sig, parsed["opt_type"])

            resolved_legs.append({
                "strike":      parsed["strike"],
                "opt_type":    parsed["opt_type"],
                "qty":         qty,
                "entry_price": entry,
                "T_years":     T_yrs,
                "sigma":       sig,
            })
            sigma_weight_num += sig * abs(qty)
            sigma_weight_den += abs(qty)
            leg_details.append({
                "symbol":      sym,
                "opt_type":    parsed["opt_type"],
                "strike":      parsed["strike"],
                "qty":         qty,
                "avg_cost":    entry,
                "ltp":         ltp_val,
                "iv":          sig,
                "theoretical": theo,
                "discrepancy": ltp_val - theo,
                "greeks":      g_per,
                "ltp_source":  ltp_source,
                "iv_source":   iv_source,
            })

        # ── 4. Aggregate analytics ────────────────────────────────────
        # qty-weighted IV used for the lognormal that drives POP. Imperfect
        # (the real underlying σ isn't the same as any leg's IV) but it's
        # the most defensible single number from the data we have.
        sigma_proxy = (sigma_weight_num / sigma_weight_den
                       if sigma_weight_den else DEFAULT_IV)

        curve = multileg_payoff_curve(
            resolved_legs, S=S,
            span_pct=max(0.01, min(float(data.span_pct or 0.10), 0.5)),
            points=max(11, min(int(data.points or 51), 121)),
        )
        agg_greeks  = multileg_greeks(resolved_legs, S=S)
        bes         = find_breakevens(curve)
        max_p, max_l = multileg_extremes(curve)
        pop = multileg_pop(curve, S=S, T_years=T_yrs_shared, sigma=sigma_proxy)
        net_cost = sum(l["entry_price"] * l["qty"] for l in resolved_legs)

        return StrategyResponse(
            underlying=underlying,
            expiry=next(iter(expiries)),
            days_to_expiry=days_to_expiry(parsed["expiry"]),
            spot=S,
            net_cost=net_cost,
            net_qty=sum(int(l["qty"]) for l in resolved_legs),
            iv_proxy=sigma_proxy,
            aggregate_greeks=OptionGreeks(**agg_greeks),
            risk=StrategyRisk(
                max_profit=max_p, max_loss=max_l,
                breakevens=bes, pop=pop,
            ),
            payoff=[PayoffPoint(**p) for p in curve],
            legs=[LegDetail(
                symbol=l["symbol"], opt_type=l["opt_type"], strike=l["strike"],
                qty=l["qty"], avg_cost=l["avg_cost"], ltp=l["ltp"], iv=l["iv"],
                theoretical=l["theoretical"], discrepancy=l["discrepancy"],
                greeks=OptionGreeks(**l["greeks"]),
                ltp_source=l["ltp_source"], iv_source=l["iv_source"],
            ) for l in leg_details],
        )
