"""
Stock-market news feed — headlines persisted in Postgres.

Accumulates headlines throughout the day and wipes the table every morning at
07:00 IST (aligned with the daily market-report refresh). Gated by
is_enabled('market_feed'): always on in prod, on/off per cap_in_dev in dev.
"""

import threading
import urllib.request
import xml.etree.ElementTree as ET
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
_FEED = (
    "https://news.google.com/rss/search?"
    "q=stock+market+OR+nifty+OR+sensex+OR+dow+OR+nasdaq+OR+S%26P+500&hl=en-US&gl=US&ceid=US:en"
)

_reset_lock = threading.Lock()
_last_reset: date | None = None


def _news_enabled() -> bool:
    return is_enabled('market_feed')


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


def _fetch_rss() -> list[tuple[datetime, dict]]:
    """Fetch Google News RSS, return newest 50 items as (utc_dt, dict)."""
    req = urllib.request.Request(_FEED, headers={"User-Agent": "RamboQuant/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = r.read()
    root = ET.fromstring(data)
    out: list[tuple[datetime, dict]] = []
    for item in list(root.iterfind(".//item"))[:50]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        src_el = item.find("source")
        source = ((src_el.text if src_el is not None else "") or "").strip()
        if not title or not link or not pub:
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


async def _fetch_and_accumulate() -> NewsResponse:
    """Fetch RSS, insert new links into DB, return the full accumulated list."""
    if not _news_enabled():
        return NewsResponse(items=[], refreshed_at=timestamp_display())

    await _maybe_reset()

    try:
        fresh = _fetch_rss()
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
                    logger.info(f"News: +{added} new headlines (total fetched {len(fresh)})")

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
