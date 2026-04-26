"""Positions endpoint — returns per-account rows and summary."""

import pandas as pd
import polars as pl
from litestar import Controller, Request, get
from litestar.exceptions import HTTPException

from backend.api.auth_guard import is_admin_request, is_demo_request
from backend.api.cache import get_or_fetch, invalidate
from backend.api.schemas import PositionsResponse, PositionRow, PositionsSummaryRow
from backend.shared.helpers import broker_apis
from backend.shared.helpers.date_time_utils import timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import mask_column

logger = get_logger(__name__)

_ROW_COLS = [
    'account', 'tradingsymbol', 'exchange', 'product',
    'quantity', 'average_price', 'close_price',
    'pnl', 'unrealised', 'realised',
]

_TTL = 30


def _fetch() -> PositionsResponse:
    raw = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    # Account masking removed — admin-only pages show real account IDs

    numeric = raw.select_dtypes(include='number').columns
    raw[numeric] = raw[numeric].fillna(0)
    df = pl.from_pandas(raw)

    row_cols = [c for c in _ROW_COLS if c in df.columns]
    df_rows = df.select(row_cols)

    grouped = df.group_by('account').agg(pl.col('pnl').sum()) if 'pnl' in df.columns \
              else pl.DataFrame({'account': [], 'pnl': []})
    totals = pl.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
    summary_df = pl.concat([grouped, totals], how='diagonal').fill_nan(0).fill_null(0)

    rows = [
        PositionRow(**{k: (v if v is not None else 0) for k, v in r.items()})
        for r in df_rows.to_dicts()
    ]
    summary = [
        PositionsSummaryRow(**{k: (v if v is not None else 0) for k, v in r.items()})
        for r in summary_df.to_dicts()
    ]
    return PositionsResponse(rows=rows, summary=summary, refreshed_at=timestamp_display())


class PositionsController(Controller):
    path = "/api/positions"

    @get("/")
    async def get_positions(self, request: Request, fresh: bool = False) -> PositionsResponse:
        try:
            # Demo session: serve curated synthetic book — never hits
            # the broker, never leaks real account data. Real positions
            # stay invisible to anonymous prod visitors.
            if is_demo_request(request):
                from backend.api.algo.demo import get_positions_response
                return get_positions_response()
            if fresh:
                invalidate("positions")
            resp = await get_or_fetch("positions", _fetch, ttl_seconds=_TTL)
            if not is_admin_request(request):
                for r in resp.rows:
                    r.account = mask_column(pd.Series([r.account]))[0]
                for s in resp.summary:
                    s.account = mask_column(pd.Series([s.account]))[0]
            return resp
        except Exception as e:
            logger.error(f"Positions API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
