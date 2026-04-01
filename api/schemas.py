"""
Pydantic v2 response schemas for all API endpoints.
These define the contract between the Litestar backend and any frontend (Streamlit or SvelteKit).
"""

from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

class HoldingRow(BaseModel):
    account: str
    tradingsymbol: str
    exchange: str
    quantity: int
    average_price: float
    close_price: float
    inv_val: float
    cur_val: float
    pnl: float
    pnl_percentage: float
    day_change: float
    day_change_val: float
    day_change_percentage: float


class HoldingsSummaryRow(BaseModel):
    account: str
    inv_val: float
    cur_val: float
    pnl: float
    pnl_percentage: float
    day_change_val: float
    day_change_percentage: float
    cash: Optional[float] = None
    net: Optional[float] = None


class HoldingsResponse(BaseModel):
    rows: list[HoldingRow]
    summary: list[HoldingsSummaryRow]
    refreshed_at: str


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class PositionRow(BaseModel):
    account: str
    tradingsymbol: str
    exchange: str
    product: str
    quantity: int
    average_price: float
    close_price: float
    pnl: float
    unrealised: float
    realised: float


class PositionsSummaryRow(BaseModel):
    account: str
    pnl: float


class PositionsResponse(BaseModel):
    rows: list[PositionRow]
    summary: list[PositionsSummaryRow]
    refreshed_at: str


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------

class FundsRow(BaseModel):
    account: str
    cash: float           # avail opening_balance
    avail_margin: float   # net
    used_margin: float    # util debits
    collateral: float     # avail collateral


class FundsResponse(BaseModel):
    rows: list[FundsRow]
    refreshed_at: str


# ---------------------------------------------------------------------------
# Market update
# ---------------------------------------------------------------------------

class MarketResponse(BaseModel):
    content: str
    cycle_date: str
    refreshed_at: str
