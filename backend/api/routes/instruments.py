"""
Instruments endpoint — Kite master instrument dump for client-side autocomplete.

GET /api/instruments    — full instrument list, cached daily (refreshed at 08:00 IST)

Returns a trimmed list suitable for symbol autocomplete:
  [
    {"s": "RELIANCE", "e": "NSE", "t": "EQ", "ls": 1, "ts": 0.05},
    {"s": "NIFTY25APR0322500CE", "e": "NFO", "t": "CE", "u": "NIFTY",
     "x": "2026-04-03", "k": 22500, "ls": 50, "ts": 0.05},
    ...
  ]

Field abbreviations keep payload small:
  s  = tradingsymbol
  e  = exchange
  t  = instrument_type (EQ / FUT / CE / PE)
  u  = underlying name (options/futures only)
  x  = expiry (YYYY-MM-DD, options/futures only)
  k  = strike (options only)
  ls = lot_size
  ts = tick_size
"""

from datetime import date
from typing import Optional

import msgspec
from litestar import Controller, get
from litestar.exceptions import HTTPException

from backend.api.auth_guard import jwt_guard
from backend.api.cache import get_or_fetch
from backend.shared.helpers.connections import Connections
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

_TTL_SECONDS = 86400  # 24 h — background task re-warms daily at 08:00 IST
_EXCHANGES   = ("NSE", "NFO", "BSE", "MCX", "CDS")


class Instrument(msgspec.Struct, omit_defaults=True):
    s: str                        # tradingsymbol
    e: str                        # exchange
    t: str                        # instrument_type (EQ / FUT / CE / PE)
    ls: int                       # lot_size
    ts: float                     # tick_size
    u: Optional[str]  = None      # underlying name
    x: Optional[str]  = None      # expiry YYYY-MM-DD
    k: Optional[float] = None     # strike


class InstrumentsResponse(msgspec.Struct):
    cycle_date: str
    count: int
    items: list[Instrument]


def _fetch_instruments() -> InstrumentsResponse:
    """Fetch full instrument dump from Kite across all relevant exchanges."""
    conns = Connections()
    account = next(iter(conns.conn))
    kite = conns.conn[account].kite

    items: list[Instrument] = []
    for exch in _EXCHANGES:
        try:
            raw = kite.instruments(exch)
        except Exception as e:
            logger.warning(f"Instruments: {exch} fetch failed: {e}")
            continue

        for inst in raw:
            itype = inst.get("instrument_type", "")
            expiry = inst.get("expiry")
            strike = inst.get("strike")
            items.append(Instrument(
                s=inst["tradingsymbol"],
                e=inst["exchange"],
                t=itype,
                ls=int(inst.get("lot_size") or 1),
                ts=float(inst.get("tick_size") or 0.05),
                u=inst.get("name") or None,
                x=expiry.isoformat() if isinstance(expiry, date) else (expiry or None),
                k=float(strike) if strike not in (None, 0, 0.0) else None,
            ))

    logger.info(f"Instruments: loaded {len(items)} rows across {len(_EXCHANGES)} exchanges")
    return InstrumentsResponse(
        cycle_date=date.today().isoformat(),
        count=len(items),
        items=items,
    )


class InstrumentsController(Controller):
    path = "/api/instruments"
    guards = [jwt_guard]

    @get("/")
    async def get_instruments(self) -> InstrumentsResponse:
        try:
            return await get_or_fetch("instruments", _fetch_instruments, ttl_seconds=_TTL_SECONDS)
        except Exception as e:
            logger.error(f"Instruments API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
