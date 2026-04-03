"""Funds endpoint — returns margins / cash / available margin per account."""

import pandas as pd
import polars as pl
from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.cache import get_or_fetch
from api.schemas import FundsResponse, FundsRow
from src.helpers import broker_apis
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column

logger = get_logger(__name__)

_TTL = 30

_COL_MAP = {
    'avail opening_balance': 'cash',
    'net':                   'avail_margin',
    'util debits':           'used_margin',
    'avail collateral':      'collateral',
}


def _fetch() -> FundsResponse:
    raw = pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    raw['account'] = mask_column(raw['account'])

    df = pl.from_pandas(raw.fillna(0))

    # Rename broker column names to schema names
    rename = {k: v for k, v in _COL_MAP.items() if k in df.columns}
    df = df.rename(rename)

    numeric = ['cash', 'avail_margin', 'used_margin', 'collateral']
    present = [c for c in numeric if c in df.columns]

    totals = df.select(present).sum().with_columns(pl.lit('TOTAL').alias('account'))
    df_all = pl.concat([df.select(['account', *present]), totals], how='diagonal') \
               .fill_nan(0).fill_null(0)

    rows = [FundsRow(**r) for r in df_all.to_dicts()]
    return FundsResponse(rows=rows, refreshed_at=timestamp_display())


class FundsController(Controller):
    path = "/api/funds"

    @get("/")
    async def get_funds(self) -> FundsResponse:
        try:
            return await get_or_fetch("funds", _fetch, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"Funds API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
