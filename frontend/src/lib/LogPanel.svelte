<script>
  import { onMount } from 'svelte';
  import { parseLogLineTime } from '$lib/stores';
  import { fetchNews } from '$lib/api';

  /** @type {{
   *   heightClass?: string,
   *   cmdHistory?: Array<{status: string, message: string, fields?: Record<string,string>, time: string}>,
   *   orderLog?: Array<any>,
   *   orderRows?: Array<{id:number, account:string, symbol:string, transaction_type:string,
   *                       quantity:number, initial_price:number|null, status:string,
   *                       engine:string, mode:string, detail:string|null, created_at:string}>,
   *   agentLog?: Array<any>,
   *   systemLog?: string[],
   *   simLog?: Array<any>,
   *   initialTab?: string,
   *   onTabChange?: (tab: string) => void,
   * }} */
  let {
    heightClass = 'flex-1 min-h-0',
    cmdHistory = [],
    orderLog = [],
    orderRows = [],
    agentLog = [],
    systemLog = [],
    simLog = [],
    initialTab = 'order',
    onTabChange = () => {},
  } = $props();

  let logTab = $state(initialTab);
  let newsItems = $state(/** @type {Array<{title:string,link:string,source:string,timestamp:string}>} */ ([]));
  let newsLoading = $state(false);
  let newsInterval;

  async function loadNews() {
    newsLoading = true;
    try {
      const data = await fetchNews();
      newsItems = data?.items || [];
    } catch (_) { /* ignore */ }
    newsLoading = false;
  }

  onMount(() => {
    loadNews();
    newsInterval = setInterval(loadNews, 10 * 60 * 1000);
    return () => { if (newsInterval) clearInterval(newsInterval); };
  });

  const TABS = [
    ['order',     'Order'],
    ['terminal',  'Terminal'],
    ['agent',     'Agent'],
    ['simulator', 'Simulator'],
    ['system',    'System'],
    ['news',      'News'],
  ];

  // ── Shared helpers so every tab renders the same way ─────────────────
  // All log rows show timestamps as HH:MM:SS (8 chars). logTime() in
  // stores.js returns the long dual-zone string used by emails / page
  // headers; that's too verbose for a monospace log row. _shortTime()
  // slices out the time portion whether the input is already short
  // ("18:44:42"), a full ISO string, or a Date.
  function _shortTime(input) {
    if (!input) return '';
    const s = typeof input === 'string' ? input : input.toISOString?.() || '';
    // ISO: 2026-04-20T18:44:42(...)  →  slice(11, 19)
    if (s.length >= 19 && s[10] === 'T') return s.slice(11, 19);
    // Already HH:MM:SS or similar short form
    const m = s.match(/\d{2}:\d{2}:\d{2}/);
    return m ? m[0] : s;
  }

  // Shared SIM / LIVE pills — amber for simulated (matches the page-top
  // "SIMULATOR ACTIVE" banner), emerald for live. Replaces the pink
  // badge that was making the Order log look like an error list.
  const SIM_PILL  = '<span class="mode-pill mode-pill-sim">SIM</span>';
  const LIVE_PILL = '<span class="mode-pill mode-pill-live">LIVE</span>';

  // ── Simulator-tab rendering ──────────────────────────────────────────
  // A sim tick entry from /api/simulator/ticks/recent looks like:
  //   { ts, tick_index, scenario, kind: 'tick'|'started'|'stopped',
  //     moves, changes: [{section, account, symbol, col, prev, next, delta}],
  //     note }
  // Rendered as one line per tick with a color based on the magnitude of
  // the worst change (red = steep rate, yellow = static crossing, neutral).
  function _fmtVal(v) {
    if (v === null || v === undefined) return '–';
    if (typeof v === 'number') {
      if (Math.abs(v) >= 1000) return '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: 0 });
      return (Math.round(v * 100) / 100).toString();
    }
    return String(v);
  }
  function _classifySimLine(entry) {
    if (entry.kind !== 'tick') return 'log-info';
    const worst = (entry.changes || []).reduce((acc, c) => {
      if (typeof c.delta !== 'number') return acc;
      return (acc === null || c.delta < acc) ? c.delta : acc;
    }, null);
    if (worst === null) return 'log-info';
    // Keep colours calm: amber-ish for meaningful price moves, neutral
    // otherwise. No red/pink — that class is reserved for actual errors.
    if (worst <= -500 || worst <= -0.3) return 'log-agent-triggered';
    return 'log-info';
  }
  function _renderSimLine(entry) {
    const ts = _shortTime(entry.ts);
    const scen = entry.scenario || '';
    if (entry.kind === 'started')  return `<span class="log-agent-success"><span class="log-ts">${ts}</span> ▶ START ${scen} · ${entry.note || ''}</span>`;
    if (entry.kind === 'stopped')  return `<span class="log-info"><span class="log-ts">${ts}</span> ■ STOP ${scen} · ${entry.note || ''}</span>`;
    if (entry.kind === 'order') {
      const o = entry.order || {};
      // BUY = green, SELL = neutral (not red — a sell isn't an error).
      const sideCls = o.side === 'BUY' ? 'log-agent-success' : 'log-info';
      const price   = (o.price != null)
        ? '@₹' + Number(o.price).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})
        : '';
      return `<span class="${sideCls}"><span class="log-ts">${ts}</span> ${SIM_PILL}◆ ${o.side || '?'} ${o.qty ?? '?'} ${o.symbol || '?'} ${price} · ${o.account || '?'} · ${o.agent || ''} ${o.action || ''}</span>`;
    }
    const cls = _classifySimLine(entry);
    const diffs = (entry.changes || []).map(c => {
      // For price moves, `c.symbol` carries the tradingsymbol and `c.col` is
      // always last_price — show the symbol so the operator sees which
      // instrument moved. For margin patches `c.symbol` is empty and `c.col`
      // names the field being set.
      const leaf  = c.symbol ? c.symbol : c.col;
      const field = `${c.section}.${c.account}.${leaf}`;
      const arrow = `${_fmtVal(c.prev)}→${_fmtVal(c.next)}`;
      const delta = (typeof c.delta === 'number') ? ` (Δ ${_fmtVal(c.delta)})` : '';
      return `<span class="log-chip"><span class="log-chip-key">${field}:</span>${arrow}${delta}</span>`;
    }).join(' ');
    const head = `tick ${entry.tick_index} · ${scen}`;
    return `<span class="${cls}"><span class="log-ts">${ts}</span> ${SIM_PILL}${head} ${diffs || '(no changes)'}</span>`;
  }

  const ORDER_TYPES = new Set(['order_placed','order_cancelled','order_rejected','order_filled']);

  function orderClass(t) {
    return t?.includes('success') ? 'log-agent-success'
         : t?.includes('fail')    ? 'log-agent-failed'
         : 'log-agent-triggered';
  }

  function stripTs(l) {
    return l.replace(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*-?\s*/, '');
  }

  function sysClass(l) {
    return l.includes('ERROR') ? 'log-error' : l.includes('WARNING') ? 'log-warning' : 'log-info';
  }

  function filteredOrder() {
    return orderLog.filter(e =>
      ORDER_TYPES.has(e.event_type) ||
      (e.event_type?.startsWith('action_') && /place_order|close_position|chase_close/i.test(e.trigger_condition || '')));
  }

  function _cmdEntryHtml(h) {
    const cls = h.status === '✓' ? 'log-agent-success' : h.status === '✗' ? 'log-agent-failed' : 'log-info';
    const chips = h.fields ? Object.entries(h.fields)
      .map(([k, v]) => `<span class="log-chip"><span class="log-chip-key">${k}:</span>${v}</span>`)
      .join(' ') : '';
    return `<span class="${cls}"><span class="log-ts">${h.time}</span> ${h.status} ${h.message} ${chips}</span>`;
  }

  // Render one AlgoOrder row (mode=live or sim) for the Order tab. Keeps
  // order details — side, qty, symbol, price, account — on one line so
  // operators can scan placements the same way they'd read a broker blotter.
  function _orderRowHtml(o) {
    const t    = _shortTime(o.created_at);
    const tag  = o.mode === 'sim' ? SIM_PILL : LIVE_PILL;
    // Colour by terminal state first, then by side. FILLED = green,
    // UNFILLED = red, OPEN (still chasing) = amber, everything else
    // falls back to the old side-based cue.
    const status = (o.status || '').toUpperCase();
    let rowCls = 'log-info';
    if      (status === 'FILLED')   rowCls = 'log-agent-success';
    else if (status === 'UNFILLED') rowCls = 'log-agent-failed';
    else if (status === 'OPEN')     rowCls = 'log-agent-alert';
    else if (o.transaction_type === 'BUY') rowCls = 'log-agent-success';
    const fillPrice = (o.fill_price != null)
      ? '@₹' + Number(o.fill_price).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})
      : null;
    const initPrice = (o.initial_price != null)
      ? '@₹' + Number(o.initial_price).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})
      : '';
    // Prefer fill_price once the chase landed; otherwise show the initial
    // limit price the operator submitted.
    const price     = fillPrice || initPrice;
    const statusChip  = o.status   ? ` <span class="log-chip"><span class="log-chip-key">status:</span>${o.status}</span>` : '';
    const attemptChip = (o.attempts != null && o.attempts > 0)
      ? ` <span class="log-chip"><span class="log-chip-key">chase:</span>#${o.attempts}</span>`
      : '';
    const engine = o.engine ? ` <span class="log-chip"><span class="log-chip-key">engine:</span>${o.engine}</span>` : '';
    return `<span class="${rowCls}"><span class="log-ts">${t}</span> ${tag}◆ ${o.transaction_type} ${o.quantity} ${o.symbol} ${price} · ${o.account}${statusChip}${attemptChip}${engine}</span>`;
  }

  function _orderLogHtml() {
    // Prefer structured AlgoOrder rows when provided; fall back to the
    // terminal-command history so the /console page still works.
    if (orderRows && orderRows.length) {
      return orderRows.map(_orderRowHtml).join('\n');
    }
    const lines = cmdHistory.map(h => _cmdEntryHtml(h));
    return lines.length ? lines.join('\n') : '<span class="log-debug">No order events.</span>';
  }

  function _terminalHtml() {
    const cmdLines = cmdHistory.map(h => ({ ts: h.time, html: _cmdEntryHtml(h) }));
    const orderLines = filteredOrder().map(e => {
      const t = _shortTime(e.timestamp);
      return { ts: t, html: `<span class="${orderClass(e.event_type)}"><span class="log-ts">${t}</span> ${e.event_type||''} ${e.trigger_condition||''}</span>` };
    });
    const agentLines = agentLog.map(e => {
      const t = _shortTime(e.timestamp);
      return { ts: t, html: `<span class="log-agent-default"><span class="log-ts">${t}</span> ${e.event_type||''} ${e.trigger_condition||''}</span>` };
    });
    const all = [...cmdLines, ...orderLines, ...agentLines];
    return all.length ? all.map(x => x.html).join('\n') : '<span class="log-debug">No events.</span>';
  }

  function setTab(id) {
    logTab = id;
    onTabChange(id);
  }
</script>

<div class="flex items-stretch mb-2 log-tab-row">
  <!-- "log" label rotated 90°. Two-layer split so the flex parent
       (wrap) reserves the column width and the child carries the
       rotation via writing-mode: vertical-lr (text flows top-to-bottom
       naturally, no transform needed). -->
  <span class="log-section-wrap" aria-hidden="true">
    <span class="log-section-text">Log</span>
  </span>
  {#each TABS as [id, label]}
    <button onclick={() => setTab(id)}
      class="log-tab-btn border-b-2 transition-colors
        {logTab === id ? 'border-[#d97706] text-[#fbbf24]' : 'border-transparent text-[#b4c8e6] hover:text-[#fbbf24]'}"
    >{label}</button>
  {/each}
</div>

<pre class="log-panel {heightClass}">{#if logTab === 'order'}{@html _orderLogHtml()}{:else if logTab === 'terminal'}{@html _terminalHtml()}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
  const t = _shortTime(e.timestamp);
  return `<span class="log-agent-default"><span class="log-ts">${t}</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else if logTab === 'simulator'}{#if simLog.length}{@html simLog.map(_renderSimLine).join('\n')}{:else}<span class="log-debug">No simulator ticks. Start a scenario at /admin/simulator to stream price changes here.</span>{/if}{:else if logTab === 'news'}{#if newsLoading && !newsItems.length}<span class="log-debug">Loading headlines…</span>{:else if newsItems.length}{@html newsItems.map(n => {
  const safeTitle = (n.title || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const safeLink  = (n.link || '').replace(/"/g,'&quot;');
  const safeSrc   = (n.source || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const src = safeSrc ? ` <span class="log-chip"><span class="log-chip-key">src:</span>${safeSrc}</span>` : '';
  return `<span class="log-info"><span class="log-ts">${_shortTime(n.timestamp)}</span> <a href="${safeLink}" target="_blank" rel="noopener">${safeTitle}</a>${src}</span>`;
}).join('\n')}{:else}<span class="log-debug">No headlines.</span>{/if}{:else}{#if systemLog.length}{@html systemLog.map(l => {
  const t = parseLogLineTime(l);
  const rest = t ? stripTs(l) : l;
  return `<span class="${sysClass(l)}">${t ? `<span class="log-ts">${t}</span> ` : ''}${rest}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>

<style>
  /* Tab row — another +30% on the previous 0.48rem → 0.62rem. Padding
     scaled proportionally. Still no inter-tab gap so mobile fit holds. */
  .log-tab-row { gap: 0; }
  :global(.log-tab-btn) {
    font-size: 0.62rem;
    font-weight: 600;
    padding: 0.18rem 0.44rem;
    white-space: nowrap;
    letter-spacing: 0.02em;
    font-family: ui-monospace, monospace;
  }

  /* Vertical "log" label — lowercase on a faint amber background so
     it reads as a quiet section stamp. Two-layer split (wrap + text)
     keeps flex layout and writing-mode from conflicting. */
  .log-section-wrap {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 0.9rem;
    padding: 0.1rem 0.2rem;
    margin-right: 0.15rem;
    background: rgba(251,191,36,0.12);
    border-right: 1px solid rgba(251,191,36,0.4);
    border-radius: 3px 0 0 3px;
    align-self: stretch;
  }
  .log-section-text {
    writing-mode: vertical-lr;
    transform: rotate(180deg);
    font-family: ui-monospace, monospace;
    font-size: 0.5rem;
    font-weight: 700;
    line-height: 1;
    color: #fbbf24;
    text-transform: none;
    letter-spacing: 0.05em;
    user-select: none;
  }

  /* Mode pills — amber SIM / emerald LIVE. Consistent across Simulator
     and Order tabs; replaces the prior pink-on-pink SIM styling that
     dominated the Order log. */
  :global(.mode-pill) {
    display: inline-block;
    padding: 0 0.3rem;
    margin-right: 0.25rem;
    font-family: ui-monospace, monospace;
    font-size: 0.5rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    border-radius: 2px;
    border: 1px solid;
    vertical-align: baseline;
  }
  :global(.mode-pill-sim) {
    background: rgba(251,191,36,0.14);
    color: #fbbf24;
    border-color: rgba(251,191,36,0.45);
  }
  :global(.mode-pill-live) {
    background: rgba(16,185,129,0.14);
    color: #6ee7b7;
    border-color: rgba(16,185,129,0.45);
  }
</style>
