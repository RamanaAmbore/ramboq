"""
ARQ background worker — replaces src/helpers/background_refresh.py threading loop.

Handles:
  - Performance data refresh (holdings, positions, funds) every N minutes during market hours
  - Open/close summary notifications per market segment
  - Loss and negative-fund-balance alerts
  - Market update cache warm once per day

Run with:
    arq workers.refresh_worker.WorkerSettings

Requires Redis running locally (or REDIS_URL env var set).

Phase 1 note: This worker is not yet wired to the Litestar WebSocket push or Redis pub/sub.
That is Phase 2. For now it replicates the background_refresh.py behaviour as an ARQ job
to validate the architecture and enable independent scaling.
"""

import os
from datetime import timedelta, time as dtime

from arq import cron
from arq.connections import RedisSettings

from src.helpers.date_time_utils import timestamp_indian, is_market_open, timestamp_display
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import config, get_nearest_time, get_cycle_date

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ---------------------------------------------------------------------------
# Helpers (mirrors background_refresh._parse_time / _build_segments)
# ---------------------------------------------------------------------------

def _parse_time(t: str):
    h, m = map(int, t.split(':'))
    return dtime(h, m)


def _build_segments():
    raw = config.get('market_segments', {})
    segments = []
    for name, s in raw.items():
        segments.append({
            'name':             name,
            'hours_start':      _parse_time(s.get('hours_start', '09:15')),
            'hours_end':        _parse_time(s.get('hours_end', '15:30')),
            'holiday_exchange': s.get('holiday_exchange', 'NSE'),
            'exchanges':        set(s.get('exchanges', [])),
        })
    return segments


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

async def warm_market_cache(ctx):
    """Warm the market update cache. Runs once at worker startup and daily at 08:30 IST."""
    from src.utils_streamlit import get_market_update
    try:
        cycle_date = get_cycle_date()
        get_market_update(cycle_date)
        logger.info(f"Worker: market cache warmed for {cycle_date}")
    except Exception as e:
        logger.error(f"Worker: market cache warm failed: {e}")


async def refresh_performance(ctx):
    """
    Fetch holdings, positions, funds for the current interval key.
    Runs every performance_refresh_interval minutes during market hours.
    Triggers open summary, close summary, and alerts as needed.
    """
    from src.utils_streamlit import fetch_margins, fetch_holdings, fetch_positions
    from src.helpers.broker_apis import fetch_holidays
    from src.helpers.alert_utils import send_summary, check_and_alert
    from src.helpers.background_refresh import _summarise_holdings, _summarise_positions

    now = timestamp_indian()
    today = now.date()
    interval = config.get('performance_refresh_interval', 5)
    open_offset = config.get('open_summary_offset_minutes', 15)
    close_offset = config.get('close_summary_offset_minutes', 15)

    segments = _build_segments()

    # Load holiday caches (cheap — cached in process memory by fetch_holidays)
    holiday_cache = {}
    for seg in segments:
        exch = seg['holiday_exchange']
        if exch not in holiday_cache:
            try:
                holiday_cache[exch] = fetch_holidays(exch)
            except Exception as e:
                logger.warning(f"Worker: holiday load failed for {exch}: {e}")
                holiday_cache[exch] = set()

    open_segments = [
        seg for seg in segments
        if is_market_open(now, holiday_cache.get(seg['holiday_exchange'], set()),
                         seg['hours_start'], seg['hours_end'])
    ]

    if not open_segments:
        return

    try:
        perf_key = get_nearest_time(interval=interval)
        df_margins = fetch_margins(perf_key)
        df_holdings, sum_holdings = fetch_holdings(perf_key, df_margins)
        df_positions, sum_positions = fetch_positions(perf_key)
        ist_display = timestamp_display()

        # Per-segment open summary + alerts
        seg_state = ctx.get('seg_state', {s['name']: {'last_open': None, 'last_close': None}
                                          for s in segments})
        alert_state = ctx.get('alert_state', {})

        for seg in open_segments:
            ss = seg_state[seg['name']]
            seg_exchanges = seg['exchanges']
            seg_holdings = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
                           if 'exchange' in df_holdings.columns else df_holdings
            seg_positions = df_positions[df_positions['exchange'].isin(seg_exchanges)] \
                            if 'exchange' in df_positions.columns else df_positions

            seg_sum_h = _summarise_holdings(seg_holdings, sum_holdings, seg_exchanges)
            seg_sum_p = _summarise_positions(seg_positions)

            # Open summary — once per day, open_offset mins after segment opens
            open_dt = now.replace(
                hour=seg['hours_start'].hour, minute=seg['hours_start'].minute,
                second=0, microsecond=0
            ) + timedelta(minutes=open_offset)

            if ss['last_open'] != today and now >= open_dt:
                send_summary(seg_sum_h, seg_sum_p, ist_display, 'open',
                             label=seg['name'].capitalize(), df_margins=df_margins)
                ss['last_open'] = today

            alert_state = check_and_alert(seg_sum_h, seg_sum_p, alert_state, ist_display,
                                          df_margins=df_margins)

        ctx['seg_state'] = seg_state
        ctx['alert_state'] = alert_state
        logger.info(f"Worker: performance refreshed for {perf_key}")

    except Exception as e:
        logger.error(f"Worker: performance refresh failed: {e}")


async def check_close_summaries(ctx):
    """
    Send close summary for any segment whose close time + offset has passed today.
    Runs every 5 minutes (same cadence as refresh_performance).
    """
    from src.utils_streamlit import fetch_margins, fetch_holdings, fetch_positions
    from src.helpers.broker_apis import fetch_holidays
    from src.helpers.alert_utils import send_summary
    from src.helpers.background_refresh import _summarise_holdings, _summarise_positions

    now = timestamp_indian()
    today = now.date()
    interval = config.get('performance_refresh_interval', 5)
    close_offset = config.get('close_summary_offset_minutes', 15)
    segments = _build_segments()

    holiday_cache = {}
    for seg in segments:
        exch = seg['holiday_exchange']
        if exch not in holiday_cache:
            try:
                holiday_cache[exch] = fetch_holidays(exch)
            except Exception:
                holiday_cache[exch] = set()

    seg_state = ctx.get('seg_state', {s['name']: {'last_open': None, 'last_close': None}
                                      for s in segments})

    for seg in segments:
        ss = seg_state[seg['name']]
        if ss['last_close'] == today:
            continue

        h_set = holiday_cache.get(seg['holiday_exchange'], set())
        close_trigger = now.replace(
            hour=seg['hours_end'].hour, minute=seg['hours_end'].minute,
            second=0, microsecond=0
        ) + timedelta(minutes=close_offset)

        if today not in h_set and now >= close_trigger:
            try:
                close_key = get_nearest_time(interval=interval)
                df_margins = fetch_margins(close_key)
                df_holdings, sum_holdings = fetch_holdings(close_key, df_margins)
                df_positions, _ = fetch_positions(close_key)
                ist_display = timestamp_display()

                seg_exchanges = seg['exchanges']
                seg_holdings = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
                               if 'exchange' in df_holdings.columns else df_holdings
                seg_positions = df_positions[df_positions['exchange'].isin(seg_exchanges)] \
                                if 'exchange' in df_positions.columns else df_positions

                seg_sum_h = _summarise_holdings(seg_holdings, sum_holdings, seg_exchanges)
                seg_sum_p = _summarise_positions(seg_positions)

                send_summary(seg_sum_h, seg_sum_p, ist_display, 'close',
                             label=seg['name'].capitalize(), df_margins=df_margins)
                ss['last_close'] = today
                logger.info(f"Worker: close summary sent for {seg['name']}")
            except Exception as e:
                logger.error(f"Worker: close summary failed for {seg['name']}: {e}")

    ctx['seg_state'] = seg_state


# ---------------------------------------------------------------------------
# Worker settings
# ---------------------------------------------------------------------------

async def startup(ctx):
    logger.info("Worker: starting up — warming market cache")
    ctx['seg_state'] = {}
    ctx['alert_state'] = {}
    await warm_market_cache(ctx)


async def shutdown(ctx):
    logger.info("Worker: shutting down")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    functions = [refresh_performance, check_close_summaries, warm_market_cache]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [
        cron(refresh_performance,   minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(check_close_summaries, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(warm_market_cache,     hour=8, minute=30),
    ]
    max_jobs = 4
    job_timeout = 120
