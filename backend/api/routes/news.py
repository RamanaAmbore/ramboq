"""Stock-market news feed — Google News RSS, cached 10 min, dual-timezone stamps."""

import socket
import urllib.request
import xml.etree.ElementTree as ET
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

logger = get_logger(__name__)

_TTL = 600  # 10 minutes
_FEED = (
    "https://news.google.com/rss/search?"
    "q=stock+market+OR+nifty+OR+sensex+OR+dow+OR+nasdaq+OR+S%26P+500&hl=en-US&gl=US&ceid=US:en"
)


def _fmt_stamp(dt) -> str:
    """Format a UTC datetime as 'IST | EDT/EST' for display, matching log style."""
    try:
        ist = dt.astimezone(timestamp_indian().tzinfo)
        est = dt.astimezone(timestamp_est().tzinfo)
        return (
            f"{ist.strftime('%a, %B %d, %Y, %I:%M %p IST')} | "
            f"{est.strftime('%a, %B %d, %Y, %I:%M %p %Z')}"
        )
    except Exception:
        return ""


def _fetch_news() -> NewsResponse:
    """Fetch the RSS feed (blocking), parse into headlines sorted by newest first."""
    try:
        # Force IPv4 in case the server's IPv6 egress is Kite-only
        socket.setdefaulttimeout(8)
        req = urllib.request.Request(_FEED, headers={"User-Agent": "RamboQuant/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read()
        root = ET.fromstring(data)

        items: list[NewsItem] = []
        for item in list(root.iterfind(".//item"))[:50]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source = (source_el.text if source_el is not None else "") or ""
            try:
                dt = parsedate_to_datetime(pub) if pub else None
                stamp = _fmt_stamp(dt) if dt else ""
            except Exception:
                dt = None
                stamp = ""
            if title and dt:
                items.append(NewsItem(
                    title=title, link=link, source=source.strip(), timestamp=stamp,
                ))
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return NewsResponse(items=items, refreshed_at=timestamp_display())
    except Exception as e:
        logger.error(f"News fetch failed: {e}")
        return NewsResponse(items=[], refreshed_at=timestamp_display())


class NewsController(Controller):
    path = "/api/news"

    @get("/")
    async def get_news(self) -> NewsResponse:
        try:
            return await get_or_fetch("news", _fetch_news, ttl_seconds=_TTL)
        except Exception as e:
            logger.error(f"News API error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
