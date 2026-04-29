/**
 * Frontend market-hours gate for auto-refresh polling.
 *
 * Indian market segments (matches `backend_config.yaml::market_segments`):
 *   NSE equity:    09:15-15:30 IST, Mon-Fri
 *   MCX commodity: 09:00-23:30 IST, Mon-Fri
 *
 * The "any segment open" window is therefore 09:00-23:30 IST on weekdays.
 * That's the gate `marketAwareInterval` uses — outside this window the
 * auto-refresh polls pause; inside, they tick at the usual cadence.
 *
 * Holidays aren't gated here — the frontend doesn't have access to the
 * Kite-fetched NSE/MCX holiday calendars. On a holiday the polls still
 * run but the backend returns the same cached values. The main goal is
 * to kill the overnight + weekend traffic, which is by far the bulk of
 * the savings.
 *
 * Manual refresh buttons (the ↻ on /admin/options, the Refresh on
 * /performance, etc.) bypass this gate by design — operators clicking
 * a button are explicitly asking for a fresh fetch and we honour it.
 */

// Minute-of-day boundaries (IST).
const NSE_OPEN_MIN  = 9 * 60 + 15;   // 09:15
const NSE_CLOSE_MIN = 15 * 60 + 30;  // 15:30
const MCX_OPEN_MIN  = 9 * 60;        // 09:00
const MCX_CLOSE_MIN = 23 * 60 + 30;  // 23:30
const ANY_OPEN_MIN  = MCX_OPEN_MIN;
const ANY_CLOSE_MIN = MCX_CLOSE_MIN;

const _WD_MAP = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

/** Resolve current IST weekday + minute-of-day from a Date. */
function _istNow(/** @type {Date} */ now) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Kolkata',
  }).formatToParts(now);
  const pick = (t) => (parts.find(p => p.type === t) || {}).value || '';
  const hh = parseInt(pick('hour'), 10) || 0;
  const mm = parseInt(pick('minute'), 10) || 0;
  return {
    weekday: _WD_MAP[pick('weekday')] ?? 0,
    minute:  hh * 60 + mm,
  };
}

/** Any market segment open — 09:00-23:30 IST Mon-Fri. */
export function isMarketOpen(/** @type {Date} */ now = new Date()) {
  const { weekday, minute } = _istNow(now);
  if (weekday === 0 || weekday === 6) return false;
  return minute >= ANY_OPEN_MIN && minute <= ANY_CLOSE_MIN;
}

/** NSE equity window — 09:15-15:30 IST Mon-Fri. */
export function isNseOpen(/** @type {Date} */ now = new Date()) {
  const { weekday, minute } = _istNow(now);
  if (weekday === 0 || weekday === 6) return false;
  return minute >= NSE_OPEN_MIN && minute <= NSE_CLOSE_MIN;
}

/** MCX commodity window — 09:00-23:30 IST Mon-Fri. */
export function isMcxOpen(/** @type {Date} */ now = new Date()) {
  const { weekday, minute } = _istNow(now);
  if (weekday === 0 || weekday === 6) return false;
  return minute >= MCX_OPEN_MIN && minute <= MCX_CLOSE_MIN;
}
