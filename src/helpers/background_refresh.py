import threading
import time
from datetime import timedelta

from src.helpers.date_time_utils import timestamp_indian, is_market_open
from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

_started = False
_lock = threading.Lock()


def start(cfg):
    """Start the background refresh daemon thread. No-op if already running."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    thread = threading.Thread(target=_loop, args=(cfg,), daemon=True, name="bg-refresh")
    thread.start()
    logger.info("Background refresh thread started")


def _parse_time(time_str):
    h, m = map(int, time_str.split(':'))
    return h, m


def _loop(cfg):
    # Deferred imports to avoid circular imports at module load
    from src.utils_streamlit import fetch_margins, fetch_holdings, fetch_positions, get_market_update
    from src.helpers.utils import get_nearest_time, get_cycle_date
    from src.helpers.alert_utils import check_and_alert, send_summary
    from src.helpers.broker_apis import fetch_nse_holidays
    from datetime import time as dtime

    interval         = cfg.get('performance_refresh_interval', 10)
    mkt_refresh_h, mkt_refresh_m = _parse_time(cfg.get('market_refresh_time', '08:30'))
    mkt_start_h, mkt_start_m     = _parse_time(cfg.get('market_hours_start', '09:15'))
    mkt_end_h, mkt_end_m         = _parse_time(cfg.get('market_hours_end', '15:30'))
    open_offset_mins              = cfg.get('open_summary_offset_minutes', 15)

    market_start = dtime(mkt_start_h, mkt_start_m)
    market_end   = dtime(mkt_end_h,   mkt_end_m)

    last_market_date  = None
    last_perf_key     = None
    last_open_date    = None
    last_close_date   = None
    alert_state       = {}
    holiday_cache     = {}   # keyed by year → set of holiday dates

    # Warm market update cache immediately at startup
    logger.info("Background: warming market update cache at startup")
    try:
        get_market_update(get_cycle_date())
        last_market_date = timestamp_indian().date()
        logger.info("Background: market update cache warmed at startup")
    except Exception as e:
        logger.error(f"Background: startup market update failed: {e}")

    # Load holiday list at startup — refresh annually
    try:
        year = timestamp_indian().year
        holiday_cache[year] = fetch_nse_holidays()
        logger.info(f"Background: NSE holidays loaded for {year} ({len(holiday_cache[year])} days)")
    except Exception as e:
        logger.warning(f"Background: failed to load NSE holidays — will use time-window only: {e}")

    while True:
        try:
            now   = timestamp_indian()
            today = now.date()

            # Refresh holiday cache on new year
            if now.year not in holiday_cache:
                try:
                    holiday_cache[now.year] = fetch_nse_holidays()
                    logger.info(f"Background: NSE holidays refreshed for {now.year}")
                except Exception as e:
                    logger.warning(f"Background: holiday refresh failed: {e}")

            current_holidays = holiday_cache.get(now.year, set())
            market_open = is_market_open(now, current_holidays, market_start, market_end)

            # --- Market update: once per day at market_refresh_time IST ---
            mkt_refresh_dt = now.replace(hour=mkt_refresh_h, minute=mkt_refresh_m, second=0, microsecond=0)
            if last_market_date != today and now >= mkt_refresh_dt:
                logger.info("Background: pre-fetching market update")
                try:
                    get_market_update(get_cycle_date())
                    last_market_date = today
                    logger.info("Background: market update cached")
                except Exception as e:
                    logger.error(f"Background: market update failed: {e}")

            # --- Performance data + open summary + alerts during market hours ---
            if market_open:
                perf_key = get_nearest_time(interval=interval)
                if perf_key != last_perf_key:
                    logger.info(f"Background: pre-fetching performance data for {perf_key}")
                    try:
                        df_margins       = fetch_margins(perf_key)
                        _, sum_holdings  = fetch_holdings(perf_key, df_margins)
                        _, sum_positions = fetch_positions(perf_key)
                        last_perf_key    = perf_key
                        logger.info(f"Background: performance data cached for {perf_key}")

                        ist_display = now.strftime("%a, %B %d, %Y, %I:%M %p")

                        # Open summary — 15 mins after market open, once per day
                        open_summary_dt = now.replace(
                            hour=mkt_start_h, minute=mkt_start_m, second=0, microsecond=0
                        ) + timedelta(minutes=open_offset_mins)
                        if last_open_date != today and now >= open_summary_dt:
                            send_summary(sum_holdings, sum_positions, ist_display, 'open')
                            last_open_date = today

                        # Intra-day loss alerts
                        alert_state = check_and_alert(
                            sum_holdings, sum_positions, alert_state, ist_display
                        )

                    except Exception as e:
                        logger.error(f"Background: performance fetch failed: {e}")

            # --- Close summary — once, after market closes on a trading day ---
            elif last_close_date != today and not market_open:
                mkt_end_dt = now.replace(hour=mkt_end_h, minute=mkt_end_m, second=0, microsecond=0)
                # Only send close if it's a trading day (not weekend/holiday) and past close time
                if today not in current_holidays and now > mkt_end_dt:
                    logger.info("Background: fetching close summary")
                    try:
                        close_key        = get_nearest_time(interval=interval)
                        df_margins       = fetch_margins(close_key)
                        _, sum_holdings  = fetch_holdings(close_key, df_margins)
                        _, sum_positions = fetch_positions(close_key)
                        ist_display      = now.strftime("%a, %B %d, %Y, %I:%M %p")
                        send_summary(sum_holdings, sum_positions, ist_display, 'close')
                        last_close_date  = today
                    except Exception as e:
                        logger.error(f"Background: close summary failed: {e}")

        except Exception as e:
            logger.error(f"Background refresh loop error: {e}")

        time.sleep(30)
