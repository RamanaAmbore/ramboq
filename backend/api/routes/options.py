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

import math
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
    expected_value,
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
    risk_reward_ratio,
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
    # Expected value of the position at expiry (₹), integrated against
    # the lognormal pdf of the underlying using the calibrated σ. POP
    # tells you "how often you win"; EV tells you "weighted by win/loss
    # magnitudes, what the trade is worth on average".
    ev:           float
    # ev / |entry_cost| as a percentage — return-on-cost. Null when
    # entry_cost is zero (operator hasn't taken the trade yet).
    ev_pct:       float | None
    # Risk:reward = max_profit / |max_loss|. None for unbounded legs
    # (long calls, short puts) where the ratio isn't meaningful.
    rr_ratio:     float | None


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

    # Payoff x-axis range used. `span_pct` is the actual decimal fraction
    # applied (e.g. 0.06 = ±6 %); `span_sigmas` is the σ-multiple it was
    # derived from (e.g. 2.5 means the chart spans ±2.5σ at expiry). UI
    # shows the σ form in the chart footnote.
    span_pct:     float
    span_sigmas:  float


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
    legs:        list[StrategyLeg]
    spot:        float | None = None     # spot override; sim or broker otherwise
    # span_pct=None auto-derives the chart range from σ × √T (using the
    # qty-weighted IV proxy across legs and the shared expiry). Pass an
    # explicit value to override. Clamped to [1%, 50%].
    span_pct:    float | None = None
    # σ-multiple used when span_pct is None. Default 2.5 → covers ~98 %
    # of the lognormal mass at expiry.
    span_sigmas: float = 2.5
    points:      int   = 51


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
    # EV: probability-weighted expiry value (lognormal pdf over the
    # curve's spot grid). For credit strategies this is typically slightly
    # positive; for paid-premium debit strategies it depends on whether
    # the breakevens sit inside or outside the lognormal mass.
    ev:          float
    ev_pct:      float | None            # ev / |net_cost| — null when net_cost == 0
    rr_ratio:    float | None            # max_profit / |max_loss| — null when unbounded


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
    # Same provenance as single-leg /analytics — UI shows ±2.5σ in the
    # chart footnote when span_sigmas is non-zero.
    span_pct:          float = 0.10
    span_sigmas:       float = 0.0


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


def _resolve_span_pct(*, sigma: float, T_years: float,
                      span_pct: Optional[float],
                      span_sigmas: float = 2.5) -> float:
    """
    Pick the payoff-curve x-axis span. When the operator passed an
    explicit `span_pct` override, use that. Otherwise derive from the
    underlying's standard deviation at expiry:

        span_pct = span_sigmas × σ × √T_years

    σ × √T is the annualized vol scaled to the option's time-to-expiry
    (so a 7-DTE 15% IV option spans ±~5% at 2.5σ; a 60-DTE same-IV
    option spans ±~15%). Keeps the chart "tight enough to show the
    interesting region" without manual span tuning per contract.

    Clamped to [2%, 50%] so degenerate inputs (σ=0, T=0, or absurdly
    long-dated contracts) still produce a readable chart.
    """
    if span_pct is not None and span_pct > 0:
        return max(0.01, min(float(span_pct), 0.5))
    if sigma > 0 and T_years > 0:
        derived = float(span_sigmas) * sigma * math.sqrt(T_years)
        return max(0.02, min(derived, 0.5))
    # σ=0 / T=0 — fall back to a reasonable default so the operator
    # doesn't see a zero-width chart.
    return 0.10


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


def _resolve_spot(underlying: str, override: Optional[float],
                  *, fallback: Optional[float] = None
                  ) -> tuple[float, str]:
    """Spot for the underlying. Returns `(spot, source)` so the UI can
    flag stale data. Sources: 'override' | 'sim' | 'live' | 'close' |
    'depth' | 'fallback'.

    When the broker is unreachable AND no `fallback` is provided, raises
    502. With `fallback` (typically the strike of the option being
    analysed), uses that and tags `source='fallback'` so the page can
    still render a useful payoff diagram even when market-data is
    completely down.
    """
    if override is not None and override > 0:
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
    px: Optional[float] = None
    src: str = "none"
    try:
        resp = get_price_broker().quote([key]) or {}
        px, src = _ltp_from_quote(resp.get(key) or {})
    except Exception as e:
        # Broker unreachable — log + try fallback below.
        logger.warning(f"options spot quote for {underlying} failed: {e}")

    if px is not None:
        return (px, src)

    if fallback is not None and fallback > 0:
        # Last resort: use the option's strike as a degenerate spot. The
        # payoff diagram still draws sensibly (strike-centred); the
        # operator gets a 'fallback' chip so they know the spot is
        # synthetic and shouldn't be trusted for absolute P&L.
        return (float(fallback), "fallback")

    raise HTTPException(status_code=502,
                        detail=f"spot for {underlying} unavailable from any source")


def _resolve_ltp(symbol: str, mode: str, account: Optional[str],
                 override: Optional[float],
                 avg_cost_hint: Optional[float] = None,
                 *,
                 estimate_inputs: Optional[dict] = None
                 ) -> tuple[float, str]:
    """
    LTP for an option contract with full fallback chain:
      override > sim-row > broker quote(last_price > close > depth-mid)
                  > avg_cost_hint > BS-estimated.
    Returns `(price, source)` so the UI can flag stale prices. Sources:
    'override' | 'sim' | 'live' | 'close' | 'depth' | 'avg_cost' |
    'estimated'.

    `estimate_inputs` (when provided) lets the resolver synthesise an
    estimated LTP via Black-Scholes at default IV when nothing else
    works. Shape: `{'spot': S, 'strike': K, 'T_years': T, 'opt_type': 'CE'}`.
    With this, the page never returns 502 — the payoff still draws
    against an estimated price, and the UI shows an 'estimated' chip.
    """
    # Treat 0 / negative explicit overrides as "no override" so a sim
    # leg or picker that copied last_price=0 falls through to broker
    # fallbacks instead of locking in an obviously wrong number.
    if override is not None and override > 0:
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

    if avg_cost_hint is not None and avg_cost_hint > 0:
        return (float(avg_cost_hint), "avg_cost")

    # Final fallback — synthesise an LTP via Black-Scholes at default IV.
    # The payoff curve still renders something the operator can read;
    # the UI shows 'estimated' so they know not to trust absolute P&L.
    if estimate_inputs:
        S = float(estimate_inputs.get("spot") or 0)
        K = float(estimate_inputs.get("strike") or 0)
        T = float(estimate_inputs.get("T_years") or 0)
        opt = str(estimate_inputs.get("opt_type") or "CE")
        if S > 0 and K > 0 and T > 0:
            from backend.api.algo.derivatives import (
                DEFAULT_IV, black_scholes
            )
            est = black_scholes(S, K, T, DEFAULT_RISK_FREE, DEFAULT_IV, opt)
            if est > 0:
                return (est, "estimated")

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
                        span_pct: Optional[float] = None,
                        span_sigmas: float = 2.5,
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
        # Spot first, with the strike as a synthetic-spot fallback so
        # the page never 502s when broker market-data is down. The
        # response carries spot_source='fallback' in that case.
        S, spot_src = _resolve_spot(parsed["underlying"], spot,
                                    fallback=parsed["strike"])
        T_yrs = days_to_expiry(parsed["expiry"]) / 365.0
        # Pass avg_cost AND estimated-BS inputs as last-resort fallbacks
        # so a stale broker quote on an illiquid contract still produces
        # a usable payoff curve. ltp_source='estimated' tells the UI it
        # came from BS at default IV against the resolved spot.
        ltp_val, ltp_src = _resolve_ltp(
            sym, mode, acct_resolved or account, ltp,
            avg_cost_hint=avg_resolved if avg_resolved > 0 else avg_cost,
            estimate_inputs={
                "spot":      S,
                "strike":    parsed["strike"],
                "T_years":   T_yrs,
                "opt_type":  parsed["opt_type"],
            },
        )
        # IV: explicit override > calibrate from current LTP > default
        if iv is not None and iv > 0:
            sigma     = float(iv)
            iv_src    = "override"
        else:
            calibrated = implied_vol(ltp_val, S, parsed["strike"], T_yrs,
                                     DEFAULT_RISK_FREE, parsed["opt_type"])
            # implied_vol returns DEFAULT_IV (0.15) on bracket failure or
            # near-intrinsic / degenerate inputs; treat that as the
            # "default" source so the UI can flag it. Estimated-LTP
            # fallback also forces 'default' since the calibration
            # would just be a self-referential round-trip.
            if (calibrated == DEFAULT_IV
                or ltp_src in ("close", "depth", "avg_cost", "estimated")):
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
        # Span auto-derived from σ × √T so short-DTE charts don't show
        # an absurd ±10% range and long-DTE charts aren't squashed.
        # Operator can override by passing span_pct explicitly.
        span_pct_resolved = _resolve_span_pct(
            sigma=sigma, T_years=T_yrs,
            span_pct=span_pct, span_sigmas=span_sigmas,
        )
        curve = payoff_curve(
            S=S, K=parsed["strike"], T_years=T_yrs,
            r=DEFAULT_RISK_FREE, sigma=sigma,
            opt_type=parsed["opt_type"], qty=qty_resolved,
            entry_price=entry,
            span_pct=span_pct_resolved,
            points=max(11, min(int(points), 101)),
        )

        # Sanitize +inf in JSON — msgspec will choke; the API surface
        # uses null and the UI renders "∞".
        def _finite_or_null(x: float) -> float | None:
            return None if x == float("inf") or x == float("-inf") else x

        # Position-level expected value via lognormal integration over
        # the payoff curve. Tells the operator "weighted by win/loss
        # magnitudes, what's this trade worth on average?" — POP alone
        # only answers "how often I win" without sizing.
        ev = expected_value(curve, S=S, T_years=T_yrs, sigma=sigma)
        # ev_pct: return on what it cost to enter, as a percentage. Null
        # when entry is zero (operator typed a hypothetical with no cost).
        cost_basis = abs(entry * qty_resolved)
        ev_pct = round(ev / cost_basis * 100.0, 2) if cost_basis > 0 else None
        rr = risk_reward_ratio(_finite_or_null(risk["max_profit"]),
                               _finite_or_null(risk["max_loss"]))

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
                ev=ev,
                ev_pct=ev_pct,
                rr_ratio=rr,
            ),
            payoff=[PayoffPoint(**p) for p in curve],
            ltp_source=ltp_src,
            spot_source=spot_src,
            iv_source=iv_src,
            span_pct=span_pct_resolved,
            span_sigmas=float(span_sigmas) if span_pct is None else 0.0,
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
        # it up on `exchange`. Stock options on BSE will land under BFO,
        # so we also check that exchange when NFO misses.
        from backend.shared.brokers.registry import get_price_broker
        broker = get_price_broker()
        token: int | None = None
        try:
            for ex in (exchange, "BFO", "NSE", "BSE"):
                if ex == exchange and token:
                    break
                insts = broker.instruments(ex) or []
                for inst in insts:
                    if str(inst.get("tradingsymbol") or "").upper() == sym:
                        token = int(inst.get("instrument_token"))
                        break
                if token:
                    break
        except Exception as e:
            # Broker unreachable — return empty bars instead of 502 so
            # the page renders an "unavailable" state without ripping
            # the whole panel.
            logger.warning(f"options historical instrument lookup failed: {e}")
            return HistoricalResponse(symbol=sym, instrument_token=None,
                                      interval=interval, bars=[])
        if not token:
            # Symbol not in any of the exchanges we tried (uncommon
            # contract / typo / out-of-cycle expiry). Return empty
            # bars + null token; the UI shows an "unavailable" message
            # instead of a 404 ripping the whole panel.
            logger.info(f"options historical: '{sym}' not found in NFO/BFO/NSE/BSE")
            return HistoricalResponse(symbol=sym, instrument_token=None,
                                      interval=interval, bars=[])

        # Kite historical_data returns list[dict] with OHLCV. Failures
        # here (rate-limited, contract not yet listed, off-hours quirks)
        # also degrade to empty bars instead of 502.
        try:
            kite = broker.kite  # type: ignore[attr-defined]
            to_d   = datetime.now()
            from_d = to_d - timedelta(days=days)
            raw    = kite.historical_data(token, from_d, to_d, interval) or []
        except Exception as e:
            logger.warning(f"options historical_data failed for {sym}: {e}")
            return HistoricalResponse(symbol=sym, instrument_token=token,
                                      interval=interval, bars=[])

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
        try:
            return await self._strategy_analytics_impl(data)
        except HTTPException:
            raise
        except Exception:
            # Log the full traceback so 500s in this endpoint are
            # debuggable — Litestar's default 500 handler swallows the
            # exception text. Re-raise as a 500 with a generic message
            # so the operator at least sees something actionable.
            logger.exception("Strategy analytics failed (legs=%s)", data.legs)
            raise HTTPException(status_code=500,
                detail="Strategy analytics failed; see server logs.")

    async def _strategy_analytics_impl(self, data: "StrategyRequest") -> "StrategyResponse":
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
            if not parsed or parsed.get("kind") not in ("opt", "fut"):
                raise HTTPException(
                    status_code=400,
                    detail=f"'{sym}' isn't a recognised option or futures contract."
                )
            underlyings.add(parsed["underlying"])
            expiries.add(parsed["expiry"].isoformat())
            # Trigger broker fetch when ltp is missing OR explicitly 0
            # (sim picker that copied a stale last_price=0 would otherwise
            # bypass the fetch and fall straight to avg_cost).
            if leg.ltp is None or leg.ltp <= 0:
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

        # ── 2. Resolve spot (request override > sim > broker > fallback) ─
        # Strike-of-the-median-leg used as the synthetic-spot fallback so
        # the strategy still draws a payoff curve even when broker market
        # data is fully unreachable. The response carries no spot_source
        # field today, but the per-leg ltp_source='estimated' or 'fallback'
        # downstream gives the operator the right "treat with care" signal.
        # Only options have strikes — futures contribute no strike anchor
        # to the synthetic-spot fallback. parse_tradingsymbol() returns a
        # dict without `strike` for kind=fut, so guard the access here
        # (otherwise KeyError → 500 when a futures leg is in the basket).
        sorted_strikes = sorted({
            p["strike"]
            for l in data.legs
            if (p := parse_tradingsymbol(l.symbol)) and "strike" in p
        })
        median_strike = (sorted_strikes[len(sorted_strikes) // 2]
                         if sorted_strikes else None)
        S, _spot_src = _resolve_spot(underlying, data.spot,
                                     fallback=median_strike)

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

            # ── Futures branch ─────────────────────────────────────
            # Linear payoff in spot, no IV, no Greeks beyond delta=1.
            # Resolve LTP from operator override → broker quote → spot
            # (futures track spot 1:1 over the sim window). Cost basis
            # falls back to LTP for "what would buying NOW look like".
            if parsed.get("kind") == "fut":
                fut_ltp: Optional[float] = None
                fut_src: str = "none"
                if leg.ltp is not None and leg.ltp > 0:
                    fut_ltp, fut_src = float(leg.ltp), "override"
                else:
                    q = quote_resp.get(f"NFO:{sym}") or {}
                    fut_ltp, fut_src = _ltp_from_quote(q)
                if fut_ltp is None and leg.avg_cost is not None and leg.avg_cost > 0:
                    fut_ltp, fut_src = float(leg.avg_cost), "avg_cost"
                if fut_ltp is None or fut_ltp <= 0:
                    fut_ltp, fut_src = float(S), "estimated"
                fut_entry = float(leg.avg_cost) if leg.avg_cost is not None else fut_ltp
                resolved_legs.append({
                    "kind":        "fut",
                    "qty":         qty,
                    "entry_price": fut_entry,
                })
                # Greeks for the leg detail row — futures contribute
                # delta=±1 only; everything else is zero.
                fut_g = {"delta": 1.0, "gamma": 0.0, "theta": 0.0,
                         "vega": 0.0, "rho": 0.0}
                leg_details.append({
                    "symbol":      sym,
                    "opt_type":    "FUT",
                    "strike":      0.0,
                    "qty":         qty,
                    "avg_cost":    fut_entry,
                    "ltp":         fut_ltp,
                    "iv":          0.0,
                    "theoretical": fut_ltp,    # futures are linear; no separate theo
                    "discrepancy": 0.0,
                    "greeks":      fut_g,
                    "ltp_source":  fut_src,
                    "iv_source":   "n/a",
                })
                continue

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
            # Final fallback — synthesise via Black-Scholes at default IV
            # against the resolved spot. The strategy still produces a
            # readable payoff curve when the broker is fully unreachable;
            # leg.ltp_source='estimated' tells the UI to treat absolute
            # numbers with care.
            # NOTE: DEFAULT_IV + black_scholes are imported at module
            # level — DON'T re-import here. A `from … import DEFAULT_IV`
            # inside this branch makes Python flag DEFAULT_IV as a local
            # for the WHOLE function, then the comparison further down
            # raises UnboundLocalError when this branch never runs.
            if ltp_val is None or ltp_val <= 0:
                est = black_scholes(S, parsed["strike"], T_yrs,
                                    DEFAULT_RISK_FREE, DEFAULT_IV,
                                    parsed["opt_type"])
                if est > 0:
                    ltp_val, ltp_source = est, "estimated"
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
                # Fresh sources: live (broker last_price), override
                # (operator-supplied), sim (driver state). Anything else
                # means the LTP was a fallback so the calibrated σ
                # shouldn't be trusted as authoritative.
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

        # Span auto-derived from the qty-weighted σ × √T_shared so the
        # chart automatically tightens for short-DTE strategies and
        # widens for long-DTE ones. Operator override via data.span_pct.
        span_pct_resolved = _resolve_span_pct(
            sigma=sigma_proxy, T_years=T_yrs_shared,
            span_pct=data.span_pct, span_sigmas=data.span_sigmas,
        )

        curve = multileg_payoff_curve(
            resolved_legs, S=S,
            span_pct=span_pct_resolved,
            points=max(11, min(int(data.points or 51), 121)),
        )
        agg_greeks  = multileg_greeks(resolved_legs, S=S)
        bes         = find_breakevens(curve)
        max_p, max_l = multileg_extremes(curve)
        pop = multileg_pop(curve, S=S, T_years=T_yrs_shared, sigma=sigma_proxy)
        net_cost = sum(l["entry_price"] * l["qty"] for l in resolved_legs)

        # Aggregate EV — same lognormal integration as single-leg, but
        # the curve already sums every leg's signed-qty payoff so this
        # is just one trapezoidal pass.
        agg_ev = expected_value(curve, S=S, T_years=T_yrs_shared,
                                sigma=sigma_proxy)
        agg_ev_pct = (round(agg_ev / abs(net_cost) * 100.0, 2)
                      if abs(net_cost) > 0 else None)
        agg_rr = risk_reward_ratio(max_p, max_l)

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
                ev=agg_ev, ev_pct=agg_ev_pct, rr_ratio=agg_rr,
            ),
            payoff=[PayoffPoint(**p) for p in curve],
            legs=[LegDetail(
                symbol=l["symbol"], opt_type=l["opt_type"], strike=l["strike"],
                qty=l["qty"], avg_cost=l["avg_cost"], ltp=l["ltp"], iv=l["iv"],
                theoretical=l["theoretical"], discrepancy=l["discrepancy"],
                greeks=OptionGreeks(**l["greeks"]),
                ltp_source=l["ltp_source"], iv_source=l["iv_source"],
            ) for l in leg_details],
            span_pct=span_pct_resolved,
            span_sigmas=float(data.span_sigmas) if data.span_pct is None else 0.0,
        )
