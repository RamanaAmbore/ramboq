import threading
import time

from src.helpers.date_time_utils import timestamp_indian
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

    interval           = cfg.get('performance_refresh_interval', 10)
    mkt_refresh_h, mkt_refresh_m   = _parse_time(cfg.get('market_refresh_time', '08:30'))
    mkt_start_h,  mkt_start_m      = _parse_time(cfg.get('market_hours_start', '09:00'))
    mkt_end_h,    mkt_end_m        = _parse_time(cfg.get('market_hours_end', '15:30'))
    open_summary_h, open_summary_m = _parse_time(cfg.get('market_open_summary_time', '09:30'))

    last_market_date  = None
    last_perf_key     = None
    last_open_date    = None   # date of last open summary sent
    last_close_date   = None   # date of last close summary sent
    alert_state       = {}     # cooldown tracker per account+type

    # Warm market update cache immediately at startup
    logger.info("Background: warming market update cache at startup")
    try:
        get_market_update(get_cycle_date())
        last_market_date = timestamp_indian().date()
        logger.info("Background: market update cache warmed at startup")
    except Exception as e:
        logger.error(f"Background: startup market update failed: {e}")

    while True:
        try:
            now   = timestamp_indian()
            today = now.date()

            mkt_start = now.replace(hour=mkt_start_h, minute=mkt_start_m, second=0, microsecond=0)
            mkt_end   = now.replace(hour=mkt_end_h,   minute=mkt_end_m,   second=0, microsecond=0)

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

            # --- Performance data + alerts + open/close summaries during and around market hours ---
            if mkt_start <= now <= mkt_end:
                perf_key = get_nearest_time(interval=interval)
                if perf_key != last_perf_key:
                    logger.info(f"Background: pre-fetching performance data for {perf_key}")
                    try:
                        df_margins   = fetch_margins(perf_key)
                        _, sum_holdings  = fetch_holdings(perf_key, df_margins)
                        _, sum_positions = fetch_positions(perf_key)
                        last_perf_key = perf_key
                        logger.info(f"Background: performance data cached for {perf_key}")

                        ist_display = now.strftime("%a, %B %d, %Y, %I:%M %p")

                        # Open summary — first fetch at/after open_summary_time (default 09:30)
                        open_summary_dt = now.replace(hour=open_summary_h, minute=open_summary_m,
                                                      second=0, microsecond=0)
                        if last_open_date != today and now >= open_summary_dt:
                            send_summary(sum_holdings, sum_positions, ist_display, 'open')
                            last_open_date = today

                        # Intra-day loss alerts
                        alert_state = check_and_alert(
                            sum_holdings, sum_positions, alert_state, ist_display
                        )

                    except Exception as e:
                        logger.error(f"Background: performance fetch failed: {e}")

            # --- Close summary — once, at/after market end ---
            elif now > mkt_end and last_close_date != today:
                logger.info("Background: fetching close summary")
                try:
                    close_key    = get_nearest_time(interval=interval)
                    df_margins   = fetch_margins(close_key)
                    _, sum_holdings  = fetch_holdings(close_key, df_margins)
                    _, sum_positions = fetch_positions(close_key)
                    ist_display  = now.strftime("%a, %B %d, %Y, %I:%M %p")
                    send_summary(sum_holdings, sum_positions, ist_display, 'close')
                    last_close_date = today
                except Exception as e:
                    logger.error(f"Background: close summary failed: {e}")

        except Exception as e:
            logger.error(f"Background refresh loop error: {e}")

        time.sleep(30)
