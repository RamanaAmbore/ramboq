"""Positions endpoint — returns per-account rows and summary."""

import pandas as pd
from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.schemas import PositionsResponse, PositionRow, PositionsSummaryRow
from src.helpers import broker_apis
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import mask_column
from src.constants import positions_config

logger = get_logger(__name__)

_POSITION_COLS = list(positions_config.keys())


class PositionsController(Controller):
    path = "/api/positions"

    @get("/")
    async def get_positions(self) -> PositionsResponse:
        try:
            df = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
            df = df[[c for c in _POSITION_COLS if c in df.columns]]
            df['account'] = mask_column(df['account'])

            grouped = df.groupby("account")[["pnl"]].sum().reset_index()
            totals = pd.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
            summary_df = pd.concat([grouped, totals], ignore_index=True)

            rows = [PositionRow(**r) for r in df.fillna(0).to_dict(orient='records')]
            summary = [PositionsSummaryRow(**r) for r in summary_df.to_dict(orient='records')]

            return PositionsResponse(
                rows=rows,
                summary=summary,
                refreshed_at=timestamp_display(),
            )
        except Exception as e:
            logger.error(f"Positions API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
