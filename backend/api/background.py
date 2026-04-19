"""
Litestar-integrated background scheduler.

Runs entirely inside the Litestar event loop — no ARQ, no Redis required.
Blocking broker API calls are offloaded to a ThreadPoolExecutor so they
never stall the async event loop.

Three tasks are started on Litestar startup:
  1. _task_performance — refresh holdings/positions/funds every N minutes during market hours,
                         send open/close summaries, fire loss alerts.
  2. _task_market      — warm market cache at startup; re-warm daily at 08:30 IST.
  3. _task_close       — check for segment close summaries (same cadence as performance).

All three tasks are cancelled cleanly on Litestar shutdown.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, time as dtime

import pandas as pd

from backend.shared.helpers.date_time_utils import timestamp_indian, is_market_open, timestamp_display
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config, get_nearest_time, get_cycle_date, mask_column

logger = get_logger(__name__)

# Thread pool for blocking broker calls (keeps async loop responsive)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ramboq-bg")


# ---------------------------------------------------------------------------
# Segment config helpers
# ---------------------------------------------------------------------------

def _parse_time(t: str) -> dtime:
    h, m = map(int, t.split(':'))
    return dtime(h, m)


def _build_segments() -> list[dict]:
    raw = config.get('market_segments', {})
    return [
        {
            'name':             name,
            'hours_start':      _parse_time(s.get('hours_start', '09:15')),
            'hours_end':        _parse_time(s.get('hours_end',   '15:30')),
            'holiday_exchange': s.get('holiday_exchange', 'NSE'),
            'exchanges':        set(s.get('exchanges', [])),
        }
        for name, s in raw.items()
    ]


def _default_seg_state() -> dict:
    return {s['name']: {'last_open': None, 'last_close': None}
            for s in _build_segments()}


# ---------------------------------------------------------------------------
# Direct broker fetch helpers
# ---------------------------------------------------------------------------

def _fetch_margins_direct() -> pd.DataFrame:
    """Returns pandas DataFrame (alert utils expect pandas)."""
    from backend.shared.helpers import broker_apis
    df = pd.concat(broker_apis.fetch_margins(), ignore_index=True)
    df['account'] = mask_column(df['account'])
    total_row = df.select_dtypes(include='number').sum()
    total_row['account'] = 'TOTAL'
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)


def _fetch_holdings_direct() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (row_df, summary_df) as plain pandas (alert utils expect pandas)."""
    from backend.shared.helpers import broker_apis
    raw = pd.concat(broker_apis.fetch_holdings(), ignore_index=True)
    raw['account'] = mask_column(raw['account'])

    sum_cols = [c for c in ['inv_val', 'cur_val', 'pnl', 'day_change_val'] if c in raw.columns]
    grouped = raw.groupby('account')[sum_cols].sum().reset_index()
    if 'pnl' in grouped and 'inv_val' in grouped:
        grouped['pnl_percentage']        = grouped['pnl'] / grouped['inv_val'] * 100
    if 'day_change_val' in grouped and 'cur_val' in grouped:
        grouped['day_change_percentage'] = grouped['day_change_val'] / grouped['cur_val'] * 100

    totals = grouped[sum_cols].sum().to_frame().T
    totals['account'] = 'TOTAL'
    if 'pnl' in totals and 'inv_val' in totals:
        totals['pnl_percentage']        = totals['pnl'] / totals['inv_val'] * 100
    if 'day_change_val' in totals and 'cur_val' in totals:
        totals['day_change_percentage'] = totals['day_change_val'] / totals['cur_val'] * 100

    summary = pd.concat([grouped, totals], ignore_index=True).fillna(0)
    return raw, summary


def _fetch_positions_direct() -> tuple[pd.DataFrame, pd.DataFrame]:
    from backend.shared.helpers import broker_apis
    raw = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
    raw['account'] = mask_column(raw['account'])
    grouped = raw.groupby('account')[['pnl']].sum().reset_index() if 'pnl' in raw.columns \
              else pd.DataFrame(columns=['account', 'pnl'])
    total   = pd.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
    summary = pd.concat([grouped, total], ignore_index=True)
    return raw, summary


# ---------------------------------------------------------------------------
# Async wrappers — run blocking calls in thread pool
# ---------------------------------------------------------------------------

async def _run(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _load_market_from_db():
    """Return MarketResponse if a DB row exists and is <24h old, else None."""
    from datetime import datetime, timezone
    from backend.api.database import async_session
    from backend.api.models import MarketReport
    from backend.api.schemas import MarketResponse

    try:
        async with async_session() as s:
            row = await s.get(MarketReport, 1)
        if not row:
            return None
        age = (datetime.now(timezone.utc) - row.generated_at).total_seconds()
        if age >= 86400:
            return None
        return MarketResponse(content=row.content, cycle_date=row.cycle_date,
                              refreshed_at=row.refreshed_at)
    except Exception as e:
        logger.error(f"Background: market DB load failed: {e}")
        return None


async def _save_market_to_db(resp) -> None:
    """Upsert id=1 row with the latest market report."""
    from datetime import datetime, timezone
    from backend.api.database import async_session
    from backend.api.models import MarketReport

    try:
        async with async_session() as s:
            row = await s.get(MarketReport, 1)
            now_utc = datetime.now(timezone.utc)
            if row:
                row.content = resp.content
                row.cycle_date = resp.cycle_date
                row.refreshed_at = resp.refreshed_at
                row.generated_at = now_utc
            else:
                s.add(MarketReport(
                    id=1, content=resp.content, cycle_date=resp.cycle_date,
                    refreshed_at=resp.refreshed_at, generated_at=now_utc,
                ))
            await s.commit()
        logger.info("Background: market report saved to DB")
    except Exception as e:
        logger.error(f"Background: market DB save failed: {e}")


async def _task_market(state: dict) -> None:
    """
    Startup: hydrate cache from DB if <24h old, else call Gemini + save.
    Then daily at 07:00 IST: call Gemini + save.
    """
    from backend.api.routes.market import fetch_fresh
    from backend.api.cache import _store
    import time as _time

    def _hydrate(resp):
        _store["market"] = (_time.monotonic() + 86400, resp)

    cached = await _load_market_from_db()
    if cached:
        _hydrate(cached)
        logger.info(f"Background: market cache hydrated from DB (cycle {cached.cycle_date})")
    else:
        try:
            result = await _run(fetch_fresh)
            if result is None:
                logger.warning("Background: Gemini empty at startup — leaving cache/DB untouched")
            else:
                _hydrate(result)
                await _save_market_to_db(result)
                logger.info(f"Background: market generated at startup (cycle {get_cycle_date()})")
        except Exception as e:
            logger.error(f"Background: market startup warm failed: {e}")

    while True:
        now = timestamp_indian()
        next_warm = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if now >= next_warm:
            next_warm += timedelta(days=1)
        sleep_s = (next_warm - now).total_seconds()
        logger.info(f"Background: market task sleeping {sleep_s/3600:.1f}h until next warm")
        await asyncio.sleep(sleep_s)

        try:
            result = await _run(fetch_fresh)
            if result is None:
                logger.warning("Background: Gemini empty on daily refresh — keeping previous report")
                continue
            _hydrate(result)
            await _save_market_to_db(result)
            logger.info(f"Background: market cache warmed for cycle {get_cycle_date()}")

            from backend.api.routes.ws import broadcast
            import json
            broadcast(json.dumps({"event": "market_updated", "refreshed_at": timestamp_display()}))
        except Exception as e:
            logger.error(f"Background: market warm failed: {e}")


async def _task_performance(state: dict) -> None:
    """Refresh performance data every N minutes during market hours."""
    from backend.shared.helpers.broker_apis import fetch_holidays
    from backend.shared.helpers.alert_utils import send_summary, check_and_alert
    from backend.shared.helpers.summarise import summarise_holdings as _summarise_holdings, summarise_positions as _summarise_positions
    from backend.api.cache import invalidate_all
    from backend.api.routes.ws import broadcast
    import json

    interval   = config.get('performance_refresh_interval', 5)
    open_offset = config.get('open_summary_offset_minutes', 15)

    seg_state   = _default_seg_state()
    alert_state = {}
    holiday_cache: dict = {}

    while True:
        await asyncio.sleep(interval * 60)

        now   = timestamp_indian()
        today = now.date()

        # Refresh holiday calendars at year boundary
        if not holiday_cache or getattr(state, '_hol_year', None) != today.year:
            holiday_cache = {}
            state['_hol_year'] = today.year

        segments = _build_segments()

        for seg in segments:
            exch = seg['holiday_exchange']
            if exch not in holiday_cache:
                try:
                    holiday_cache[exch] = await _run(fetch_holidays, exch)
                except Exception as e:
                    logger.debug(f"Background: holiday load skipped for {exch}: {e}")
                    holiday_cache[exch] = set()

        open_segments = [
            seg for seg in segments
            if is_market_open(now, holiday_cache.get(seg['holiday_exchange'], set()),
                              seg['hours_start'], seg['hours_end'])
        ]

        if not open_segments:
            continue

        try:
            (df_holdings, sum_holdings), (df_positions, sum_positions) = \
                await _run(lambda: (_fetch_holdings_direct(), _fetch_positions_direct()))

            df_margins  = await _run(_fetch_margins_direct)
            ist_display = timestamp_display()
            perf_key    = get_nearest_time(interval=interval)

            # Full portfolio summaries (no segment filtering)
            all_sum_h = _summarise_holdings(df_holdings, sum_holdings, None)
            all_sum_p = _summarise_positions(df_positions)

            for seg in open_segments:
                ss = seg_state[seg['name']]

                open_trigger = now.replace(
                    hour=seg['hours_start'].hour,
                    minute=seg['hours_start'].minute,
                    second=0, microsecond=0
                ) + timedelta(minutes=open_offset)

                if ss['last_open'] != today and now >= open_trigger:
                    _label = seg['name'].capitalize()
                    _dm = df_margins
                    try:
                        await _run(lambda: send_summary(all_sum_h, all_sum_p, ist_display,
                                                        'open', label=_label, df_margins=_dm))
                        logger.info(f"Background: open summary sent for {seg['name']}")
                    except Exception as e:
                        logger.error(f"Background: open summary failed for {seg['name']}: {e}")
                    ss['last_open'] = today

            # Loss alerts — full portfolio, once per refresh
            try:
                _as = alert_state
                _dm = df_margins
                await _run(lambda: check_and_alert(all_sum_h, all_sum_p, _as, ist_display, _dm))
            except Exception as e:
                logger.error(f"Background: alert check failed: {e}")

            # Run agent engine with market data context
            try:
                from backend.api.algo.agent_engine import run_cycle
                from backend.api.routes.algo import _broadcast_event
                agent_context = {
                    "sum_holdings": sum_holdings,
                    "sum_positions": sum_positions,
                    "df_margins": df_margins,
                    "df_holdings": df_holdings,
                    "df_positions": df_positions,
                    "ist_display": ist_display,
                    "now": now,
                    "seg_state": seg_state,
                    # alert_state is the long-lived dict owned here (pnl_history,
                    # session_start, last_alert buckets, funds_*). Passed so the
                    # v2 grammar evaluator in run_cycle can read rate history
                    # and write its own suppression entries without needing a
                    # parallel state store.
                    "alert_state": alert_state,
                    "segments":    segments,
                }
                await run_cycle(agent_context, broadcast_fn=_broadcast_event)
            except Exception as ae:
                logger.error(f"Background: agent engine failed: {ae}")

            # Invalidate in-process cache and push to WebSocket clients
            invalidate_all()
            broadcast(json.dumps({
                "event":        "performance_updated",
                "refreshed_at": ist_display,
                "interval_key": perf_key,
            }))
            logger.info(f"Background: performance refreshed — {ist_display}")

        except Exception as e:
            logger.error(f"Background: performance refresh failed: {e}")


async def _task_close(state: dict) -> None:
    """Send close summary for each segment after its close time + offset."""
    from backend.shared.helpers.broker_apis import fetch_holidays
    from backend.shared.helpers.alert_utils import send_summary
    from backend.shared.helpers.summarise import summarise_holdings as _summarise_holdings, summarise_positions as _summarise_positions

    interval     = config.get('performance_refresh_interval', 5)
    close_offset = config.get('close_summary_offset_minutes', 15)

    seg_state     = state.setdefault('close_seg_state', _default_seg_state())
    holiday_cache: dict = {}

    while True:
        await asyncio.sleep(interval * 60)

        now   = timestamp_indian()
        today = now.date()
        segments = _build_segments()

        for seg in segments:
            exch = seg['holiday_exchange']
            if exch not in holiday_cache:
                try:
                    holiday_cache[exch] = await _run(fetch_holidays, exch)
                except Exception:
                    holiday_cache[exch] = set()

        for seg in segments:
            ss = seg_state[seg['name']]
            if ss['last_close'] == today:
                continue

            h_set = holiday_cache.get(seg['holiday_exchange'], set())
            close_trigger = now.replace(
                hour=seg['hours_end'].hour,
                minute=seg['hours_end'].minute,
                second=0, microsecond=0
            ) + timedelta(minutes=close_offset)

            if today not in h_set and now.weekday() < 5 and now >= close_trigger:
                try:
                    (df_h, sum_h), (df_p, sum_p) = await _run(
                        lambda: (_fetch_holdings_direct(), _fetch_positions_direct()))
                    df_margins  = await _run(_fetch_margins_direct)
                    ist_display = timestamp_display()

                    _sh = _summarise_holdings(df_h, sum_h, None)
                    _sp = _summarise_positions(df_p)
                    _label = seg['name'].capitalize()
                    _dm = df_margins
                    await _run(lambda: send_summary(_sh, _sp, ist_display, 'close',
                                                    label=_label, df_margins=_dm))
                    ss['last_close'] = today
                    logger.info(f"Background: close summary sent for {seg['name']}")
                except Exception as e:
                    logger.error(f"Background: close summary failed for {seg['name']}: {e}")


# ---------------------------------------------------------------------------
# Litestar lifecycle hooks
# ---------------------------------------------------------------------------

async def _task_expiry_check() -> None:
    """Check once daily at 09:20 IST if today is an expiry day and auto-start the engine."""
    from backend.api.algo.expiry import ExpiryEngine
    from backend.api.routes.algo import _broadcast_event

    while True:
        now = timestamp_indian()
        # Schedule for 09:20 IST daily
        check_time = now.replace(hour=9, minute=20, second=0, microsecond=0)
        if now >= check_time:
            check_time += timedelta(days=1)
        sleep_s = (check_time - now).total_seconds()
        logger.info(f"Background: expiry check sleeping {sleep_s/3600:.1f}h until {check_time.strftime('%H:%M')}")
        await asyncio.sleep(sleep_s)

        try:
            engine = ExpiryEngine(on_event=_broadcast_event)
            # Quick scan to see if any positions expire today
            positions = await _run(engine._fetch_option_positions)
            today = timestamp_indian().date()
            expiring = [p for p in positions if p.expiry == today]

            if expiring:
                logger.info(f"Background: expiry day detected — {len(expiring)} option positions expiring today")
                _broadcast_event("expiry_day_detected", {"count": len(expiring)})
                # Run full expiry engine
                await engine.run()
            else:
                logger.info("Background: no option positions expiring today")
        except Exception as e:
            logger.error(f"Background: expiry check failed: {e}")


async def _task_instruments() -> None:
    """Warm the Kite instrument cache once at startup and daily at 08:00 IST."""
    from backend.api.routes.instruments import _fetch_instruments
    from backend.api.cache import _store
    import time as _time

    async def _warm():
        try:
            result = await _run(_fetch_instruments)
            _store["instruments"] = (_time.monotonic() + 86400, result)
            logger.info(f"Background: instruments cache warmed ({result.count} rows)")
        except Exception as e:
            logger.error(f"Background: instruments warm failed: {e}")

    await _warm()

    while True:
        now = timestamp_indian()
        # Refresh at 08:00 IST daily (Kite master updates ~07:30)
        next_warm = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= next_warm:
            next_warm += timedelta(days=1)
        sleep_s = (next_warm - now).total_seconds()
        logger.info(f"Background: instruments task sleeping {sleep_s/3600:.1f}h until next warm")
        await asyncio.sleep(sleep_s)
        await _warm()


async def on_startup(app) -> None:
    """Start all background tasks. Called by Litestar on startup."""
    state: dict = {}
    app.state.bg_tasks = [
        asyncio.create_task(_task_market(state),      name="bg-market"),
        asyncio.create_task(_task_performance(state), name="bg-performance"),
        asyncio.create_task(_task_close(state),       name="bg-close"),
        asyncio.create_task(_task_expiry_check(),     name="bg-expiry"),
        asyncio.create_task(_task_instruments(),      name="bg-instruments"),
    ]
    logger.info("Background: all tasks started (market, performance, close, expiry, instruments)")


async def on_shutdown(app) -> None:
    """Cancel all background tasks. Called by Litestar on shutdown."""
    tasks: list[asyncio.Task] = getattr(app.state, 'bg_tasks', [])
    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _executor.shutdown(wait=False)
    logger.info("Background: all tasks stopped")
