"""
Curated demo book — hardcoded so operators can tweak by editing this
file. Two synthetic accounts, ~10 positions across NIFTY / BANKNIFTY
F&O, ~6 equity holdings, plausible funds. The numbers don't have to
match a real PnL day — they need to LOOK like a real F&O book so the
chart, agent fires, and risk panels render with non-trivial data.

Symbol naming uses the calendar:
  - The "current" monthly expiry is computed at module import time
    (last Thursday of the current month). When a deploy crosses month-
    end the next deploy will refresh.
  - Strikes pegged near recent NIFTY (24,000) / BANKNIFTY (52,000)
    levels — close enough to look real even as the actual indexes
    move. If you're updating these, peg to the current spot.

Avoid putting real account codes (ZG/ZJ patterns) here — `DEMO1` /
`DEMO2` are unmistakable to grep / log searches.
"""

from datetime import date, datetime, timedelta

from backend.api.schemas import (
    FundsResponse, FundsRow,
    HoldingRow, HoldingsResponse, HoldingsSummaryRow,
    PositionRow, PositionsResponse, PositionsSummaryRow,
)
from backend.shared.helpers.date_time_utils import timestamp_display

DEMO_ACCOUNTS = ("DEMO1", "DEMO2")


# ── Calendar helpers ────────────────────────────────────────────────────

def _last_thursday_of_month(d: date) -> date:
    """Last Thursday of d's month — Indian monthly F&O expiry convention."""
    next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = next_month - timedelta(days=1)
    while last_day.weekday() != 3:
        last_day -= timedelta(days=1)
    return last_day


def _next_monthly_expiry(today: date | None = None) -> date:
    today = today or date.today()
    exp = _last_thursday_of_month(today)
    if exp <= today:
        # Roll to next month
        rolled = (today.replace(day=28) + timedelta(days=14))
        exp = _last_thursday_of_month(rolled)
    return exp


def _expiry_token(d: date) -> str:
    """26APR-style — 2 digit year, MMM."""
    return f"{d.year % 100:02d}{d.strftime('%b').upper()}"


_EXPIRY = _next_monthly_expiry()
_EXP_TOK = _expiry_token(_EXPIRY)


# ── Positions (F&O) ─────────────────────────────────────────────────────
#
# A modest book that demonstrates:
#   - long futures (delta exposure)
#   - covered call (long fut + short ATM call)
#   - bull put spread (short OTM put + long deeper OTM put)
#   - naked short call (deep OTM, theta collector)
# Numbers picked so the aggregate strategy chart shows interesting
# Greeks (positive theta, negative-then-positive vega) + a real
# breakeven cluster.

def _positions_data() -> list[dict]:
    return [
        # DEMO1 — NIFTY covered call + bull put spread
        {
            "account": "DEMO1", "tradingsymbol": f"NIFTY{_EXP_TOK}FUT",
            "exchange": "NFO", "product": "NRML",
            "quantity": 50, "average_price": 24050.0, "close_price": 24180.0,
            "pnl": 6500.0, "unrealised": 6500.0, "realised": 0.0,
        },
        {
            "account": "DEMO1", "tradingsymbol": f"NIFTY{_EXP_TOK}24200CE",
            "exchange": "NFO", "product": "NRML",
            "quantity": -50, "average_price": 145.50, "close_price": 138.20,
            "pnl": 365.0, "unrealised": 365.0, "realised": 0.0,
        },
        {
            "account": "DEMO1", "tradingsymbol": f"NIFTY{_EXP_TOK}23800PE",
            "exchange": "NFO", "product": "NRML",
            "quantity": -50, "average_price": 72.10, "close_price": 58.30,
            "pnl": 690.0, "unrealised": 690.0, "realised": 0.0,
        },
        {
            "account": "DEMO1", "tradingsymbol": f"NIFTY{_EXP_TOK}23600PE",
            "exchange": "NFO", "product": "NRML",
            "quantity": 50, "average_price": 38.40, "close_price": 31.80,
            "pnl": -330.0, "unrealised": -330.0, "realised": 0.0,
        },

        # DEMO2 — BANKNIFTY iron-condor sketch + a naked short call
        {
            "account": "DEMO2", "tradingsymbol": f"BANKNIFTY{_EXP_TOK}53000CE",
            "exchange": "NFO", "product": "NRML",
            "quantity": -25, "average_price": 218.50, "close_price": 192.40,
            "pnl": 652.5, "unrealised": 652.5, "realised": 0.0,
        },
        {
            "account": "DEMO2", "tradingsymbol": f"BANKNIFTY{_EXP_TOK}53500CE",
            "exchange": "NFO", "product": "NRML",
            "quantity": 25, "average_price": 105.30, "close_price": 88.90,
            "pnl": -410.0, "unrealised": -410.0, "realised": 0.0,
        },
        {
            "account": "DEMO2", "tradingsymbol": f"BANKNIFTY{_EXP_TOK}51000PE",
            "exchange": "NFO", "product": "NRML",
            "quantity": -25, "average_price": 195.80, "close_price": 168.20,
            "pnl": 690.0, "unrealised": 690.0, "realised": 0.0,
        },
        {
            "account": "DEMO2", "tradingsymbol": f"BANKNIFTY{_EXP_TOK}50500PE",
            "exchange": "NFO", "product": "NRML",
            "quantity": 25, "average_price": 92.40, "close_price": 78.10,
            "pnl": -357.5, "unrealised": -357.5, "realised": 0.0,
        },
        # Naked short — deep OTM, slow theta drip
        {
            "account": "DEMO2", "tradingsymbol": f"BANKNIFTY{_EXP_TOK}54000CE",
            "exchange": "NFO", "product": "NRML",
            "quantity": -50, "average_price": 42.80, "close_price": 31.20,
            "pnl": 580.0, "unrealised": 580.0, "realised": 0.0,
        },
    ]


# ── Holdings (cash equities) ───────────────────────────────────────────

def _holdings_data() -> list[dict]:
    return [
        # DEMO1
        {"account": "DEMO1", "tradingsymbol": "RELIANCE",  "exchange": "NSE",
         "quantity": 50, "average_price": 2810.50, "close_price": 2924.30,
         "day_change": 18.40},
        {"account": "DEMO1", "tradingsymbol": "INFY",      "exchange": "NSE",
         "quantity": 100, "average_price": 1480.20, "close_price": 1518.65,
         "day_change":  6.10},
        {"account": "DEMO1", "tradingsymbol": "HDFCBANK",  "exchange": "NSE",
         "quantity": 75,  "average_price": 1645.80, "close_price": 1612.40,
         "day_change": -4.20},
        # DEMO2
        {"account": "DEMO2", "tradingsymbol": "TCS",       "exchange": "NSE",
         "quantity": 40,  "average_price": 3920.00, "close_price": 4044.20,
         "day_change": 28.30},
        {"account": "DEMO2", "tradingsymbol": "ITC",       "exchange": "NSE",
         "quantity": 200, "average_price": 412.30,  "close_price": 425.80,
         "day_change":  2.40},
        {"account": "DEMO2", "tradingsymbol": "ASIANPAINT","exchange": "NSE",
         "quantity": 30,  "average_price": 2850.20, "close_price": 2790.50,
         "day_change": -12.80},
    ]


# ── Funds (cash + margin) ──────────────────────────────────────────────

def _funds_data() -> list[dict]:
    return [
        {"account": "DEMO1", "cash": 425_000.0, "avail_margin": 218_400.0,
         "used_margin": 184_500.0, "collateral": 92_000.0},
        {"account": "DEMO2", "cash": 380_000.0, "avail_margin": 196_300.0,
         "used_margin": 165_200.0, "collateral":  70_500.0},
    ]


# ── Response builders ──────────────────────────────────────────────────
# The fixtures above are structural; these turn them into the schema
# shapes the existing /api/positions, /api/holdings, /api/funds
# endpoints already return.

def get_positions_response() -> PositionsResponse:
    raw = _positions_data()
    rows = [PositionRow(**r) for r in raw]
    # Per-account totals + grand total — same shape the live endpoint emits.
    totals: dict[str, float] = {}
    for r in raw:
        totals[r["account"]] = totals.get(r["account"], 0.0) + float(r["pnl"])
    summary_rows = [PositionsSummaryRow(account=k, pnl=v) for k, v in totals.items()]
    summary_rows.append(PositionsSummaryRow(account="TOTAL", pnl=sum(totals.values())))
    return PositionsResponse(rows=rows, summary=summary_rows, refreshed_at=timestamp_display())


def get_holdings_response() -> HoldingsResponse:
    raw = _holdings_data()
    rows: list[HoldingRow] = []
    per_acct: dict[str, dict] = {}
    for r in raw:
        inv_val = r["average_price"] * r["quantity"]
        cur_val = r["close_price"]   * r["quantity"]
        pnl     = cur_val - inv_val
        pnl_pct = (pnl / inv_val * 100.0) if inv_val else 0.0
        day_val = r["day_change"]    * r["quantity"]
        day_pct = (day_val / inv_val * 100.0) if inv_val else 0.0
        rows.append(HoldingRow(
            account=r["account"],
            tradingsymbol=r["tradingsymbol"],
            exchange=r["exchange"],
            quantity=r["quantity"],
            average_price=r["average_price"],
            close_price=r["close_price"],
            inv_val=round(inv_val, 2),
            cur_val=round(cur_val, 2),
            pnl=round(pnl, 2),
            pnl_percentage=round(pnl_pct, 2),
            day_change=r["day_change"],
            day_change_val=round(day_val, 2),
            day_change_percentage=round(day_pct, 2),
        ))
        agg = per_acct.setdefault(r["account"], {"inv_val": 0, "cur_val": 0, "pnl": 0, "day_val": 0})
        agg["inv_val"] += inv_val
        agg["cur_val"] += cur_val
        agg["pnl"]     += pnl
        agg["day_val"] += day_val

    summary_rows: list[HoldingsSummaryRow] = []
    grand_inv = grand_cur = grand_pnl = grand_day = 0.0
    for acct, agg in per_acct.items():
        summary_rows.append(HoldingsSummaryRow(
            account=acct,
            inv_val=round(agg["inv_val"], 2),
            cur_val=round(agg["cur_val"], 2),
            pnl=round(agg["pnl"], 2),
            pnl_percentage=round(agg["pnl"] / agg["inv_val"] * 100.0, 2) if agg["inv_val"] else 0.0,
            day_change_val=round(agg["day_val"], 2),
            day_change_percentage=round(agg["day_val"] / agg["inv_val"] * 100.0, 2) if agg["inv_val"] else 0.0,
        ))
        grand_inv += agg["inv_val"]; grand_cur += agg["cur_val"]
        grand_pnl += agg["pnl"];     grand_day += agg["day_val"]
    summary_rows.append(HoldingsSummaryRow(
        account="TOTAL",
        inv_val=round(grand_inv, 2),
        cur_val=round(grand_cur, 2),
        pnl=round(grand_pnl, 2),
        pnl_percentage=round(grand_pnl / grand_inv * 100.0, 2) if grand_inv else 0.0,
        day_change_val=round(grand_day, 2),
        day_change_percentage=round(grand_day / grand_inv * 100.0, 2) if grand_inv else 0.0,
    ))
    return HoldingsResponse(rows=rows, summary=summary_rows, refreshed_at=timestamp_display())


def get_funds_response() -> FundsResponse:
    rows = [FundsRow(**r) for r in _funds_data()]
    return FundsResponse(rows=rows, refreshed_at=timestamp_display())
