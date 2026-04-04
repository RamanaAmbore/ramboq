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

# Market report: fetched ONCE per day by background task at 07:00 IST.
# API serves cached data only — never calls Gemini on user request.
# TTL = 24h. If cache is empty (first startup), returns fallback static content.
_TTL = 86400  # 24 hours


def _fetch_cached() -> MarketResponse:
    """Return cached market data or static fallback — does NOT call Gemini."""
    from src.helpers.utils import ramboq_config
    content = ramboq_config.get("market", "Market update will be available at 07:00 AM IST.")
    return MarketResponse(
        content=content,
        cycle_date=str(get_cycle_date()),
        refreshed_at=timestamp_display(),
    )


def fetch_fresh() -> MarketResponse:
    """Call Gemini for fresh market update — only called by background task."""
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
            return await get_or_fetch("market", _fetch_cached, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"Market API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
