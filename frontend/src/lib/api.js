/**
 * API helpers — thin wrappers around the Litestar REST endpoints.
 * All functions return plain JS objects matching the Pydantic response schemas.
 *
 * Auth: protected endpoints require a JWT stored in sessionStorage as 'ramboq_token'.
 * A 401 response clears the token and redirects to /signin.
 *
 * Base URL resolves to the Vite dev-proxy (/api → http://localhost:8000)
 * in dev mode, and to the same origin in production.
 */

const BASE = '/api';

import { authStore } from '$lib/stores';

/** Return auth headers if a token is present, empty object otherwise. */
function _authHeaders() {
  const token = authStore.getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function _hasToken() { return !!authStore.getToken(); }

/** Handle 401 — clear the token and (only if there was one) redirect
 *  to signin. An anonymous demo session can hit endpoints that 401
 *  for unauthenticated requests; those shouldn't bounce the visitor
 *  to /signin (they're browsing the public algo demo, not a stale
 *  admin session). The redirect now fires only when a token actually
 *  existed — i.e., a session expired. */
function _handle401() {
  const hadToken = !!authStore.getToken();
  authStore.logout();
  if (hadToken && typeof window !== 'undefined') {
    window.location.href = '/signin';
  }
}

// ── Error handling: friendly UI message + raw console log ────────────
// Anonymous sessions on prod = demo. We treat them as such for two
// reasons: (1) error messages should explain "this is read-only" rather
// than "Unauthorized"; (2) raw console output must be masked so account
// IDs / tokens don't leak to a recruiter who opens devtools.
function _isAnonymous() { return !authStore.getToken(); }

// Patterns we mask before printing to console in anonymous (demo)
// sessions. Backend already masks accounts via mask_column() in row
// data; this is a defence-in-depth net for stack traces or error
// detail strings that might still carry the raw values.
const _SECRET_PATTERNS = [
  { re: /\bZ[A-Z]\d{4,8}\b/g, sub: 'Z#####' },                            // account IDs (ZG0790, ZJ6294, …)
  { re: /\b[A-Z0-9]{32,}\b/g, sub: '<key>' },                             // long uppercase tokens / keys
  { re: /\bbearer\s+[a-zA-Z0-9._-]{20,}\b/gi, sub: 'bearer <token>' },    // JWT-shaped strings
  { re: /\b[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b/gi, sub: '<email>' }, // email addresses
];

function _maskForDemoLog(/** @type {unknown} */ value) {
  if (typeof value === 'string') {
    let out = value;
    for (const { re, sub } of _SECRET_PATTERNS) out = out.replace(re, sub);
    return out;
  }
  if (value && typeof value === 'object') {
    try {
      return JSON.parse(_maskForDemoLog(JSON.stringify(value)));
    } catch (_) { return value; }
  }
  return value;
}

/** Log the raw error to the browser console for debugging. In an
 *  anonymous (demo) session, account IDs and secrets are masked first
 *  so accidental leaks via console.error never show real values. */
function _logApiError(/** @type {string} */ path,
                     /** @type {number|null} */ status,
                     /** @type {unknown} */ raw) {
  const safe = _isAnonymous() ? _maskForDemoLog(raw) : raw;
  // Use console.warn rather than .error so a transient 5xx during a
  // poll doesn't tag every page with the red-error glyph in devtools.
  console.warn(`[api] ${path}${status ? ` (${status})` : ' (network)'}:`, safe);
}

/** Translate a fetch failure into a friendly UI string. Pages render
 *  this verbatim (no HTML), so it must be self-contained text. The
 *  raw backend `detail` is logged separately by _logApiError. */
function _friendlyError(/** @type {number|null} */ status,
                        /** @type {string|null} */ detail) {
  const isAnon = _isAnonymous();
  // Prefer the backend's `detail` for 401/403 when present — it carries
  // the real reason ("Invalid username or password" on a bad login,
  // "Live order placement is not available in demo mode" on a demo
  // chokepoint). Fall back to the generic only when the server didn't
  // supply a body (e.g. token expired mid-poll).
  if (status === 401) {
    if (detail) return detail;
    return isAnon
      ? 'Sign in to use this feature.'
      : 'Your session has expired — please sign in again.';
  }
  if (status === 403) {
    if (detail) return detail;
    return isAnon
      ? 'This action is read-only in the demo. Sign in to enable it.'
      : "You don't have permission for this action.";
  }
  if (status === 404)              return 'That information is not available right now.';
  if (status === 429)              return 'Slow down a moment, then retry.';
  // Soft language deliberately — surfaces avoid the word "failed" and
  // suggest a retry instead, matching the user request that errors
  // read more like "still working" than "broke".
  if (status && status >= 500)     return "We're having trouble reaching that — please try again in a moment.";
  if (status == null || status === 0) {
    return 'Connection trouble — please try again in a moment.';
  }
  // Backend-supplied detail for 4xx is usually already user-readable
  // (e.g. validation errors). Surface it as-is, stripping any HTTP
  // boilerplate that might have crept in.
  if (detail) return detail.replace(/^(GET|POST|PUT|PATCH|DELETE)\s+\S+\s+failed:\s*/i, '');
  return 'The request was rejected — please try again.';
}

/** One fetch wrapper to rule them all. Replaces ~15 hand-rolled
 *  fetch+401+error blocks, and routes every error through the
 *  friendly-message + masked-log pipeline. */
async function _request(/** @type {string} */ method,
                        /** @type {string} */ path,
                        /** @type {{auth?: boolean, body?: unknown}} */ opts = {}) {
  const { auth = false, body } = opts;
  /** @type {Record<string, string>} */
  const headers = auth ? { ..._authHeaders() } : {};
  /** @type {RequestInit} */
  const init = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch (e) {
    _logApiError(path, null, /** @type {any} */ (e)?.message || e);
    throw new Error(_friendlyError(null, null));
  }
  if (res.status === 401) {
    _handle401();
    const friendly = _friendlyError(401, null);
    _logApiError(path, 401, friendly);
    throw new Error(friendly);
  }
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    const detail = errBody?.detail || res.statusText || null;
    _logApiError(path, res.status, detail);
    throw new Error(_friendlyError(res.status, detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

// Method-specific shortcuts over _request — same friendly-error +
// masked-log pipeline as everything else.
const _get   = (/** @type {string} */ path, /** @type {any} */ opts = {}) =>
  _request('GET', path, opts);
const _post  = (/** @type {string} */ path, /** @type {any} */ body, /** @type {any} */ opts = {}) =>
  _request('POST', path, { ...opts, body });
const _put   = (/** @type {string} */ path, /** @type {any} */ body, /** @type {any} */ opts = {}) =>
  _request('PUT', path, { ...opts, body });
const _patch = (/** @type {string} */ path, /** @type {any} */ body, /** @type {any} */ opts = {}) =>
  _request('PATCH', path, { ...opts, body });
const _del   = (/** @type {string} */ path, /** @type {any} */ opts = {}) =>
  _request('DELETE', path, opts);

/** POST /api/auth/login */
export const login = (username, password) =>
  _post('/auth/login', { username, password });

/** POST /api/auth/register */
export const register = (payload) =>
  _post('/auth/register', payload);

// ── Public data endpoints (read-only — no JWT required) ──────────────────────
// Pass auth header if available — backend masks accounts for non-admin
// Pass `fresh=true` to make the server bypass its 30-second cache and
// pull a live broker snapshot. The Refresh button uses it; page mount
// + WebSocket-driven auto-refresh rely on the cached value.
export const fetchHoldings  = ({ fresh = false } = {}) =>
  _get(`/holdings/${fresh ? '?fresh=1' : ''}`, { auth: _hasToken() });
export const fetchPositions = ({ fresh = false } = {}) =>
  _get(`/positions/${fresh ? '?fresh=1' : ''}`, { auth: _hasToken() });
export const fetchFunds     = ({ fresh = false } = {}) =>
  _get(`/funds/${fresh ? '?fresh=1' : ''}`, { auth: _hasToken() });

// ── Protected endpoints (require JWT — order mutations) ───────────────────────
export const fetchOrders    = () => _get('/orders/',    { auth: true });
export const fetchAccounts  = () => _get('/accounts/', { auth: true });

// ── Public endpoints (no JWT needed) ─────────────────────────────────────────
export const fetchMarket = () => _get('/market/');
export const fetchNews   = () => _get('/news/');
export const fetchPost   = () => _get('/config/post');
export const fetchAbout  = () => _get('/config/about');

// ── Agent endpoints (admin) ───────────────────────────────────────────────────
export const fetchAgents      = () => _get('/agents/', { auth: true });

// ── Grammar tokens (admin) ────────────────────────────────────────────────────
// The Agent-grammar catalog — condition / notify / action tokens backing every
// agent. System tokens are toggle-only; custom tokens support full CRUD.
export const fetchGrammarTokens = (grammar) =>
  _get(`/admin/grammar/tokens${grammar ? `?grammar=${encodeURIComponent(grammar)}` : ''}`,
       { auth: true });
export const patchGrammarToken  = (id, payload) =>
  _patch(`/admin/grammar/tokens/${id}`, payload, { auth: true });
export const createGrammarToken = (payload) =>
  _post('/admin/grammar/tokens', payload, { auth: true });
export const deleteGrammarToken = (id) =>
  _del(`/admin/grammar/tokens/${id}`, { auth: true });
export const reloadGrammarRegistry = () => _post('/admin/grammar/reload', {}, { auth: true });

// ── Settings (admin) ────────────────────────────────────────────────────
export const fetchSettings     = () => _get('/admin/settings/', { auth: true });
export const updateSetting     = (key, value) =>
  _patch(`/admin/settings/${encodeURIComponent(key)}`,
         { value: String(value) },
         { auth: true });
export const resetSetting      = (key) =>
  _post(`/admin/settings/${encodeURIComponent(key)}/reset`, {}, { auth: true });
export const fetchAgentEvents = (slug, n = 50) => _get(`/agents/${slug}/events?n=${n}`, { auth: true });
export const fetchRecentAgentEvents = (n = 100) => _get(`/agents/events/recent?n=${n}`, { auth: true });
export const createAgent      = (payload) => _post('/agents/', payload, { auth: true });

// Dry-validate a condition tree against the grammar registry. Returns
// { ok: bool, errors: string[], grammar: 'v2' }.
export const validateAgentCondition = (condTree) =>
  _post('/agents/validate-condition', condTree, { auth: true });

// ── Market simulator control plane (/api/simulator/*) ─────────────────
// Gated by cap_in_<branch>.simulator in backend_config.yaml. Default:
// dev on, prod off. Server returns 400 when the flag is off.
export const fetchSimScenarios    = () => _get('/simulator/scenarios', { auth: true });
export const fetchSimStatus       = () => _get('/simulator/status', { auth: true });
// `opts` may include:
//   seed_mode: 'scripted' | 'live' | 'live+scenario'
//   agent_ids: number[]   (restrict isolation to these agents)
//   positions_every_n_ticks: number | null
//     — positions cadence override; null = fall back to scenario YAML or
//       the DB setting `simulator.positions_every_n_ticks`.
//   market_state_preset: one of pre_open | at_open | mid_session |
//       pre_close | at_close | post_close | expiry_day, or null to use
//       the scenario's YAML value.
//   pct_overrides: array of per-tick decimal pct values (0.05 = 5%).
//       Replaces each pct-typed move's `value` in that tick; null entries
//       keep the scenario YAML default.
//   symbols: array of tradingsymbols to restrict the sim to. After
//       seeding, positions whose symbol isn't in this list are dropped.
//       Empty / null = all positions.
export const startSim             = (scenario, rate_ms = 2000, opts = {}) =>
  _post('/simulator/start',
        { scenario, rate_ms,
          seed_mode:               opts.seed_mode || 'scripted',
          agent_ids:               opts.agent_ids || null,
          positions_every_n_ticks: opts.positions_every_n_ticks ?? null,
          market_state_preset:     opts.market_state_preset || null,
          pct_overrides:           opts.pct_overrides           || null,
          symbols:                 opts.symbols                 || null,
          spread_pct:              opts.spread_pct              ?? null,
          custom_positions:        opts.custom_positions        || null },
        { auth: true });
export const stopSim              = () => _post('/simulator/stop', {}, { auth: true });
export const stepSim              = () => _post('/simulator/step', {}, { auth: true });
export const runSimCycle          = () => _post('/simulator/run-cycle', {}, { auth: true });
export const clearSimArtefacts    = () => _post('/simulator/clear', {}, { auth: true });
export const seedSimLive          = () => _post('/simulator/seed-live', {}, { auth: true });

// Agent-generated orders from the algo_orders table. Returns live + sim
// by default; pass `mode='live'` or `'sim'` to scope. Used by the Order
// tab of the LogPanel on /agents and /admin/simulator.
export const fetchAlgoOrdersRecent = (n = 100, mode = 'all') =>
  _get(`/orders/algo/recent?n=${n}&mode=${mode}`, { auth: true });
// Synthesize-and-start — scenario generated live from the agent's condition
// tree. Preferred over manually picking a scenario when the goal is "test
// this specific agent."
export const startSimForAgent     = (agentId, rate_ms = 2000) =>
  _post(`/simulator/start-for-agent/${agentId}?rate_ms=${rate_ms}`, {}, { auth: true });
export const fetchSimEvents       = (n = 50) => _get(`/simulator/events/recent?limit=${n}`, { auth: true });
export const fetchSimOrders       = (n = 50) => _get(`/simulator/orders/recent?limit=${n}`, { auth: true });
export const fetchSimTicks        = (n = 100) => _get(`/simulator/ticks/recent?limit=${n}`, { auth: true });

export const updateAgent     = (slug, payload) => _put(`/agents/${slug}`, payload, { auth: true });
export const activateAgent   = (slug) => _put(`/agents/${slug}/activate`, undefined, { auth: true });
export const deactivateAgent = (slug) => _put(`/agents/${slug}/deactivate`, undefined, { auth: true });
export const deleteAgent     = (slug) => _del(`/agents/${slug}`, { auth: true });
export const interpretAgent  = (command) => _post('/agents/interpret', { command }, { auth: true });

// ── Order mutations (protected) ───────────────────────────────────────────────
export const placeOrder  = (payload)         => _post('/orders/place', payload, { auth: true });
export const modifyOrder = (orderId, payload) => _put(`/orders/${orderId}`, payload, { auth: true });

// ── Admin endpoints (require admin JWT) ──────────────────────────────────────
export const fetchUsers = () => _get('/admin/users', { auth: true });
export const createUser = (payload) => _post('/admin/users', payload, { auth: true });

export const approveUser = (username) => _put(`/admin/users/${username}/approve`, undefined, { auth: true });
export const rejectUser  = (username) => _put(`/admin/users/${username}/reject`,  undefined, { auth: true });
export const updateUser  = (username, payload) => _put(`/admin/users/${username}`, payload, { auth: true });

export const cancelOrder = (orderId, account, variety = 'regular') => {
  const params = new URLSearchParams({ account, variety });
  return _del(`/orders/${orderId}?${params}`, { auth: true });
};

// ── Charts (admin-guarded) ────────────────────────────────────────────────────

/** GET /api/charts/symbols?mode=… — list symbols with captured ticks. */
export async function fetchChartSymbols(mode) {
  return _get(`/charts/symbols?mode=${encodeURIComponent(mode)}`, { auth: true });
}

/** GET /api/charts/price-history — ticks + AlgoOrder lifecycle markers. */
export async function fetchChartPriceHistory(mode, symbol, since = null, limit = 600) {
  const p = new URLSearchParams({ mode, symbol, limit: String(limit) });
  if (since) p.set('since', since);
  return _get(`/charts/price-history?${p}`, { auth: true });
}

/** GET /api/charts/paper-status — prod paper engine snapshot for /admin/paper. */
export async function fetchPaperStatus() {
  return _get('/charts/paper-status', { auth: true });
}

/** GET /api/quote — single-symbol quote with top-5 depth. Used by
 *  OrderTicket / OrderDepth to render the bid/ask ladder while the
 *  ticket is open. Polls every ~1 s for live depth. */
export async function fetchQuote(exchange, tradingsymbol) {
  const p = new URLSearchParams({ exchange, tradingsymbol });
  return _get(`/quote/?${p}`, { auth: true });
}

/** POST /api/orders/ticket — operator-initiated order from the
 *  reusable <OrderTicket>. Phase 2: only mode='paper' is wired —
 *  routes through the prod paper engine. mode='live' returns 501
 *  until phase 3. mode='draft' is client-side, never reaches here. */
export async function placeTicketOrder(payload) {
  return _post('/orders/ticket', payload, { auth: true });
}

/** GET /api/charts/batch — N charts in one round-trip. Returns
 *  `{mode, charts: [ChartResponse, …]}` in the order of `symbols`. */
export async function fetchChartBatch(mode, symbols, since = null, limit = 600) {
  if (!symbols?.length) return { mode, charts: [] };
  const p = new URLSearchParams({
    mode,
    symbols: symbols.join(','),
    limit: String(limit),
  });
  if (since) p.set('since', since);
  return _get(`/charts/batch?${p}`, { auth: true });
}

// ── Options analytics (admin) ────────────────────────────────────────

/** GET /api/options/analytics — Greeks, theoretical price, payoff curve,
 *  risk metrics for one option position. */
export async function fetchOptionAnalytics(opts = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(opts)) {
    if (v != null && v !== '') p.set(k, String(v));
  }
  return _get(`/options/analytics?${p}`, { auth: true });
}

/** GET /api/options/historical — historical OHLCV bars from Kite. */
export async function fetchOptionHistorical(symbol, days = 30,
                                            interval = 'day',
                                            exchange = 'NFO') {
  const p = new URLSearchParams({ symbol, days: String(days), interval, exchange });
  return _get(`/options/historical?${p}`, { auth: true });
}

// ── Broker accounts (admin CRUD) ─────────────────────────────────────

/** GET /api/admin/brokers — list every broker account (no secrets). */
export const fetchBrokerAccounts = () => _get('/admin/brokers', { auth: true });

/** GET /api/admin/brokers/{account} — single account metadata. */
export const fetchBrokerAccount = (acct) =>
  _get(`/admin/brokers/${encodeURIComponent(acct)}`, { auth: true });

/** POST /api/admin/brokers — create a new account. */
export async function createBrokerAccount(payload) {
  return _post('/admin/brokers', payload, { auth: true });
}

/** PATCH /api/admin/brokers/{account} — partial update. Empty secrets
 *  fields mean "leave unchanged" so the operator can edit one credential
 *  without re-typing the rest. */
export const updateBrokerAccount = (acct, payload) =>
  _patch(`/admin/brokers/${encodeURIComponent(acct)}`, payload, { auth: true });

/** DELETE /api/admin/brokers/{account}. */
export const deleteBrokerAccount = (acct) =>
  _del(`/admin/brokers/${encodeURIComponent(acct)}`, { auth: true });

/** POST /api/admin/brokers/{account}/test — try profile() and report. */
export async function testBrokerAccount(acct) {
  return _post(`/admin/brokers/${encodeURIComponent(acct)}/test`, {}, { auth: true });
}


/** POST /api/options/strategy-analytics — multi-leg aggregate analytics. */
export async function fetchStrategyAnalytics(legs, opts = {}) {
  return _post('/options/strategy-analytics',
    {
      legs: (legs || []).map(l => ({
        symbol:   String(l.symbol || '').trim().toUpperCase(),
        qty:      Number(l.qty),
        avg_cost: l.avg_cost == null || l.avg_cost === '' ? null : Number(l.avg_cost),
        ltp:      l.ltp      == null || l.ltp      === '' ? null : Number(l.ltp),
        iv:       l.iv       == null || l.iv       === '' ? null : Number(l.iv),
      })),
      spot:     opts.spot     ?? null,
      span_pct: opts.span_pct ?? 0.10,
      points:   opts.points   ?? 51,
    },
    { auth: true });
}
