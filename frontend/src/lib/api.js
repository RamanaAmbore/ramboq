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
export const fetchHoldings  = () => _get('/holdings/');
export const fetchPositions = () => _get('/positions/');
export const fetchFunds     = () => _get('/funds/');

// ── Protected endpoints (require JWT — order mutations) ───────────────────────
export const fetchOrders    = () => _get('/orders/',    { auth: true });
export const fetchAccounts  = () => _get('/accounts/', { auth: true });

// ── Public endpoints (no JWT needed) ─────────────────────────────────────────
export const fetchMarket = () => _get('/market/');
export const fetchPost   = () => _get('/config/post');
export const fetchAbout  = () => _get('/config/about');

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
