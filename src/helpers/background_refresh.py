import threading
import time
from datetime import timedelta, time as dtime

from src.helpers.date_time_utils import timestamp_indian, is_market_open, timestamp_display
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


def _build_segments(cfg):
    """
    Parse market_segments from config into a list of segment dicts with parsed times.
    Each entry: {name, hours_start (dtime), hours_end (dtime), holiday_exchange, exchanges (set)}
    """
    raw = cfg.get('market_segments', {})
    segments = []
    for name, s in raw.items():
        h, m = _parse_time(s.get('hours_start', '09:15'))
        eh, em = _parse_time(s.get('hours_end', '15:30'))
        segments.append({
            'name':             name,
            'hours_start':      dtime(h, m),
            'hours_end':        dtime(eh, em),
            'holiday_exchange': s.get('holiday_exchange', 'NSE'),
            'exchanges':        set(s.get('exchanges', [])),
        })
    return segments


def _load_holidays(segments, holiday_cache, year):
    """Load holiday sets for all unique holiday_exchanges for the given year."""
    from src.helpers.broker_apis import fetch_holidays
    seen = set()
    for seg in segments:
        exch = seg['holiday_exchange']
        if exch not in seen:
            seen.add(exch)
            try:
                holiday_cache.setdefault(exch, {})[year] = fetch_holidays(exch)
                logger.info(f"Background: holidays loaded for {exch} {year} "
                            f"({len(holiday_cache[exch][year])} days)")
            except Exception as e:
                logger.warning(f"Background: failed to load holidays for {exch}: {e}")
                holiday_cache.setdefault(exch, {})[year] = set()


def _loop(cfg):
    from src.utils_streamlit import fetch_margins, fetch_holdings, fetch_positions, get_market_update
    from src.helpers.utils import get_nearest_time, get_cycle_date
    from src.helpers.alert_utils import check_and_alert, send_summary

    open_offset_mins  = cfg.get('open_summary_offset_minutes', 15)
    close_offset_mins = cfg.get('close_summary_offset_minutes', 15)
    mkt_refresh_h, mkt_refresh_m = _parse_time(cfg.get('market_refresh_time', '08:30'))
    interval = cfg.get('performance_refresh_interval', 5)

    segments = _build_segments(cfg)

    # State per segment: last_open_date, last_close_date
    seg_state = {s['name']: {'last_open_date': None, 'last_close_date': None}
                 for s in segments}

    last_market_cycle_date = None
    last_perf_key          = None
    alert_state            = {}
    holiday_cache          = {}   # holiday_cache[exchange][year] = set of dates

    # Warm market update + load holidays at startup
    logger.info("Background: warming market update cache at startup")
    try:
        cycle_date = get_cycle_date()
        get_market_update(cycle_date)
        last_market_cycle_date = cycle_date
        logger.info("Background: market update cache warmed at startup")
    except Exception as e:
        logger.error(f"Background: startup market update failed: {e}")

    _load_holidays(segments, holiday_cache, timestamp_indian().year)

    while True:
        try:
            now   = timestamp_indian()
            today = now.date()

            # Refresh holiday cache on new year
            if any(now.year not in holiday_cache.get(s['holiday_exchange'], {})
                   for s in segments):
                _load_holidays(segments, holiday_cache, now.year)

            # --- Market update: re-fetch when cycle_date advances past mkt_refresh_time ---
            # get_cycle_date() flips from yesterday→today at 08:00 IST. Waiting until
            # mkt_refresh_time (08:30) ensures pre-market data is available before fetching.
            mkt_refresh_dt = now.replace(hour=mkt_refresh_h, minute=mkt_refresh_m,
                                         second=0, microsecond=0)
            cycle_date = get_cycle_date()
            if last_market_cycle_date != cycle_date and now >= mkt_refresh_dt:
                try:
                    get_market_update(cycle_date)
                    last_market_cycle_date = cycle_date
                    logger.info("Background: market update cached")
                except Exception as e:
                    logger.error(f"Background: market update failed: {e}")

            # Determine which segments are open right now
            open_segments = []
            for seg in segments:
                h_set = holiday_cache.get(seg['holiday_exchange'], {}).get(now.year, set())
                if is_market_open(now, h_set, seg['hours_start'], seg['hours_end']):
                    open_segments.append(seg)

            any_open = bool(open_segments)

            # --- Performance fetch: whenever any segment is open ---
            if any_open:
                perf_key = get_nearest_time(interval=interval)
                if perf_key != last_perf_key:
                    logger.info(f"Background: pre-fetching performance data for {perf_key}")
                    try:
                        df_margins        = fetch_margins(perf_key)
                        df_holdings, sum_holdings   = fetch_holdings(perf_key, df_margins)
                        df_positions, sum_positions = fetch_positions(perf_key)
                        last_perf_key = perf_key
                        ist_display   = timestamp_display()
                        logger.info(f"Background: performance data cached for {perf_key}")

                        for seg in open_segments:
                            ss = seg_state[seg['name']]

                            # Filter holdings/positions to this segment's exchanges
                            seg_exchanges = seg['exchanges']
                            seg_holdings  = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
                                            if 'exchange' in df_holdings.columns else df_holdings
                            seg_positions = df_positions[df_positions['exchange'].isin(seg_exchanges)] \
                                            if 'exchange' in df_positions.columns else df_positions

                            # Recompute segment summary from filtered rows
                            seg_sum_holdings  = _summarise_holdings(seg_holdings, sum_holdings, seg_exchanges)
                            seg_sum_positions = _summarise_positions(seg_positions)

                            # Open summary — offset mins after segment open, once per day
                            open_dt = now.replace(
                                hour=seg['hours_start'].hour,
                                minute=seg['hours_start'].minute,
                                second=0, microsecond=0
                            ) + timedelta(minutes=open_offset_mins)

                            if ss['last_open_date'] != today and now >= open_dt:
                                label = seg['name'].capitalize()
                                send_summary(seg_sum_holdings, seg_sum_positions,
                                             ist_display, 'open', label=label,
                                             df_margins=df_margins)
                                ss['last_open_date'] = today

                            # Loss alerts (use full sum for all-account check)
                            alert_state = check_and_alert(
                                seg_sum_holdings, seg_sum_positions, alert_state, ist_display,
                                df_margins=df_margins
                            )

                    except Exception as e:
                        logger.error(f"Background: performance fetch failed: {e}")

            # --- Close summary — once per segment after its close time on a trading day ---
            for seg in segments:
                ss = seg_state[seg['name']]
                if ss['last_close_date'] == today:
                    continue
                h_set    = holiday_cache.get(seg['holiday_exchange'], {}).get(now.year, set())
                close_dt = now.replace(hour=seg['hours_end'].hour, minute=seg['hours_end'].minute,
                                       second=0, microsecond=0)
                close_trigger_dt = close_dt + timedelta(minutes=close_offset_mins)
                if today not in h_set and now >= close_trigger_dt:
                    logger.info(f"Background: fetching close summary for {seg['name']}")
                    try:
                        close_key         = get_nearest_time(interval=interval)
                        df_margins        = fetch_margins(close_key)
                        df_holdings, sum_holdings   = fetch_holdings(close_key, df_margins)
                        df_positions, sum_positions = fetch_positions(close_key)
                        ist_display       = timestamp_display()

                        seg_exchanges = seg['exchanges']
                        seg_holdings  = df_holdings[df_holdings['exchange'].isin(seg_exchanges)] \
                                        if 'exchange' in df_holdings.columns else df_holdings
                        seg_positions = df_positions[df_positions['exchange'].isin(seg_exchanges)] \
                                        if 'exchange' in df_positions.columns else df_positions

                        seg_sum_holdings  = _summarise_holdings(seg_holdings, sum_holdings, seg_exchanges)
                        seg_sum_positions = _summarise_positions(seg_positions)

                        label = seg['name'].capitalize()
                        send_summary(seg_sum_holdings, seg_sum_positions, ist_display, 'close',
                                     label=label, df_margins=df_margins)
                        ss['last_close_date'] = today
                    except Exception as e:
                        logger.error(f"Background: close summary for {seg['name']} failed: {e}")

        except Exception as e:
            logger.error(f"Background refresh loop error: {e}")

        time.sleep(30)


def _summarise_holdings(seg_holdings, full_sum_holdings, seg_exchanges):
    """Re-derive per-account + TOTAL summary from segment-filtered holdings rows."""
    import pandas as pd
    if seg_holdings.empty:
        return seg_holdings

    sum_columns = ["inv_val", "cur_val", "pnl", "day_change_val"]
    grouped = seg_holdings.groupby("account")[sum_columns].sum().reset_index()

    # Recalculate derived pct columns
    grouped['pnl_percentage']        = grouped['pnl'] / grouped['inv_val'] * 100
    grouped['day_change_percentage'] = grouped['day_change_val'] / grouped['cur_val'] * 100

    # Pull cash from full_sum_holdings for matching accounts (equity only)
    if 'cash' in full_sum_holdings.columns:
        cash_df = full_sum_holdings[full_sum_holdings['account'] != 'TOTAL'][['account', 'cash', 'net']]
        grouped = pd.merge(grouped, cash_df, on='account', how='left')

    total = grouped[[c for c in sum_columns if c in grouped.columns]].sum().to_frame().T
    total['account'] = 'TOTAL'
    if 'pnl_percentage' in grouped.columns:
        total['pnl_percentage']        = total['pnl'] / total['inv_val'] * 100
    if 'day_change_percentage' in grouped.columns:
        total['day_change_percentage'] = total['day_change_val'] / total['cur_val'] * 100

    return pd.concat([grouped, total], ignore_index=True)


def _summarise_positions(seg_positions):
    """Re-derive per-account + TOTAL summary from segment-filtered positions rows."""
    import pandas as pd
    if seg_positions.empty:
        return seg_positions

    grouped = seg_positions.groupby("account")[["pnl"]].sum().reset_index()
    total = pd.DataFrame([{'account': 'TOTAL', 'pnl': grouped['pnl'].sum()}])
    return pd.concat([grouped, total], ignore_index=True)
