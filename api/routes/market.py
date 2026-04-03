"""Market update endpoint — returns AI-generated market report with TTL cache."""

from litestar import Controller, get
from litestar.exceptions import HTTPException

from api.cache import get_or_fetch
from api.schemas import MarketResponse
from src.helpers import genai_api
from src.helpers.date_time_utils import timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import get_cycle_date

logger = get_logger(__name__)

# Market report changes once per day (cycle_date advances at 08:00 IST).
# Cache for 3600 s so a fresh Gemini call is made at most once per hour,
# and the worker's daily warm at 08:30 forces a fresh fetch via warm_market_cache.
_TTL = 3600


def _fetch() -> MarketResponse:
    content = genai_api.get_market_update()
    return MarketResponse(
        content=content,
        cycle_date=str(get_cycle_date()),
        refreshed_at=timestamp_display(),
    )


class MarketController(Controller):
    path = "/api/market"

    @get("/")
    async def get_market(self) -> MarketResponse:
        try:
            return await get_or_fetch("market", _fetch, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"Market API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
