/**
 * Shared app state — auth + client-side data cache.
 *
 * Auth store: persists JWT + user profile in sessionStorage so page reloads
 * keep the session alive. Writable store so any component can react to login/logout.
 *
 * Data cache: plain module-level object (not reactive). Pages write to it after
 * a successful fetch and read from it on mount to show stale-while-revalidate data
 * immediately when navigating back.
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

// ---------------------------------------------------------------------------
// Auth store
// ---------------------------------------------------------------------------

function _readSession() {
  if (!browser) return { token: null, user: null };
  try {
    const token = sessionStorage.getItem('ramboq_token');
    const raw   = sessionStorage.getItem('ramboq_user');
    const user  = raw ? JSON.parse(raw) : null;
    return { token, user };
  } catch {
    return { token: null, user: null };
  }
}

function createAuthStore() {
  const { subscribe, set } = writable(_readSession());

  return {
    subscribe,

    /** Call after successful login. */
    login(token, user) {
      if (browser) {
        sessionStorage.setItem('ramboq_token', token);
        sessionStorage.setItem('ramboq_user', JSON.stringify(user));
      }
      set({ token, user });
    },

    /** Call on logout or 401. */
    logout() {
      if (browser) {
        sessionStorage.removeItem('ramboq_token');
        sessionStorage.removeItem('ramboq_user');
      }
      set({ token: null, user: null });
    },

    /** Read token directly (non-reactive). */
    getToken() {
      return browser ? sessionStorage.getItem('ramboq_token') : null;
    },
  };
}

export const authStore = createAuthStore();

// ---------------------------------------------------------------------------
// Data cache — stale-while-revalidate for all data pages
// Each entry: { data, refreshed_at } or null before first fetch.
// ---------------------------------------------------------------------------

export const dataCache = {
  market:    null,   // { content, cycle_date, refreshed_at }
  holdings:  null,   // { rows, summary, refreshed_at }
  positions: null,   // { rows, summary, refreshed_at }
  funds:     null,   // { rows, refreshed_at }
  insights:  null,   // { content }
};

/**
 * Compact current time for the page-top timestamp banner. Drops the
 * weekday and year (the page tells you what year it is) and uses
 * 24-hour time so IST + EST line up visually. Example:
 *   "Apr 20, 22:00 IST | 12:30 EDT"
 * ~28 chars vs the previous ~65. All operationally-useful info kept —
 * date, both time zones, and the auto-resolving TZ abbreviation (EST
 * in winter, EDT in summer).
 */
export function clientTimestamp() {
  const now = new Date();
  const datePart = now.toLocaleDateString('en-US', {
    month: 'short', day: '2-digit', timeZone: 'Asia/Kolkata',
  });
  const fmtTime = (tz) => now.toLocaleTimeString('en-GB', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz,
  });
  const estTz = now.toLocaleTimeString('en-US', {
    timeZoneName: 'short', timeZone: 'America/New_York',
  }).split(' ').pop();   // "EST" or "EDT" — depends on season
  return `${datePart}, ${fmtTime('Asia/Kolkata')} IST | ${fmtTime('America/New_York')} ${estTz}`;
}

/** Short DD-MMM HH:MM:SS IST | DD-MMM HH:MM:SS EST for log entries. Input: ISO string or Date. */
export function logTime(iso) {
  if (!iso) return '';
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  if (isNaN(d)) return '';
  const fmt = (tz) => d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, timeZone: tz,
  }).replace(',', '');
  return `${fmt('Asia/Kolkata')} IST | ${fmt('America/New_York')} EST`;
}

/** Parse the leading 'YYYY-MM-DD HH:MM:SS[,ms]' timestamp from a python log line
 *  (treated as UTC) and return short IST|EST. Returns null if not found. */
export function parseLogLineTime(line) {
  const m = line?.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})/);
  if (!m) return null;
  return logTime(`${m[1]}T${m[2]}Z`);
}
