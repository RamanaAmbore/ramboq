// Order-entry grammar loader.
//
// Reads the language-agnostic grammar definition from orders.yaml (shared with
// the Python backend) and wires up the JS-side suggester hooks referenced by
// `kind` (symbol/account/qty/price/order_id/chase_level/expiry).
//
// Exports:
//   orderGrammar — engine-compatible grammar object
//   chaseConfig(level) — maps chase level 1-10 to {band_ticks, retry_seconds}
//   buildOrderPayload(parsed) — converts parsed command to order REST payload
//   resolveSymbol(raw, ctx) — symbol lookup (used during payload build)

import yaml from 'js-yaml';
import grammarYaml from './orders.yaml?raw';

import {
  getInstrument, listOptions, listFutures, nearestExpiry, listStrikes,
  findOption, findNearestFuture, findEquity, listUnderlyingsByType,
} from '$lib/data/instruments';
import { suggestAccounts } from '$lib/data/accounts';

// Map grammar's instType → instruments cache type codes
const INST_TYPE_MAP = { CALL: 'CE', PUT: 'PE', FUT: 'FUT', EQ: 'EQ' };

// --- Symbol resolution (separate instType/symbol/strike tokens) ---

/**
 * Resolve the full Kite instrument from the grammar's three components:
 *   instType: EQ | CALL | PUT | FUT
 *   symbol:   underlying name (RELIANCE, NIFTY, …)
 *   strike:   number (CALL/PUT only; ignored otherwise)
 *   expiry:   optional YYYY-MM-DD override (CALL/PUT/FUT)
 *
 * Throws if no match or ambiguous.
 */
export function resolveInstrument(args = /** @type {any} */ ({})) {
  const { instType, symbol, strike, expiry } = args;
  if (!symbol) throw new Error('symbol required');
  const underlying = String(symbol).toUpperCase();
  const type = String(instType || 'EQ').toUpperCase();
  const mapped = INST_TYPE_MAP[type];
  if (!mapped) throw new Error(`unknown instType: ${instType}`);

  if (mapped === 'EQ') {
    const eq = findEquity(underlying);
    if (!eq) throw new Error(`no equity instrument: ${underlying}`);
    return eq;
  }
  if (mapped === 'FUT') {
    const inst = findNearestFuture(underlying);
    if (!inst) throw new Error(`no futures for ${underlying}`);
    if (expiry) {
      const alt = listFutures(underlying).find(r => r.x === expiry);
      if (alt) return alt;
    }
    return inst;
  }
  // CE / PE
  if (strike == null) throw new Error(`strike required for ${type}`);
  const exp = expiry || nearestExpiry(underlying, mapped);
  if (!exp) throw new Error(`no ${type} contracts for ${underlying}`);
  const inst = findOption(underlying, mapped, Number(strike), exp);
  if (!inst) throw new Error(`no ${underlying} ${strike} ${type} on ${exp}`);
  return inst;
}

// Legacy alias kept for compatibility; now just delegates.
export function resolveSymbol(raw, ctx = {}) {
  const direct = getInstrument(raw);
  if (direct) return direct;
  return resolveInstrument({
    instType: ctx.instType,
    symbol: raw,
    strike: ctx.strike,
    expiry: ctx.expiry,
  });
}

// --- Suggesters, keyed by `kind` from the YAML spec ---

function symbolSuggest(prefix, ctx) {
  // Filter by instType if present (CALL/PUT/FUT/EQ); default EQ
  const instType = (ctx && ctx.instType ? String(ctx.instType) : 'EQ').toUpperCase();
  const mapped = INST_TYPE_MAP[instType] || 'EQ';
  // When mapped = EQ/CE/PE/FUT → show underlyings that have that class
  return listUnderlyingsByType(mapped, prefix, 20);
}

function strikeSuggest(prefix, ctx) {
  const instType = (ctx && ctx.instType ? String(ctx.instType) : '').toUpperCase();
  const mapped = INST_TYPE_MAP[instType];
  if (mapped !== 'CE' && mapped !== 'PE') return [];
  const underlying = ctx && ctx.symbol;
  if (!underlying) return [];
  const expiry = (ctx && ctx.expiry) || nearestExpiry(underlying, mapped);
  if (!expiry) return [];
  const strikes = listStrikes(underlying, mapped, expiry).map(String);
  if (!prefix) {
    // Return full strike ladder; consumer auto-scrolls to ATM (nearest to spot).
    // findOption(..., strike, expiry).last_price gives us spot roughly via instrument
    // map, but we don't have spot price in the frontend cache. Use middle of the
    // strike ladder as a proxy — Kite's strike lists are centered around spot.
    const mid = Math.floor(strikes.length / 2);
    // Attach a focus hint via non-enumerable property so the array prints as strings only
    Object.defineProperty(strikes, '_focusIndex', { value: mid, enumerable: false });
    return strikes;
  }
  return strikes.filter(s => s.startsWith(prefix));
}

function qtySuggest(prefix, ctx) {
  // Resolve instrument so we can pre-multiply by lot size for F&O.
  try {
    const inst = resolveInstrument({
      instType: ctx.instType || 'EQ',
      symbol: ctx.symbol,
      strike: ctx.strike,
      expiry: ctx.expiry,
    });
    const ls = inst.ls || 1;
    const isFO = inst.t === 'CE' || inst.t === 'PE' || inst.t === 'FUT';
    if (isFO && ls > 1) {
      // Suggest N lots → N*ls shares, displayed as "500 (5 lots × 100)"
      // The first token (number) is what gets inserted; the bracket is a label.
      const lots = prefix ? [Number(prefix) || 1] : [1, 2, 3, 5, 10];
      return lots.map(n => `${n * ls} (${n} lot${n > 1 ? 's' : ''} × ${ls})`);
    }
    // Equity: suggest plain share counts
    if (prefix) return [];
    return ['1', '5', '10', '25', '50', '100', '500'];
  } catch {
    if (prefix) return [];
    return ['1','2','5','10','100'];
  }
}

function expirySuggest(prefix, ctx) {
  if (!ctx || !ctx.symbol) return [];
  const underlying = String(ctx.symbol).toUpperCase();
  const mapped = INST_TYPE_MAP[(ctx.instType || 'EQ').toUpperCase()];
  if (mapped === 'FUT') {
    return listFutures(underlying).map(r => r.x).filter(Boolean).slice(0, 20);
  }
  if (mapped !== 'CE' && mapped !== 'PE') return [];
  const rows = listOptions(underlying, mapped);
  const set = new Set();
  for (const r of rows) if (r.x) set.add(r.x);
  return Array.from(set).sort().slice(0, 20);
}

function orderIdSuggest(prefix, ctx) {
  const ids = ctx.openOrderIds || [];
  if (!prefix) return ids.slice(0, 20);
  return ids.filter(id => id.startsWith(prefix)).slice(0, 20);
}

// In-memory cache of recent LTPs keyed by `${exchange}:${tradingsymbol}`
const _ltpCache = new Map();

async function _fetchLtp(exchange, tradingsymbol) {
  const key = `${exchange}:${tradingsymbol}`;
  const cached = _ltpCache.get(key);
  if (cached && Date.now() - cached.at < 30000) return cached; // 30s cache
  try {
    const { authStore } = await import('$lib/stores');
    const token = authStore.getToken();
    const res = await fetch(`/api/quote/?exchange=${encodeURIComponent(exchange)}&tradingsymbol=${encodeURIComponent(tradingsymbol)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return null;
    const data = await res.json();
    const entry = { ltp: data.ltp, bid: data.bid, ask: data.ask, at: Date.now() };
    _ltpCache.set(key, entry);
    return entry;
  } catch { return null; }
}

function priceSuggest(prefix, ctx) {
  // Resolve instrument from ctx to get tick_size + exchange; then look up LTP
  try {
    const inst = resolveInstrument({
      instType: ctx.instType || 'EQ',
      symbol: ctx.symbol,
      strike: ctx.strike,
      expiry: ctx.expiry,
    });
    const entry = _ltpCache.get(`${inst.e}:${inst.s}`);
    if (!entry) {
      // Kick off async fetch; next keystroke will pick it up
      _fetchLtp(inst.e, inst.s);
      return [];
    }
    const tick = inst.ts || 0.05;
    // Round LTP to nearest tick
    const atm = Math.round(entry.ltp / tick) * tick;
    // Build ladder: ATM ± 10 ticks, centered on ATM
    const steps = [];
    for (let i = -10; i <= 10; i++) {
      const p = +(atm + i * tick).toFixed(2);
      if (p > 0) steps.push(String(p));
    }
    // Focus index = ATM (the midpoint)
    const atmStr = String(+atm.toFixed(2));
    const focus = steps.indexOf(atmStr);
    if (focus >= 0) Object.defineProperty(steps, '_focusIndex', { value: focus, enumerable: false });
    if (!prefix) return steps;
    return steps.filter(s => s.startsWith(prefix));
  } catch { return []; }
}

const SUGGESTERS = {
  symbol:       symbolSuggest,
  strike:       strikeSuggest,
  account:      (p, _) => suggestAccounts(p, 20),
  qty:          qtySuggest,
  price:        priceSuggest,
  order_id:     orderIdSuggest,
  expiry:       expirySuggest,
  chase_level:  null,      // uses static values from YAML
  order_type:   null,
};

const PARSERS = {
  int:   (v) => { const n = parseInt(v, 10); if (Number.isNaN(n)) throw new Error(`int: ${v}`); return n; },
  float: (v) => { const n = parseFloat(v);   if (Number.isNaN(n)) throw new Error(`float: ${v}`); return n; },
  upper: (v) => String(v).toUpperCase(),
  str:   (v) => String(v),
};

// --- Convert declarative YAML → engine grammar ---

function _wireRequired(required) {
  if (typeof required !== 'string') return !!required;
  // Syntax: "if:<name>==<VALUE>" | "if:<name>!=<VALUE>" | "if:<name>==<V1>|<V2>"
  const m = required.match(/^if:([a-zA-Z_]+)(==|!=)(.+)$/);
  if (!m) return false;
  const [, name, op, valuesRaw] = m;
  const wanted = valuesRaw.split('|').map(v => v.toUpperCase());
  return (ctx) => {
    const actual = (ctx[name] || '').toString().toUpperCase();
    const inList = wanted.includes(actual);
    return op === '==' ? inList : !inList;
  };
}

function _wireSpec(spec) {
  const out = {};
  if (spec.role) out.role = spec.role;
  if (spec.hint) out.hint = spec.hint;
  if (spec.required !== undefined) out.required = _wireRequired(spec.required);
  if (spec.parse) out.parse = PARSERS[spec.parse] || PARSERS.str;
  if (spec.values) {
    out.values = spec.values.map(String);
  } else if (spec.kind && SUGGESTERS[spec.kind]) {
    out.suggest = SUGGESTERS[spec.kind];
  } else if (spec.kind === 'chase_level') {
    out.values = Array.from({ length: 10 }, (_, i) => String(i + 1));
  } else if (spec.kind === 'order_type') {
    out.values = ['MARKET', 'LIMIT', 'SL', 'SL-M'];
  }
  return out;
}

function _buildGrammar(yamlText) {
  const doc = /** @type {any} */ (yaml.load(yamlText));
  const verbs = {};
  for (const [name, def] of Object.entries(doc.verbs || {})) {
    const d = /** @type {any} */ (def);
    const tokens = (d.tokens || []).map(_wireSpec);
    const kwargs = {};
    for (const [k, v] of Object.entries(d.kwargs || {})) {
      kwargs[k] = _wireSpec(v);
    }
    verbs[name] = { tokens, kwargs };
  }
  return {
    verbs,
    chaseLevels: doc.chase_levels || {},
  };
}

const _parsed = _buildGrammar(grammarYaml);
export const orderGrammar = { verbs: _parsed.verbs };
const _CHASE_LEVELS = _parsed.chaseLevels;

// --- Chase level → engine config ---

export function chaseConfig(level) {
  const n = Math.max(1, Math.min(10, Number(level) || 0));
  const cfg = _CHASE_LEVELS[String(n)];
  if (cfg) return { ...cfg, level: n };
  // Fallback linear mapping
  return { band_ticks: Math.max(1, 11 - n), retry_seconds: Math.max(6, 60 - (n - 1) * 6), level: n };
}

// --- Build order payload from parsed command ---

export function buildOrderPayload(parsed) {
  const { verb, args, kwargs } = parsed;
  if (verb !== 'buy' && verb !== 'sell') return null;
  const inst = resolveInstrument({
    instType: args.instType || 'EQ',
    symbol: args.symbol,
    strike: args.strike,
    expiry: kwargs.expiry,
  });
  const product = kwargs.product
    || (inst.t === 'EQ' ? 'CNC' : (inst.t === 'FUT' || inst.t === 'CE' || inst.t === 'PE') ? 'NRML' : 'MIS');
  return {
    account: args.account,
    tradingsymbol: inst.s,
    exchange: inst.e,
    quantity: args.qty,
    transaction_type: verb.toUpperCase(),
    order_type: args.orderType.toUpperCase(),
    price: args.price || 0,
    product,
    variety: 'regular',
    validity: 'DAY',
    chase: kwargs.chase ? chaseConfig(kwargs.chase) : null,
  };
}
