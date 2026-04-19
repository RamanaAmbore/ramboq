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

# India-locale feed first (Indian market news is the primary interest), then a
# global feed to catch major moves that affect Indian sentiment.
_FEEDS = [
    "https://news.google.com/rss/search?"
    "q=nifty+OR+sensex+OR+%22Indian+stock+market%22+OR+RBI+OR+SEBI+OR+%22Nifty+Bank%22+OR+%22NSE+India%22"
    "&hl=en&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?"
    "q=%22stock+market%22+OR+%22S%26P+500%22+OR+nasdaq+OR+%22dow+jones%22+OR+%22federal+reserve%22"
    "&hl=en-US&gl=US&ceid=US:en",
]

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


def _fetch_one_feed(url: str) -> list[tuple[datetime, dict]]:
    req = urllib.request.Request(url, headers={"User-Agent": "RamboQuant/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = r.read()
    root = ET.fromstring(data)
    out: list[tuple[datetime, dict]] = []
    for item in list(root.iterfind(".//item"))[:40]:
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


def _fetch_rss() -> list[tuple[datetime, dict]]:
    """Fetch all configured feeds, merge, dedupe by link."""
    merged: dict[str, tuple[datetime, dict]] = {}
    for url in _FEEDS:
        try:
            for dt, row in _fetch_one_feed(url):
                merged.setdefault(row["link"], (dt, row))
        except Exception as e:
            logger.warning(f"News feed {url[:60]}… failed: {e}")
    return list(merged.values())


def _ai_rank(items: list[tuple[datetime, dict]]) -> list[tuple[datetime, dict]]:
    """
    Ask Gemini which headlines matter for an Indian markets trader. Returns the
    filtered subset. Falls back to the input list on any failure so we never
    lose headlines to a bad AI call.
    """
    if not items or not is_enabled('genai'):
        return items
    try:
        from backend.shared.helpers.utils import secrets, ramboq_config
        from google import genai
        from google.genai import types

        titles = [row["title"] for _, row in items]
        numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(titles))
        prompt = (
            "You are filtering market news headlines for an active Indian "
            "retail trader holding Nifty/Sensex equities and NFO options. "
            "Return the indices (0-based) of headlines that are genuinely "
            "market-moving or informative for this trader. Prioritize: Indian "
            "market movers (Nifty, Sensex, Bank Nifty, sector indices, "
            "corporate earnings, RBI/SEBI actions, FII flows, INR) and major "
            "global market moves that drive Indian sentiment (US Fed, S&P 500, "
            "NASDAQ, oil, gold). Exclude: fluff pieces, advertorials, unrelated "
            "business news, celebrity/sports.\n\n"
            "Reply with ONLY a JSON array of indices, e.g. [0, 3, 7]. No prose.\n\n"
            f"HEADLINES:\n{numbered}"
        )

        client = genai.Client(api_key=secrets["gemini_api_key"])
        resp = client.models.generate_content(
            model=ramboq_config.get('genai_model', 'gemini-2.5-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
                thinking_config=types.ThinkingConfig(thinking_budget=256),
            ),
        )
        text = (resp.text or "").strip()
        # Extract the first [...] block
        import re as _re, json as _json
        m = _re.search(r'\[[\s\d,\s]*\]', text)
        if not m:
            return items
        keep = set(_json.loads(m.group(0)))
        out = [items[i] for i in keep if 0 <= i < len(items)]
        logger.info(f"News: AI kept {len(out)}/{len(items)} headlines")
        return out or items
    except Exception as e:
        logger.warning(f"News: AI rank failed, keeping all ({e})")
        return items


async def _fetch_and_accumulate() -> NewsResponse:
    """Fetch RSS, insert new links into DB, return the full accumulated list."""
    if not _news_enabled():
        return NewsResponse(items=[], refreshed_at=timestamp_display())

    await _maybe_reset()

    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()
    try:
        fresh_all = await loop.run_in_executor(None, _fetch_rss)
    except Exception as e:
        logger.error(f"News fetch failed: {e}")
        fresh_all = []

    try:
        async with async_session() as s:
            # Prune to only links we haven't seen yet before the (expensive) AI rank
            fresh = fresh_all
            if fresh:
                existing = await s.execute(
                    select(NewsHeadline.link).where(
                        NewsHeadline.link.in_([row["link"] for _, row in fresh])
                    )
                )
                have = {r[0] for r in existing}
                fresh = [p for p in fresh if p[1]["link"] not in have]

            # AI relevance filter on the new items only
            if fresh:
                fresh = await loop.run_in_executor(None, _ai_rank, fresh)

            added = 0
            for _dt, row in fresh:
                s.add(NewsHeadline(**row))
                added += 1
            if added:
                await s.commit()
                logger.info(f"News: +{added} new relevant headlines")

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
