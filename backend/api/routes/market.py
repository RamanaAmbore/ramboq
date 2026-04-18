"""Market update endpoint — AI-generated report; DB cache; no YAML fallback."""

import asyncio

from litestar import Controller, get
from litestar.exceptions import HTTPException

from backend.api.cache import get_or_fetch
from backend.api.schemas import MarketResponse
from backend.shared.helpers import genai_api
from backend.shared.helpers.date_time_utils import timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import get_cycle_date

logger = get_logger(__name__)

# Flow: in-process cache → DB row (<24h old) → Gemini. Never YAML.
_TTL = 86400  # 24 hours


def fetch_fresh() -> MarketResponse:
    """Call Gemini for a fresh market update — blocks for a few seconds."""
    content = genai_api.get_market_update()
    return MarketResponse(
        content=content,
        cycle_date=str(get_cycle_date()),
        refreshed_at=timestamp_display(),
    )


async def _db_or_gemini() -> MarketResponse:
    """Try DB row (<24h old). Else call Gemini inline and persist."""
    from backend.api.background import _load_market_from_db, _save_market_to_db

    cached = await _load_market_from_db()
    if cached:
        return cached

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, fetch_fresh)
    await _save_market_to_db(result)
    return result


class MarketController(Controller):
    path = "/api/market"

    @get("/")
    async def get_market(self) -> MarketResponse:
        try:
            return await get_or_fetch("market", _db_or_gemini, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"Market API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
