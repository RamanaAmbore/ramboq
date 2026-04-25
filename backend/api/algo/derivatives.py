"""
Derivatives helpers — Indian F&O symbol parser + Black-Scholes pricer +
implied-volatility calibrator. Used by the simulator to drive coherent
option/future re-pricing off a single underlying spot move (so a "−3%
NIFTY" tick re-prices every NIFTY call/put/future at once instead of
moving each contract in isolation).

Conventions:
  - Risk-free rate `r` defaults to 7 % (Indian 91-day T-bill, close enough
    for a sim that runs in minutes).
  - Day count: 365.
  - Vega/theta deliberately ignored — sim runs are minutes, not days, so
    the time-value bleed is a rounding error against the spot delta.
  - IV is locked at sim start by inverting BS against each option's current
    LTP. Subsequent ticks re-price with that cached σ. A scripted scenario
    can override per-position via `iv: 0.18` on the position dict; otherwise
    the calibrator runs on whatever LTP comes from the seed.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Optional


DEFAULT_RISK_FREE   = 0.07     # 7% annualized
DEFAULT_DTE_DAYS    = 7        # fallback when neither row.expiry nor symbol parse yields a date
DEFAULT_IV          = 0.15     # 15% annualized — fallback when calibration fails
SECONDS_PER_YEAR    = 365 * 24 * 60 * 60


# ── Symbol parser ─────────────────────────────────────────────────────

# Monthly options:  NIFTY25APR22000CE, BANKNIFTY25APR48000PE, RELIANCE25APR2800CE
_OPT_MONTHLY = re.compile(r"^([A-Z]+?)(\d{2})([A-Z]{3})(\d+(?:\.\d+)?)(CE|PE)$")
# Weekly options (Kite uses single-digit month + 2-digit day): NIFTY25424CE = 24-Apr-25
# Format: NIFTY YY M DD STRIKE CE/PE  where M is 1-9 / O / N / D
_OPT_WEEKLY = re.compile(
    r"^([A-Z]+?)(\d{2})([1-9OND])(\d{2})(\d+(?:\.\d+)?)(CE|PE)$"
)
# Monthly futures: NIFTY25APRFUT
_FUT_MONTHLY = re.compile(r"^([A-Z]+?)(\d{2})([A-Z]{3})FUT$")

_MONTH_BY_CODE_LONG = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
_MONTH_BY_CODE_SHORT = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "O": 10, "N": 11, "D": 12,
}


def parse_tradingsymbol(symbol: str) -> Optional[dict]:
    """
    Parse a Kite-style F&O tradingsymbol. Returns a dict with:
        kind:        'opt' | 'fut'
        underlying:  underlying root (e.g. 'NIFTY')
        opt_type:    'CE' | 'PE'   (options only)
        strike:      float          (options only)
        expiry:      datetime.date  (best-effort — last Thursday for
                     monthly, parsed exactly for weekly)
    Returns None if the symbol doesn't match a known F&O shape (e.g.
    cash-equity holdings).
    """
    if not symbol:
        return None
    sym = symbol.upper()

    # Try monthly options first (longer match) before falling through to
    # weekly, since NIFTY25APR22000CE would otherwise back-track past the
    # 'A'/'P' boundary in the weekly pattern.
    m = _OPT_MONTHLY.match(sym)
    if m:
        und, yy, mon, strike, opt = m.groups()
        try:
            month  = _MONTH_BY_CODE_LONG[mon]
            year   = 2000 + int(yy)
            expiry = _last_thursday(year, month)
            return {"kind": "opt", "underlying": und,
                    "opt_type": opt, "strike": float(strike),
                    "expiry": expiry}
        except Exception:
            pass

    m = _OPT_WEEKLY.match(sym)
    if m:
        und, yy, mon_code, dd, strike, opt = m.groups()
        try:
            month  = _MONTH_BY_CODE_SHORT[mon_code]
            year   = 2000 + int(yy)
            day    = int(dd)
            expiry = date(year, month, day)
            return {"kind": "opt", "underlying": und,
                    "opt_type": opt, "strike": float(strike),
                    "expiry": expiry}
        except Exception:
            pass

    m = _FUT_MONTHLY.match(sym)
    if m:
        und, yy, mon = m.groups()
        try:
            month  = _MONTH_BY_CODE_LONG[mon]
            year   = 2000 + int(yy)
            expiry = _last_thursday(year, month)
            return {"kind": "fut", "underlying": und, "expiry": expiry}
        except Exception:
            pass

    return None


def _last_thursday(year: int, month: int) -> date:
    """Last Thursday of the given month — Kite's monthly expiry day."""
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    # Walk back from the first of next month
    d = first_next
    while True:
        from datetime import timedelta
        d = d - timedelta(days=1)
        if d.weekday() == 3:   # Thursday
            return d


def days_to_expiry(expiry: date, *, ref: Optional[datetime] = None,
                   default_days: int = DEFAULT_DTE_DAYS) -> float:
    """Whole + fractional days from `ref` (default: now) to `expiry`. Floors at 0."""
    if not expiry:
        return float(default_days)
    now = ref or datetime.now()
    if isinstance(expiry, datetime):
        expiry = expiry.date()
    delta = (datetime(expiry.year, expiry.month, expiry.day) - now)
    days  = delta.total_seconds() / 86400.0
    return max(0.0, days)


# ── Black-Scholes ─────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(S: float, K: float, T_years: float, r: float,
                  sigma: float, opt_type: str) -> float:
    """
    Vanilla European option price (no dividend yield — Indian index
    options pay no carry between expiries, so q=0 is fine). T_years
    is time-to-expiry in fractional years.
    """
    if S <= 0 or K <= 0:
        return 0.0
    # Degenerate cases — at expiry or zero vol → intrinsic.
    if T_years <= 0 or sigma <= 0:
        if opt_type == "CE":
            return max(0.0, S - K)
        return max(0.0, K - S)

    sqrt_T = math.sqrt(T_years)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2.0) * T_years) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T_years) * _norm_cdf(d2)
    return K * math.exp(-r * T_years) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol(price: float, S: float, K: float, T_years: float,
                r: float, opt_type: str,
                *, max_iter: int = 80, tol: float = 1e-3) -> float:
    """
    Bisection IV solver. Robust to weird-priced contracts (deep ITM,
    near-zero time value, pre-open stale LTPs) — falls back to
    DEFAULT_IV when the bisection can't bracket a solution.
    """
    if price <= 0 or S <= 0 or K <= 0 or T_years <= 0:
        return DEFAULT_IV

    intrinsic = max(0.0, S - K) if opt_type == "CE" else max(0.0, K - S)
    if price <= intrinsic + 0.05:
        # All intrinsic — vol is undefined; return a small positive number
        # so downstream re-pricing is well-behaved (price won't change much
        # from spot moves on a deep-ITM contract anyway).
        return 0.0001

    lo, hi = 0.0001, 5.0
    p_lo = black_scholes(S, K, T_years, r, lo, opt_type)
    p_hi = black_scholes(S, K, T_years, r, hi, opt_type)
    # If the target price is outside the bracket, fall back.
    if not (p_lo - 0.5 <= price <= p_hi + 0.5):
        return DEFAULT_IV

    for _ in range(max_iter):
        mid    = 0.5 * (lo + hi)
        p_mid  = black_scholes(S, K, T_years, r, mid, opt_type)
        if abs(p_mid - price) < tol:
            return mid
        if p_mid < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── Helpers used by the simulator ─────────────────────────────────────

def detect_underlying(symbol: str, row: Optional[dict] = None) -> Optional[str]:
    """Return the underlying name for a position row, or None if the
    symbol isn't a recognised derivative."""
    parsed = parse_tradingsymbol(symbol)
    if parsed:
        return parsed["underlying"]
    return None


# Index-to-Kite-LTP-key mapping. Indian index spot tickers don't follow the
# tradingsymbol convention — NIFTY's spot is "NSE:NIFTY 50", not "NSE:NIFTY".
# Stock underlyings DO match (RELIANCE option underlying = "NSE:RELIANCE"),
# so anything not in this map falls through to "NSE:<NAME>".
_INDEX_LTP_KEY = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "SENSEX":     "BSE:SENSEX",
    "BANKEX":     "BSE:BANKEX",
}


def underlying_ltp_key(underlying: str) -> str:
    """Kite quote/ltp key for an underlying's spot. Indices use their
    special tickers; stocks use NSE:<underlying>."""
    name = (underlying or "").upper()
    return _INDEX_LTP_KEY.get(name, f"NSE:{name}")


def calibrate_iv_for_row(row: dict, spot: float,
                         *, risk_free: float = DEFAULT_RISK_FREE,
                         ref_now: Optional[datetime] = None) -> Optional[float]:
    """
    Given a position row + a known underlying spot, calibrate IV so
    Black-Scholes(spot, strike, T, r, σ) matches the row's current
    last_price. Returns the σ, or None if the row isn't an option.
    """
    sym    = str(row.get("tradingsymbol") or "")
    parsed = parse_tradingsymbol(sym)
    if not parsed or parsed["kind"] != "opt":
        return None
    ltp    = row.get("last_price")
    if ltp is None or float(ltp) <= 0:
        return DEFAULT_IV
    expiry = parsed["expiry"]
    T_yrs  = days_to_expiry(expiry, ref=ref_now) / 365.0
    return implied_vol(float(ltp), float(spot), parsed["strike"],
                       T_yrs, risk_free, parsed["opt_type"])


def reprice_row(row: dict, *, spot: float, sigma: Optional[float],
                risk_free: float = DEFAULT_RISK_FREE,
                ref_now: Optional[datetime] = None) -> Optional[float]:
    """
    Re-price a derivative row given a new underlying `spot` and a cached
    σ (only used for options). Returns the new last_price, or None if
    the row isn't a recognised derivative on this underlying.

    Futures track spot 1:1 (cost-of-carry over a few minutes is sub-tick).
    """
    sym    = str(row.get("tradingsymbol") or "")
    parsed = parse_tradingsymbol(sym)
    if not parsed:
        return None
    if parsed["kind"] == "fut":
        return float(spot)
    if parsed["kind"] == "opt":
        expiry = parsed["expiry"]
        T_yrs  = days_to_expiry(expiry, ref=ref_now) / 365.0
        sig    = sigma if (sigma and sigma > 0) else DEFAULT_IV
        return black_scholes(float(spot), parsed["strike"],
                             T_yrs, risk_free, sig, parsed["opt_type"])
    return None
