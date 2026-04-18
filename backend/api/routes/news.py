"""
Stock-market news feed.

Fetches Google News RSS for a financial-markets query, accumulates headlines
throughout the day, and resets every morning at 07:00 IST (aligned with the
daily market-report refresh). Gated by the `news` flag in backend_config.yaml
(combined with `cap_in_dev`) so dev can silence it independently of prod.
"""

import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from litestar import Controller, get
from litestar.exceptions import HTTPException

from backend.api.cache import get_or_fetch
from backend.api.schemas import NewsItem, NewsResponse
from backend.shared.helpers.date_time_utils import (
    timestamp_display,
    timestamp_indian,
    timestamp_est,
)
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config, is_prod_capable

logger = get_logger(__name__)

_CACHE_TTL = 600  # 10 minutes — duration the route caches the accumulated list
_FEED = (
    "https://news.google.com/rss/search?"
    "q=stock+market+OR+nifty+OR+sensex+OR+dow+OR+nasdaq+OR+S%26P+500&hl=en-US&gl=US&ceid=US:en"
)

# Accumulator — headlines seen since the last 07:00 IST reset. Keyed by link for
# deduplication; the stored tuple carries the parsed UTC datetime for sorting.
_accum_by_link: dict[str, tuple[datetime, NewsItem]] = {}
_accum_lock = threading.Lock()
_last_reset: date | None = None


def _news_enabled() -> bool:
    return bool(is_prod_capable() and config.get('news'))


def _fmt_stamp(dt: datetime) -> str:
    try:
        ist = dt.astimezone(timestamp_indian().tzinfo)
        est = dt.astimezone(timestamp_est().tzinfo)
        return (
            f"{ist.strftime('%a, %B %d, %Y, %I:%M %p IST')} | "
            f"{est.strftime('%a, %B %d, %Y, %I:%M %p %Z')}"
        )
    except Exception:
        return ""


def _maybe_reset() -> None:
    """Clear the accumulator once per day after 07:00 IST (morning rollover)."""
    global _last_reset
    now = timestamp_indian()
    today = now.date()
    seven_am = now.replace(hour=7, minute=0, second=0, microsecond=0)
    with _accum_lock:
        if now >= seven_am and _last_reset != today:
            _accum_by_link.clear()
            _last_reset = today
            logger.info("News: accumulator reset for new trading day")


def _fetch_rss() -> list[tuple[datetime, NewsItem]]:
    """Fetch Google News RSS and return a list of (utc_dt, NewsItem) tuples."""
    req = urllib.request.Request(_FEED, headers={"User-Agent": "RamboQuant/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = r.read()
    root = ET.fromstring(data)
    out: list[tuple[datetime, NewsItem]] = []
    for item in list(root.iterfind(".//item"))[:50]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = (src_el.text if src_el is not None else "") or ""
        if not title or not link or not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        out.append((dt, NewsItem(
            title=title, link=link, source=source.strip(), timestamp=_fmt_stamp(dt),
        )))
    return out


def _fetch_and_accumulate() -> NewsResponse:
    """Merge fresh RSS items into the accumulator and return sorted result."""
    if not _news_enabled():
        return NewsResponse(items=[], refreshed_at=timestamp_display())

    _maybe_reset()
    try:
        fresh = _fetch_rss()
    except Exception as e:
        logger.error(f"News fetch failed: {e}")
        fresh = []

    with _accum_lock:
        for dt, item in fresh:
            _accum_by_link.setdefault(item.link, (dt, item))
        sorted_pairs = sorted(_accum_by_link.values(), key=lambda p: p[0], reverse=True)
        items = [pair[1] for pair in sorted_pairs]

    return NewsResponse(items=items, refreshed_at=timestamp_display())


class NewsController(Controller):
    path = "/api/news"

    @get("/")
    async def get_news(self) -> NewsResponse:
        try:
            return await get_or_fetch("news", _fetch_and_accumulate, ttl_seconds=_CACHE_TTL)
        except Exception as e:
            logger.error(f"News API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
