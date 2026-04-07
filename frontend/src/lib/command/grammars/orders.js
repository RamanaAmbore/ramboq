// Order-entry grammar: buy / sell / cancel / modify.
//
// This file loads the declarative YAML grammar from backend/config/grammars/orders.yaml
// and wires JavaScript-side suggesters and resolvers.
//
// Exports:
//   orderGrammar              — grammar object for CommandBar
//   buildOrderPayload(parsed) — converts parsed command to order REST payload
//   resolveInstrument(args)   — resolves instType+symbol+strike+expiry → Kite instrument
//   chaseConfig(level)        — LOW/MED/HIGH → { band_ticks, retry_seconds }
//   setQuoteLoadedCallback(fn)— register callback for async quote completion

import yamlText from './orders.yaml?raw';
import yaml from 'js-yaml';

import {
  getInstrument, listOptions, listFutures, nearestExpiry, listStrikes,
  findOption, findNearestFuture, findEquity, listUnderlyingsByType,
  listExpiries,
} from '$lib/data/instruments';
import { suggestAccounts } from '$lib/data/accounts';

const GRAMMAR_DOC = /** @type {any} */ (yaml.load(yamlText));
const INST_TYPE_MAP = { CALL: 'CE', PUT: 'PE', FUT: 'FUT', EQ: 'EQ' };

// ---------------------------------------------------------------------------
// Quote cache (for price suggestions)
// ---------------------------------------------------------------------------

const _ltpCache = new Map();
const _pendingLtp = new Set();
let _onQuoteLoaded = null;
export function setQuoteLoadedCallback(fn) { _onQuoteLoaded = fn; }

async function _fetchLtp(exchange, tradingsymbol) {
  const key = `${exchange}:${tradingsymbol}`;
  const cached = _ltpCache.get(key);
  if (cached && Date.now() - cached.at < 30000) return cached;
  if (_pendingLtp.has(key)) return null;
  _pendingLtp.add(key);
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
    if (_onQuoteLoaded) _onQuoteLoaded();
    return entry;
  } catch { return null; }
  finally { _pendingLtp.delete(key); }
}

// ---------------------------------------------------------------------------
// Suggesters
// ---------------------------------------------------------------------------

function symbolSuggest(prefix, ctx) {
  const instType = (ctx && ctx.instType ? String(ctx.instType) : 'EQ').toUpperCase();
  const mapped = INST_TYPE_MAP[instType] || 'EQ';
  return listUnderlyingsByType(mapped, prefix, 20);
}

function strikeSuggest(prefix, ctx) {
  const instType = (ctx && ctx.instType ? String(ctx.instType) : '').toUpperCase();
  const mapped = INST_TYPE_MAP[instType];
  if (mapped !== 'CE' && mapped !== 'PE') return [];
  const underlying = ctx && ctx.symbol;
  if (!underlying) return [];
  const expiry = nearestExpiry(underlying, mapped);
  if (!expiry) return [];
  const strikes = listStrikes(underlying, mapped, expiry);
  if (strikes.length === 0) return [];

  // Fetch quotes for all strikes to check bid/ask availability + spread
  // For now, mark each strike and kick off background fetches
  const labels = strikes.map(k => {
    const opt = findOption(underlying, mapped, k, expiry);
    if (!opt) return String(k);
    const cacheKey = `${opt.e}:${opt.s}`;
    const entry = _ltpCache.get(cacheKey);
    if (!entry) {
      _fetchLtp(opt.e, opt.s); // background fetch
      return String(k);
    }
    const hasBoth = entry.bid && entry.ask && entry.bid > 0 && entry.ask > 0;
    if (!hasBoth) return `${k} (no quotes)`;
    const spread = entry.ask - entry.bid;
    const tick = opt.ts || 0.05;
    const spreadTicks = Math.round(spread / tick);
    const star = spreadTicks > 20 ? ' ***' : spreadTicks > 10 ? ' **' : spreadTicks > 5 ? ' *' : '';
    return `${k} (${entry.ltp.toFixed(2)})${star}`;
  });

  if (!prefix) {
    const mid = Math.floor(labels.length / 2);
    Object.defineProperty(labels, '_focusIndex', { value: mid, enumerable: false });
    return labels;
  }
  return labels.filter(s => s.startsWith(prefix));
}

function expirySuggest(prefix, ctx) {
  if (!ctx || !ctx.symbol) return [];
  const underlying = String(ctx.symbol).toUpperCase();
  const instType = (ctx.instType || 'EQ').toUpperCase();
  const mapped = INST_TYPE_MAP[instType];
  if (mapped === 'EQ') return [];
  if (mapped === 'FUT') {
    return listFutures(underlying).map(r => r.x).filter(Boolean).slice(0, 20);
  }
  return listExpiries(underlying, mapped).slice(0, 20);
}

function qtySuggest(prefix, ctx) {
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
      // Show as: lots ( × lot_size = total)
      // e.g. "1 ( × 50 = 50)", "2 ( × 50 = 100)"
      // Inserted value is just the lots number; bracket is display-only
      const lots = prefix ? [Number(prefix) || 1] : [1, 2, 3, 5, 10];
      return lots.map(n => `${n} ( × ${ls} = ${n * ls})`);
    }
    // Equity: plain share counts
    if (prefix) return [];
    return ['1', '5', '10', '25', '50', '100', '500'];
  } catch {
    // Fallback when instrument can't be resolved yet
    if (prefix) return [];
    return ['1', '5', '10', '25', '50', '100', '500'];
  }
}

function priceSuggest(prefix, ctx) {
  try {
    const inst = resolveInstrument({
      instType: ctx.instType || 'EQ',
      symbol: ctx.symbol,
      strike: ctx.strike,
      expiry: ctx.expiry,
    });
    const entry = _ltpCache.get(`${inst.e}:${inst.s}`);
    if (!entry) {
      _fetchLtp(inst.e, inst.s);
      return [];
    }
    const ltp = entry.ltp;
    const tick = inst.ts || 0.05;
    const orderType = (ctx.orderType || 'LIMIT').toUpperCase();

    if (orderType === 'SL' || orderType === 'SL-M') {
      // Show % trigger prices
      const isBuy = ctx._verb === 'buy';
      const pcts = isBuy ? [5, 10, 20] : [-5, -10, -20];
      return pcts.map(pct => {
        const price = +(ltp * (1 + pct / 100)).toFixed(2);
        const rounded = Math.round(price / tick) * tick;
        return `${rounded.toFixed(2)} (${pct > 0 ? '+' : ''}${pct}% of ${ltp.toFixed(2)})`;
      });
    }

    // LIMIT: show ATM ± 10 ticks centered on LTP
    const atm = Math.round(ltp / tick) * tick;
    const steps = [];
    for (let i = -10; i <= 10; i++) {
      const p = +(atm + i * tick).toFixed(2);
      if (p > 0) steps.push(String(p));
    }
    const atmStr = String(+atm.toFixed(2));
    const focus = steps.indexOf(atmStr);
    if (focus >= 0) Object.defineProperty(steps, '_focusIndex', { value: focus, enumerable: false });
    if (!prefix) return steps;
    return steps.filter(s => s.startsWith(prefix));
  } catch { return []; }
}

function orderIdSuggest(prefix, ctx) {
  const ids = ctx.openOrderIds || [];
  if (!prefix) return ids.slice(0, 20);
  return ids.filter(id => id.startsWith(prefix)).slice(0, 20);
}

const SUGGESTERS = {
  symbol:       symbolSuggest,
  strike:       strikeSuggest,
  account:      (p, _) => suggestAccounts(p, 20),
  qty:          qtySuggest,
  price:        priceSuggest,
  order_id:     orderIdSuggest,
  expiry:       expirySuggest,
  chase_level:  null,
  order_type:   null,
};

// ---------------------------------------------------------------------------
// Grammar wiring (YAML → engine format)
// ---------------------------------------------------------------------------

function _wireRequired(required) {
  if (typeof required !== 'string') return !!required;
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

const _PARSE_MAP = {
  int: Number,
  float: Number,
  upper: (v) => String(v).toUpperCase(),
  str: String,
};

function _wireTokens(tokenSpecs) {
  return (tokenSpecs || []).map(spec => ({
    role: spec.role,
    values: spec.values || undefined,
    suggest: spec.kind ? SUGGESTERS[spec.kind] || undefined : undefined,
    required: _wireRequired(spec.required),
    parse: _PARSE_MAP[spec.parse] || undefined,
    resolve: undefined,
    hint: spec.hint || undefined,
  }));
}

function _wireKwargs(kwargSpecs) {
  if (!kwargSpecs) return undefined;
  const out = {};
  for (const [key, spec] of Object.entries(kwargSpecs)) {
    out[key] = {
      values: spec.values || undefined,
      suggest: spec.kind ? SUGGESTERS[spec.kind] || undefined : undefined,
      parse: _PARSE_MAP[spec.parse] || undefined,
      hint: spec.hint || undefined,
    };
  }
  return out;
}

const _wiredVerbs = {};
for (const [name, def] of Object.entries(GRAMMAR_DOC.verbs)) {
  _wiredVerbs[name] = {
    tokens: _wireTokens(def.tokens),
    kwargs: _wireKwargs(def.kwargs),
  };
}

export const orderGrammar = { verbs: _wiredVerbs };

// ---------------------------------------------------------------------------
// Symbol resolution
// ---------------------------------------------------------------------------

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
    if (expiry) {
      const alt = listFutures(underlying).find(r => r.x === expiry);
      if (alt) return alt;
    }
    const inst = findNearestFuture(underlying);
    if (!inst) throw new Error(`no futures for ${underlying}`);
    return inst;
  }
  if (strike == null) throw new Error(`strike required for ${type}`);
  const exp = expiry || nearestExpiry(underlying, mapped);
  if (!exp) throw new Error(`no ${type} contracts for ${underlying}`);
  const inst = findOption(underlying, mapped, Number(strike), exp);
  if (!inst) throw new Error(`no ${underlying} ${strike} ${type} on ${exp}`);
  return inst;
}

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

// ---------------------------------------------------------------------------
// Chase config
// ---------------------------------------------------------------------------

const CHASE_LEVELS = (GRAMMAR_DOC.chase_levels || {});
export function chaseConfig(level) {
  const key = String(level).toUpperCase();
  const cfg = CHASE_LEVELS[key];
  if (cfg) return { ...cfg, level: key };
  return { band_ticks: 4, retry_seconds: 30, level: 'MED' };
}

// ---------------------------------------------------------------------------
// Build order payload
// ---------------------------------------------------------------------------

export function buildOrderPayload(parsed) {
  const { verb, args, kwargs } = parsed;
  if (verb !== 'buy' && verb !== 'sell') return null;
  const inst = resolveInstrument({
    instType: args.instType || 'EQ',
    symbol: args.symbol,
    strike: args.strike,
    expiry: args.expiry,
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
    chase: args.chase ? chaseConfig(args.chase) : null,
  };
}

/**
 * After a command is fully typed, return a preview string showing the resolved
 * Kite tradingsymbol (e.g. "→ NIFTY25APR0322500CE"). Used by the CommandBar
 * to display a confirmation line.
 */
export function previewSymbol(parsed) {
  try {
    const { args } = parsed;
    const inst = resolveInstrument({
      instType: args.instType || 'EQ',
      symbol: args.symbol,
      strike: args.strike,
      expiry: args.expiry,
    });
    return `→ ${inst.s} (${inst.e})`;
  } catch { return ''; }
}
