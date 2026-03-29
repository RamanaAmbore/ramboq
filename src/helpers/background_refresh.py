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

    interval = cfg.get('performance_refresh_interval', 10)
    mkt_refresh_h, mkt_refresh_m = _parse_time(cfg.get('market_refresh_time', '08:30'))
    mkt_start_h, mkt_start_m = _parse_time(cfg.get('market_hours_start', '09:00'))
    mkt_end_h, mkt_end_m = _parse_time(cfg.get('market_hours_end', '15:30'))

    last_market_date = None
    last_perf_key = None

    while True:
        try:
            now = timestamp_indian()
            today = now.date()

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

            # --- Performance data: during market hours at each interval boundary ---
            mkt_start = now.replace(hour=mkt_start_h, minute=mkt_start_m, second=0, microsecond=0)
            mkt_end = now.replace(hour=mkt_end_h, minute=mkt_end_m, second=0, microsecond=0)

            if mkt_start <= now <= mkt_end:
                perf_key = get_nearest_time(interval=interval)
                if perf_key != last_perf_key:
                    logger.info(f"Background: pre-fetching performance data for {perf_key}")
                    try:
                        df_margins = fetch_margins(perf_key)
                        fetch_holdings(perf_key, df_margins)
                        fetch_positions(perf_key)
                        last_perf_key = perf_key
                        logger.info(f"Background: performance data cached for {perf_key}")
                    except Exception as e:
                        logger.error(f"Background: performance fetch failed: {e}")

        except Exception as e:
            logger.error(f"Background refresh loop error: {e}")

        time.sleep(30)
