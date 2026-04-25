from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo


from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

# Define constants for timezones
EST_ZONE = ZoneInfo("US/Eastern")
INDIAN_TIMEZONE = ZoneInfo("Asia/Kolkata")


# Helper functions for direct use
def timestamp_local():
    """Returns today's date in the local timezone."""
    return datetime.today()  # Uses system's local timezone


def timestamp_est():
    return datetime.now(tz=EST_ZONE)


def timestamp_indian():
    return datetime.now(tz=INDIAN_TIMEZONE)


def today_local():
    """Returns today's date in the local timezone."""
    return datetime.now().date()  # Uses system's local timezone


def today_est():
    return datetime.now(tz=EST_ZONE).date()


def today_indian():
    return datetime.now(tz=INDIAN_TIMEZONE).date()


def current_time_local():
    """Returns the current time in the local timezone."""
    return datetime.today().time()  # Uses system's local timezone


def current_time_est():
    return datetime.now(tz=EST_ZONE).time()


def current_time_indian():
    return datetime.now(tz=INDIAN_TIMEZONE).time()


def timestamp_display() -> str:
    """
    Compact dual-timezone timestamp for alerts, emails, and public-site
    refreshed_at strings. Day-first, 3-letter weekday + month, 24-hour
    time, year dropped (implied by the session). Matches
    stores.js::clientTimestamp so client-generated banners and
    server-generated refreshed_at stamps look identical everywhere.

    Example: "Sat 25 Apr 07:03 IST | Fri 24 Apr 21:33 EDT"
    %Z renders EST / EDT automatically by season.
    """
    now_ist = timestamp_indian()
    now_est = timestamp_est()
    ist_str = now_ist.strftime('%a %d %b %H:%M IST')
    est_str = now_est.strftime('%a %d %b %H:%M %Z')
    return f"{ist_str} | {est_str}"


def is_market_open(now, holiday_set: set, market_start: dtime = dtime(9, 15),
                   market_end: dtime = dtime(15, 30)) -> bool:
    """
    Returns True if the market is currently open.
    - now: timezone-aware datetime in IST
    - holiday_set: set of date objects from fetch_nse_holidays()
    - Weekends are NOT hardcoded as closed — special trading sessions on
      Saturdays/Sundays are handled correctly since they won't appear in
      the NSE holiday list. Regular weekends will run the broker fetch but
      return stale closing data (day change = 0, no alerts fire).
    - Falls back to time-window-only check if holiday_set is empty.
    """
    if holiday_set and now.date() in holiday_set:
        return False
    # Regular weekends are closed (Muhurat trading on special Saturdays
    # will need an explicit override if needed in future)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    t = now.time().replace(second=0, microsecond=0)
    return market_start <= t <= market_end


def convert_to_timezone(date_str, format='%Y-%m-%d', return_date=True, tz=INDIAN_TIMEZONE):
    try:
        dt = datetime.strptime(date_str, format).replace(tzinfo=tz)  # Assign the correct timezone
        return dt if return_date is None else (dt.date() if return_date else dt.time())
    except Exception:
        logger.warning(f"Invalid date format: {date_str}")
        return None


# Test Code in __main__
if __name__ == "__main__":
    logger.info(f"EST timestamp: {timestamp_est()}")
    logger.info(f"Indian timestamp: {timestamp_indian()}")
    logger.info(f"Local timestamp: {timestamp_local()}")

    logger.info(f"Today's Date in EST: {today_est()}")
    logger.info(f"Today's Date in IST: {today_indian()}")
    logger.info(f"Current Time in IST: {today_local()}")

    logger.info(f"Current Time in IST: {current_time_indian()}")
    logger.info(f"Current Time in EST: {current_time_local()}")
    logger.info(f"Current Time in EST: {current_time_est()}")
