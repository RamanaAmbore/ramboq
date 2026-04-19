"""
Stock-market news feed — headlines persisted in Postgres.

Pulls from curated Indian and global financial RSS feeds (already pre-filtered
by their editors), applies a small keyword exclusion for noise, dedupes by
link, and stores in Postgres. Wipes the table every morning at 07:00 IST,
aligned with the daily market-report refresh. Gated by is_enabled('market_feed').
"""

import asyncio
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from litestar import Controller, get
from litestar.exceptions import HTTPException
from sqlalchemy import select, delete

from backend.api.cache import get_or_fetch
from backend.api.database import async_session
from backend.api.models import NewsHeadline
from backend.api.schemas import NewsItem, NewsResponse
from backend.shared.helpers.date_time_utils import (
    timestamp_display,
    timestamp_indian,
    timestamp_est,
)
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import is_enabled

logger = get_logger(__name__)

_CACHE_TTL = 600  # 10-minute route-level coalescing; the DB holds the accumulator

# Curated financial RSS feeds — Indian-first, with two global feeds to catch
# moves that drive Indian sentiment. All sources are already market-focused,
# so no AI rerank is needed.
_FEEDS = [
    # Indian markets
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.livemint.com/rss/markets",
    # Global markets
    "https://news.google.com/rss/search?q=site%3Abloomberg.com+markets&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=site%3Areuters.com+markets+OR+stocks&hl=en-US&gl=US&ceid=US:en",
]

# Drop obvious non-market content that sometimes sneaks into general sections.
_NOISE_RE = re.compile(
    r'\b(horoscope|astrology|bollywood|hollywood|cricket|ipl|kohli|dhoni|sports|'
    r'weather|recipe|cooking|travel|tourism|lifestyle|fashion|beauty|health\s+tip|'
    r'viral\s+video|whatsapp\s+status|rashifal|vastu)\b',
    re.IGNORECASE,
)

# Drop low-information headlines — pure stubs, "X in 10 seconds" fillers, etc.
_STUB_RE = re.compile(
    r'^\s*('
    r'market\s+(update|wrap|recap|roundup|close|open)s?'
    r'|stock\s+updates?'
    r'|daily\s+(wrap|recap|roundup)'
    r'|morning\s+(brief|briefing)'
    r'|closing\s+bell'
    r'|news\s+(wrap|recap)'
    r'|top\s+\d+\s+(news|stocks?|gainers?|losers?)'
    r')\s*[:\-—|]*\s*$',
    re.IGNORECASE,
)

_MIN_TITLE_CHARS = 40  # headlines shorter than this are usually just labels
_MIN_TITLE_WORDS = 5


def _is_low_info(title: str) -> bool:
    """Drop headlines that carry no substantive information."""
    t = (title or "").strip()
    if not t:
        return True
    # Strip trailing " - Source" suffix Google News appends, for length checks
    stripped = re.sub(r'\s+[-—|]\s+[^-—|]{1,40}$', '', t)
    if len(stripped) < _MIN_TITLE_CHARS:
        return True
    if len(stripped.split()) < _MIN_TITLE_WORDS:
        return True
    if _STUB_RE.match(stripped):
        return True
    return False

_reset_lock = threading.Lock()
_last_reset: date | None = None


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


async def _maybe_reset() -> None:
    """Truncate news_headlines once per day after 07:00 IST (morning rollover)."""
    global _last_reset
    now = timestamp_indian()
    today = now.date()
    seven_am = now.replace(hour=7, minute=0, second=0, microsecond=0)
    with _reset_lock:
        due = (now >= seven_am and _last_reset != today)
        if due:
            _last_reset = today
    if due:
        try:
            async with async_session() as s:
                await s.execute(delete(NewsHeadline))
                await s.commit()
            logger.info("News: headlines table cleared for new trading day")
        except Exception as e:
            logger.error(f"News: reset failed: {e}")


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


_FEED_TIMEOUT = 4  # seconds per feed — slow publishers get dropped from this cycle


def _fetch_one_feed(url: str) -> list[tuple[datetime, dict]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5",
    })
    with urllib.request.urlopen(req, timeout=_FEED_TIMEOUT) as r:
        data = r.read()
    root = ET.fromstring(data)
    out: list[tuple[datetime, dict]] = []
    for item in list(root.iterfind(".//item"))[:40]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        # Fall back to the domain as source when the feed doesn't include one
        source = ((src_el.text if src_el is not None else "") or "").strip()
        if not source:
            try:
                from urllib.parse import urlparse
                source = urlparse(link).netloc.removeprefix("www.")
            except Exception:
                source = ""
        if not title or not link or not pub:
            continue
        if _NOISE_RE.search(title):
            continue
        if _is_low_info(title):
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        out.append((dt, {
            "link": link, "title": title, "source": source,
            "published_at": dt, "timestamp_display": _fmt_stamp(dt),
        }))
    return out


def _fetch_rss() -> list[tuple[datetime, dict]]:
    """Fetch every configured feed in parallel, merge, dedupe by link."""
    merged: dict[str, tuple[datetime, dict]] = {}
    with ThreadPoolExecutor(max_workers=len(_FEEDS)) as ex:
        future_by_url = {ex.submit(_fetch_one_feed, u): u for u in _FEEDS}
        for fut in as_completed(future_by_url, timeout=_FEED_TIMEOUT + 2):
            url = future_by_url[fut]
            try:
                for dt, row in fut.result(timeout=0.1):
                    merged.setdefault(row["link"], (dt, row))
            except Exception as e:
                logger.warning(f"News feed {url[:60]}… failed: {e}")
    return list(merged.values())


async def _fetch_and_accumulate() -> NewsResponse:
    """Fetch RSS feeds, insert new links into DB, return the full accumulated list."""
    if not is_enabled('market_feed'):
        return NewsResponse(items=[], refreshed_at=timestamp_display())

    await _maybe_reset()

    loop = asyncio.get_running_loop()
    try:
        fresh = await loop.run_in_executor(None, _fetch_rss)
    except Exception as e:
        logger.error(f"News fetch failed: {e}")
        fresh = []

    try:
        async with async_session() as s:
            if fresh:
                existing = await s.execute(
                    select(NewsHeadline.link).where(
                        NewsHeadline.link.in_([row["link"] for _, row in fresh])
                    )
                )
                have = {r[0] for r in existing}
                added = 0
                for _dt, row in fresh:
                    if row["link"] in have:
                        continue
                    s.add(NewsHeadline(**row))
                    added += 1
                if added:
                    await s.commit()
                    logger.info(f"News: +{added} new headlines")

            rows = await s.execute(
                select(NewsHeadline).order_by(NewsHeadline.published_at.desc())
            )
            items = [
                NewsItem(
                    title=h.title, link=h.link,
                    source=h.source or "", timestamp=h.timestamp_display or "",
                )
                for h in rows.scalars().all()
            ]
    except Exception as e:
        logger.error(f"News DB query failed: {e}")
        items = []

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
