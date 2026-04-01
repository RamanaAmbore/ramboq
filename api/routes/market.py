"""Market update endpoint — returns AI-generated market report."""

from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.schemas import MarketResponse
from src.helpers import genai_api
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import get_cycle_date

logger = get_logger(__name__)


class MarketController(Controller):
    path = "/api/market"

    @get("/")
    async def get_market(self) -> MarketResponse:
        try:
            cycle_date = get_cycle_date()
            content = genai_api.get_market_update()
            return MarketResponse(
                content=content,
                cycle_date=cycle_date,
                refreshed_at=timestamp_display(),
            )
        except Exception as e:
            logger.error(f"Market API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
