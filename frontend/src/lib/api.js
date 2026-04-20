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
export const fetchHoldings  = () => _get('/holdings/', { auth: _hasToken() });
export const fetchPositions = () => _get('/positions/', { auth: _hasToken() });
export const fetchFunds     = () => _get('/funds/', { auth: _hasToken() });

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
//   holdings_every_n_ticks / positions_every_n_ticks: number | null
//     — override per-section tick cadence; null = fall back to scenario YAML
//       or module default.
export const startSim             = (scenario, rate_ms = 2000, opts = {}) =>
  _post('/simulator/start',
        { scenario, rate_ms,
          seed_mode:               opts.seed_mode || 'scripted',
          agent_ids:               opts.agent_ids || null,
          holdings_every_n_ticks:  opts.holdings_every_n_ticks  ?? null,
          positions_every_n_ticks: opts.positions_every_n_ticks ?? null },
        { auth: true });
export const stopSim              = () => _post('/simulator/stop', {}, { auth: true });
export const stepSim              = () => _post('/simulator/step', {}, { auth: true });
export const runSimCycle          = () => _post('/simulator/run-cycle', {}, { auth: true });
export const clearSimArtefacts    = () => _post('/simulator/clear', {}, { auth: true });
export const seedSimLive          = () => _post('/simulator/seed-live', {}, { auth: true });
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
