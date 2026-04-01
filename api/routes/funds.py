"""Funds endpoint — returns margins / cash / available margin per account."""

import pandas as pd
from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.schemas import FundsResponse, FundsRow
from src.helpers import broker_apis
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column

logger = get_logger(__name__)


class FundsController(Controller):
    path = "/api/funds"

    @get("/")
    async def get_funds(self) -> FundsResponse:
        try:
            df = pd.concat(broker_apis.fetch_margins(), ignore_index=True)
            df['account'] = mask_column(df['account'])

            rows = []
            for _, row in df.iterrows():
                rows.append(FundsRow(
                    account=str(row.get('account', '')),
                    cash=float(row.get('avail opening_balance', 0) or 0),
                    avail_margin=float(row.get('net', 0) or 0),
                    used_margin=float(row.get('util debits', 0) or 0),
                    collateral=float(row.get('avail collateral', 0) or 0),
                ))

            # Append TOTAL row
            rows.append(FundsRow(
                account='TOTAL',
                cash=sum(r.cash for r in rows),
                avail_margin=sum(r.avail_margin for r in rows),
                used_margin=sum(r.used_margin for r in rows),
                collateral=sum(r.collateral for r in rows),
            ))

            return FundsResponse(rows=rows, refreshed_at=timestamp_display())
        except Exception as e:
            logger.error(f"Funds API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
