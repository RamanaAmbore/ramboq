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
"""

import json
import os
from datetime import timedelta, time as dtime

import pandas as pd
import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings

PERF_CHANNEL = "performance:update"

from backend.shared.helpers import broker_apis
from backend.shared.helpers.date_time_utils import timestamp_indian, is_market_open, timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config, get_nearest_time, get_cycle_date, mask_column

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


# ---------------------------------------------------------------------------
# Direct broker fetch helpers (worker is a separate process)
# ---------------------------------------------------------------------------

def _fetch_margins_direct():
    df = pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    df['account'] = mask_column(df['account'])
    total_row = df.select_dtypes(include='number').sum()
    total_row['account'] = 'TOTAL'
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)


def _fetch_holdings_direct(df_margins=None):
    df = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    df['account'] = mask_column(df['account'])

    sum_cols = ["inv_val", "cur_val", "pnl", "day_change_val"]
    grouped = df.groupby("account")[[c for c in sum_cols if c in df.columns]].sum().reset_index()

    if df_margins is not None and not df_margins.empty:
        cash_df = df_margins[df_margins['account'] != 'TOTAL'][['account', 'avail opening_balance']].copy()
        grouped = pd.merge(grouped, cash_df, on='account', how='left')
        grouped.rename(columns={'avail opening_balance': 'cash'}, inplace=True)
        grouped['net'] = grouped['cur_val'] + grouped['cash']

    agg_cols = [c for c in [*sum_cols, 'net', 'cash'] if c in grouped.columns]
    totals = grouped[agg_cols].sum().to_frame().T
    totals['account'] = 'TOTAL'

    total_df = pd.concat([grouped, totals], ignore_index=True)
    if 'pnl' in total_df.columns and 'inv_val' in total_df.columns:
        total_df['pnl_percentage'] = total_df['pnl'] / total_df['inv_val'] * 100
    if 'day_change_val' in total_df.columns and 'cur_val' in total_df.columns:
        total_df['day_change_percentage'] = total_df['day_change_val'] / total_df['cur_val'] * 100

    return df, total_df


def _fetch_positions_direct():
    df = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    df['account'] = mask_column(df['account'])

    grouped = df.groupby("account")[["pnl"]].sum().reset_index() if 'pnl' in df.columns else df
    total = pd.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
    return df, pd.concat([grouped, total], ignore_index=True)


# ---------------------------------------------------------------------------
# Segment helpers
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
    from backend.shared.helpers.genai_api import get_market_update
    try:
        content = get_market_update()
        logger.info(f"Worker: market cache warmed for cycle {get_cycle_date()}")
    except Exception as e:
        logger.error(f"Worker: market cache warm failed: {e}")


async def refresh_performance(ctx):
    """
    Fetch holdings, positions, funds for the current interval key.
    Runs every performance_refresh_interval minutes during market hours.
    Triggers open summary, close summary, and alerts as needed.
    """
    from backend.shared.helpers.broker_apis import fetch_holidays
    from backend.shared.helpers.alert_utils import send_summary, check_and_alert
    from backend.shared.helpers.summarise import summarise_holdings as _summarise_holdings, summarise_positions as _summarise_positions

    now = timestamp_indian()
    today = now.date()
    interval = config.get('performance_refresh_interval', 5)
    open_offset = config.get('open_summary_offset_minutes', 15)

    segments = _build_segments()

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
        df_margins        = _fetch_margins_direct()
        df_holdings, sum_holdings   = _fetch_holdings_direct(df_margins)
        df_positions, sum_positions = _fetch_positions_direct()
        ist_display = timestamp_display()

        seg_state   = ctx.get('seg_state') or _default_seg_state()
        alert_state = ctx.get('alert_state', {})

        for seg in open_segments:
            ss = seg_state[seg['name']]
            seg_exchanges = seg['exchanges']
            seg_holdings  = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
                            if 'exchange' in df_holdings.columns else df_holdings
            seg_positions = df_positions[df_positions['exchange'].isin(seg_exchanges)] \
                            if 'exchange' in df_positions.columns else df_positions

            seg_sum_h = _summarise_holdings(seg_holdings, sum_holdings, seg_exchanges)
            seg_sum_p = _summarise_positions(seg_positions)

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

        ctx['seg_state']   = seg_state
        ctx['alert_state'] = alert_state
        logger.info(f"Worker: performance refreshed for {perf_key}")

        # Publish WS event — the Litestar server will invalidate its own cache
        # on receipt of this message before broadcasting to WebSocket clients.
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            payload = json.dumps({
                "event": "performance_updated",
                "refreshed_at": ist_display,
                "interval_key": perf_key,
            })
            await r.publish(PERF_CHANNEL, payload)
            await r.aclose()
        except Exception as pub_err:
            logger.warning(f"Worker: Redis publish failed: {pub_err}")

    except Exception as e:
        logger.error(f"Worker: performance refresh failed: {e}")


async def check_close_summaries(ctx):
    """
    Send close summary for any segment whose close time + offset has passed today.
    Runs every 5 minutes (same cadence as refresh_performance).
    """
    from backend.shared.helpers.broker_apis import fetch_holidays
    from backend.shared.helpers.alert_utils import send_summary
    from backend.shared.helpers.summarise import summarise_holdings as _summarise_holdings, summarise_positions as _summarise_positions

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

    seg_state = ctx.get('seg_state') or _default_seg_state()

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
                df_margins        = _fetch_margins_direct()
                df_holdings, sum_holdings   = _fetch_holdings_direct(df_margins)
                df_positions, sum_positions = _fetch_positions_direct()
                ist_display = timestamp_display()

                seg_exchanges = seg['exchanges']
                seg_holdings  = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
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

def _default_seg_state():
    """Build initial seg_state keyed by segment name from config."""
    return {s['name']: {'last_open': None, 'last_close': None}
            for s in _build_segments()}


async def startup(ctx):
    logger.info("Worker: starting up — warming market cache")
    ctx['seg_state']   = _default_seg_state()
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
