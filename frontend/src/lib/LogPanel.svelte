<script>
  import { onMount } from 'svelte';
  import { logTime, parseLogLineTime } from '$lib/stores';
  import { fetchNews } from '$lib/api';

  /** @type {{
   *   heightClass?: string,
   *   cmdHistory?: Array<{status: string, message: string, fields?: Record<string,string>, time: string}>,
   *   orderLog?: Array<any>,
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
    if (worst <= -2000 || worst <= -1.0) return 'log-agent-failed';      // rate-steep
    if (worst <= -500  || worst <= -0.3) return 'log-agent-triggered';   // static-crossing
    return 'log-info';
  }
  function _renderSimLine(entry) {
    const ts = entry.ts ? entry.ts.slice(11, 19) : '';  // HH:MM:SS
    const scen = entry.scenario || '';
    if (entry.kind === 'started')  return `<span class="log-agent-success"><span class="log-ts">[${ts}]</span> ▶ START ${scen} · ${entry.note || ''}</span>`;
    if (entry.kind === 'stopped')  return `<span class="log-info"><span class="log-ts">[${ts}]</span> ■ STOP ${scen} · ${entry.note || ''}</span>`;
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
    return `<span class="${cls}"><span class="log-ts">[${ts}]</span> <span class="px-1 rounded bg-[#fb7185]/15 text-[#fb7185] border border-[#fb7185]/30">SIMULATOR</span> ${head} ${diffs || '(no changes)'}</span>`;
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
      (e.event_type?.startsWith('action_') && /place_order|chase_close/i.test(e.trigger_condition || '')));
  }

  function _cmdEntryHtml(h) {
    const cls = h.status === '✓' ? 'log-agent-success' : h.status === '✗' ? 'log-agent-failed' : 'log-info';
    const chips = h.fields ? Object.entries(h.fields)
      .map(([k, v]) => `<span class="log-chip"><span class="log-chip-key">${k}:</span>${v}</span>`)
      .join(' ') : '';
    return `<span class="${cls}"><span class="log-ts">[${h.time}]</span> ${h.status} ${h.message} ${chips}</span>`;
  }

  function _orderLogHtml() {
    const lines = cmdHistory.map(h => _cmdEntryHtml(h));
    return lines.length ? lines.join('\n') : '<span class="log-debug">No order events.</span>';
  }

  function _terminalHtml() {
    const cmdLines = cmdHistory.map(h => ({ ts: h.time, html: _cmdEntryHtml(h) }));
    const orderLines = filteredOrder().map(e => {
      const t = logTime(e.timestamp);
      return { ts: t, html: `<span class="${orderClass(e.event_type)}"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>` };
    });
    const agentLines = agentLog.map(e => {
      const t = logTime(e.timestamp);
      return { ts: t, html: `<span class="log-agent-default"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>` };
    });
    const all = [...cmdLines, ...orderLines, ...agentLines];
    return all.length ? all.map(x => x.html).join('\n') : '<span class="log-debug">No events.</span>';
  }

  function setTab(id) {
    logTab = id;
    onTabChange(id);
  }
</script>

<div class="flex gap-0.5 mb-2">
  {#each TABS as [id, label]}
    <button onclick={() => setTab(id)}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {logTab === id ? 'border-[#d97706] text-[#fbbf24]' : 'border-transparent text-[#b4c8e6] hover:text-[#fbbf24]'}"
    >{label}</button>
  {/each}
</div>

<pre class="log-panel {heightClass}">{#if logTab === 'order'}{@html _orderLogHtml()}{:else if logTab === 'terminal'}{@html _terminalHtml()}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
  const t = logTime(e.timestamp);
  return `<span class="log-agent-default"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else if logTab === 'simulator'}{#if simLog.length}{@html simLog.map(_renderSimLine).join('\n')}{:else}<span class="log-debug">No simulator ticks. Start a scenario at /admin/simulator to stream price changes here.</span>{/if}{:else if logTab === 'news'}{#if newsLoading && !newsItems.length}<span class="log-debug">Loading headlines…</span>{:else if newsItems.length}{@html newsItems.map(n => {
  const safeTitle = (n.title || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const safeLink  = (n.link || '').replace(/"/g,'&quot;');
  const safeSrc   = (n.source || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const src = safeSrc ? ` <span class="log-chip"><span class="log-chip-key">src:</span>${safeSrc}</span>` : '';
  return `<span class="log-info"><span class="log-ts">[${n.timestamp}]</span> <a href="${safeLink}" target="_blank" rel="noopener">${safeTitle}</a>${src}</span>`;
}).join('\n')}{:else}<span class="log-debug">No headlines.</span>{/if}{:else}{#if systemLog.length}{@html systemLog.map(l => {
  const t = parseLogLineTime(l);
  const rest = t ? stripTs(l) : l;
  return `<span class="${sysClass(l)}">${t ? `<span class="log-ts">[${t}]</span> ` : ''}${rest}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>
