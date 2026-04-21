"""Funds endpoint — returns margins / cash / available margin per account."""

import pandas as pd
import polars as pl
from litestar import Controller, Request, get
from litestar.exceptions import HTTPException

from backend.api.auth_guard import is_admin_request
from backend.api.cache import get_or_fetch, invalidate
from backend.api.schemas import FundsResponse, FundsRow
from backend.shared.helpers import broker_apis
from backend.shared.helpers.date_time_utils import timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import mask_column

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
    # Account masking removed — admin-only pages show real account IDs

    numeric = raw.select_dtypes(include='number').columns
    raw[numeric] = raw[numeric].fillna(0)
    df = pl.from_pandas(raw)

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
    async def get_funds(self, request: Request, fresh: bool = False) -> FundsResponse:
        try:
            if fresh:
                invalidate("funds")
            resp = await get_or_fetch("funds", _fetch, ttl_seconds=_TTL)
            if not is_admin_request(request):
                for r in resp.rows:
                    if r.account != 'TOTAL':
                        r.account = mask_column(pd.Series([r.account]))[0]
            return resp
        except Exception as e:
            logger.error(f"Funds API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
