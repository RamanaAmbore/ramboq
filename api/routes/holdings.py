"""Holdings endpoint — returns per-account rows and summary."""

import pandas as pd
import polars as pl
from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.cache import get_or_fetch
from api.schemas import HoldingsResponse, HoldingRow, HoldingsSummaryRow
from src.helpers import broker_apis
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column

logger = get_logger(__name__)

_ROW_COLS = [
    'account', 'tradingsymbol', 'exchange', 'quantity',
    'average_price', 'close_price', 'inv_val', 'cur_val',
    'pnl', 'pnl_percentage', 'day_change', 'day_change_val', 'day_change_percentage',
]

_TTL = 30  # seconds — background task invalidates on each refresh


def _fetch() -> HoldingsResponse:
    raw = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    raw['account'] = mask_column(raw['account'])

    df = pl.from_pandas(raw.fillna(0))

    row_cols = [c for c in _ROW_COLS if c in df.columns]
    df_rows = df.select(row_cols)

    sum_cols = [c for c in ['inv_val', 'cur_val', 'pnl', 'day_change_val'] if c in df.columns]
    grouped = (
        df.group_by('account')
          .agg([pl.col(c).sum() for c in sum_cols])
    )
    grouped = grouped.with_columns([
        (pl.col('pnl')            / pl.col('inv_val')  * 100).alias('pnl_percentage'),
        (pl.col('day_change_val') / pl.col('cur_val')  * 100).alias('day_change_percentage'),
    ])

    totals = grouped.select(sum_cols).sum().with_columns([
        pl.lit('TOTAL').alias('account'),
        (pl.col('pnl')            / pl.col('inv_val')  * 100).alias('pnl_percentage'),
        (pl.col('day_change_val') / pl.col('cur_val')  * 100).alias('day_change_percentage'),
    ])
    summary_df = pl.concat([grouped, totals], how='diagonal').fill_nan(0).fill_null(0)

    rows = [
        HoldingRow(**{k: (v if v is not None else 0) for k, v in r.items()})
        for r in df_rows.to_dicts()
    ]
    summary = [
        HoldingsSummaryRow(**{k: (v if v is not None else 0) for k, v in r.items()})
        for r in summary_df.to_dicts()
    ]
    return HoldingsResponse(rows=rows, summary=summary, refreshed_at=timestamp_display())


class HoldingsController(Controller):
    path = "/api/holdings"

    @get("/")
    async def get_holdings(self) -> HoldingsResponse:
        try:
            return await get_or_fetch("holdings", _fetch, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"Holdings API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
