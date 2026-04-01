"""Holdings endpoint — returns per-account rows and summary."""

import pandas as pd
from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.schemas import HoldingsResponse, HoldingRow, HoldingsSummaryRow
from src.helpers import broker_apis
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column
from src.constants import holdings_config

logger = get_logger(__name__)

_HOLDING_COLS = [c for c in holdings_config.keys() if c not in ('cash', 'net')]


class HoldingsController(Controller):
    path = "/api/holdings"

    @get("/")
    async def get_holdings(self) -> HoldingsResponse:
        try:
            df = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
            df = df[[c for c in _HOLDING_COLS if c in df.columns]]
            df['account'] = mask_column(df['account'])

            # Summary: per-account + TOTAL
            sum_cols = ["inv_val", "cur_val", "pnl", "day_change_val"]
            grouped = df.groupby("account")[sum_cols].sum().reset_index()
            grouped['pnl_percentage'] = grouped['pnl'] / grouped['inv_val'] * 100
            grouped['day_change_percentage'] = grouped['day_change_val'] / grouped['cur_val'] * 100

            totals = grouped[sum_cols].sum().to_frame().T
            totals['account'] = 'TOTAL'
            totals['pnl_percentage'] = totals['pnl'] / totals['inv_val'] * 100
            totals['day_change_percentage'] = totals['day_change_val'] / totals['cur_val'] * 100
            summary_df = pd.concat([grouped, totals], ignore_index=True).fillna(0)

            rows = [HoldingRow(**r) for r in df.fillna(0).to_dict(orient='records')]
            summary = [HoldingsSummaryRow(**r) for r in summary_df.to_dict(orient='records')]

            return HoldingsResponse(
                rows=rows,
                summary=summary,
                refreshed_at=timestamp_display(),
            )
        except Exception as e:
            logger.error(f"Holdings API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
