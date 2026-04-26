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

/** Handle 401 — clear token and redirect to signin. */
function _handle401() {
  authStore.logout();
  if (typeof window !== 'undefined') window.location.href = '/signin';
}

/** POST /api/auth/login */
export async function login(username, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || 'Login failed');
  }
  return res.json();
}

/** POST /api/auth/register */
export async function register(payload) {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || 'Registration failed');
  }
  return res.json();
}

async function _get(path, { auth = false } = {}) {
  const headers = auth ? _authHeaders() : {};
  const res = await fetch(`${BASE}${path}`, { headers });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  return res.json();
}

async function _post(path, payload, { auth = false } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(auth ? _authHeaders() : {}) },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `POST ${path} failed: ${res.status}`);
  }
  return res.json();
}

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
export const patchGrammarToken = async (id, payload) => {
  const res = await fetch(`${BASE}/admin/grammar/tokens/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
};
export const createGrammarToken = async (payload) => {
  const res = await fetch(`${BASE}/admin/grammar/tokens`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
};
export const deleteGrammarToken = async (id) => {
  const res = await fetch(`${BASE}/admin/grammar/tokens/${id}`, {
    method: 'DELETE', headers: _authHeaders(),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok && res.status !== 204) {
    const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed');
  }
};
export const reloadGrammarRegistry = () => _post('/admin/grammar/reload', {}, { auth: true });

// ── Settings (admin) ────────────────────────────────────────────────────
export const fetchSettings     = () => _get('/admin/settings/', { auth: true });
export const updateSetting     = async (key, value) => {
  const res = await fetch(`${BASE}/admin/settings/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify({ value: String(value) }),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
};
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

export async function updateAgent(slug, payload) {
  const res = await fetch(`${BASE}/agents/${slug}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function activateAgent(slug) {
  const res = await fetch(`${BASE}/agents/${slug}/activate`, { method: 'PUT', headers: _authHeaders() });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function deactivateAgent(slug) {
  const res = await fetch(`${BASE}/agents/${slug}/deactivate`, { method: 'PUT', headers: _authHeaders() });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function deleteAgent(slug) {
  const res = await fetch(`${BASE}/agents/${slug}`, { method: 'DELETE', headers: _authHeaders() });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function interpretAgent(command) {
  return _post('/agents/interpret', { command }, { auth: true });
}

// ── Order mutations (protected) ───────────────────────────────────────────────
export async function placeOrder(payload) {
  return _post('/orders/place', payload, { auth: true });
}

export async function modifyOrder(orderId, payload) {
  const res = await fetch(`${BASE}/orders/${orderId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Modify order failed: ${res.status}`);
  }
  return res.json();
}

// ── Admin endpoints (require admin JWT) ──────────────────────────────────────
export const fetchUsers = () => _get('/admin/users', { auth: true });
export const createUser = (payload) => _post('/admin/users', payload, { auth: true });

export async function approveUser(username) {
  const res = await fetch(`${BASE}/admin/users/${username}/approve`, {
    method: 'PUT', headers: _authHeaders(),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function rejectUser(username) {
  const res = await fetch(`${BASE}/admin/users/${username}/reject`, {
    method: 'PUT', headers: _authHeaders(),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function updateUser(username, payload) {
  const res = await fetch(`${BASE}/admin/users/${username}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
  return res.json();
}

export async function cancelOrder(orderId, account, variety = 'regular') {
  const params = new URLSearchParams({ account, variety });
  const res = await fetch(`${BASE}/orders/${orderId}?${params}`, {
    method: 'DELETE',
    headers: _authHeaders(),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Cancel order failed: ${res.status}`);
  }
  return res.json();
}

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
export async function updateBrokerAccount(acct, payload) {
  const res = await fetch(`${BASE}/admin/brokers/${encodeURIComponent(acct)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ..._authHeaders() },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(e.detail || `Update failed: ${res.status}`);
  }
  return res.json();
}

/** DELETE /api/admin/brokers/{account}. */
export async function deleteBrokerAccount(acct) {
  const res = await fetch(`${BASE}/admin/brokers/${encodeURIComponent(acct)}`, {
    method: 'DELETE',
    headers: _authHeaders(),
  });
  if (res.status === 401) { _handle401(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(e.detail || `Delete failed: ${res.status}`);
  }
  return res.json();
}

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
