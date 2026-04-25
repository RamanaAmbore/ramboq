<script>
  // Compact SVG line chart for price history during sim / paper / live.
  // Polls /api/charts/price-history and renders LTP as a line with order
  // event markers (placed / filled / unfilled). No chart library — the
  // chart panel is small enough that hand-rolled SVG is simpler and ships
  // zero JS bytes beyond what's already on the page.

  import { onDestroy, onMount } from 'svelte';
  import { fetchChartPriceHistory } from '$lib/api';

  let {
    /** @type {'sim'|'paper'|'live'} */ mode,
    /** @type {string} */ symbol,
    /** @type {number} */ height = 180,
    /** @type {number} */ pollMs = 3000,
    /** @type {boolean} */ autoPoll = true,
  } = $props();

  /** @type {Array<{ts:string,ltp:number,bid:number|null,ask:number|null}>} */
  let ticks = $state([]);
  /** @type {Array<{ts:string,kind:string,side:string,price:number|null,status:string,order_id:number,attempts:number,detail:string|null}>} */
  let events = $state([]);
  let error = $state('');
  let loading = $state(true);
  let timer = $state(/** @type {any} */ (null));
  let mounted = $state(true);
  /** @type {{x:number,y:number,kind:string,side:string,price:number|null,ts:string,detail:string|null,order_id:number}|null} */
  let hover = $state(null);

  async function load() {
    if (!mode || !symbol) { loading = false; return; }
    try {
      const r = await fetchChartPriceHistory(mode, symbol);
      if (!mounted) return;
      ticks = r.ticks || [];
      events = r.events || [];
      error = '';
    } catch (e) {
      error = e.message || String(e);
    } finally {
      loading = false;
    }
  }

  function startPolling() {
    if (!autoPoll || !pollMs) return;
    stopPolling();
    timer = setInterval(load, pollMs);
  }
  function stopPolling() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  onMount(() => { load(); startPolling(); });
  onDestroy(() => { mounted = false; stopPolling(); });

  // Reload when props change.
  $effect(() => {
    // Re-trigger when mode/symbol switch.
    void mode; void symbol;
    loading = true; ticks = []; events = []; error = '';
    load();
  });

  // ── Chart geometry ─────────────────────────────────────────────────
  const W = 720;            // viewBox width (scales to container via 100%)
  const PAD_L = 40, PAD_R = 8, PAD_T = 8, PAD_B = 22;

  const xAxisY = $derived(height - PAD_B);
  const innerW = $derived(W - PAD_L - PAD_R);
  const innerH = $derived(height - PAD_T - PAD_B);

  // Time domain: from first tick's ts to max(now, last tick).
  const tMin = $derived(ticks.length ? +new Date(ticks[0].ts) : 0);
  const tMax = $derived(ticks.length ? +new Date(ticks[ticks.length - 1].ts) : 1);
  const tSpan = $derived(Math.max(1, tMax - tMin));

  // Price domain — pad ±2% so the line doesn't kiss the frame.
  const prices = $derived(
    ticks.flatMap(t => [t.ltp, t.bid, t.ask].filter(v => v != null))
  );
  const pMin = $derived(prices.length ? Math.min(...prices) : 0);
  const pMax = $derived(prices.length ? Math.max(...prices) : 1);
  const pPad = $derived(Math.max((pMax - pMin) * 0.05, pMin * 0.0005, 0.5));
  const yMin = $derived(pMin - pPad);
  const yMax = $derived(pMax + pPad);
  const ySpan = $derived(Math.max(0.001, yMax - yMin));

  function xOf(/** @type {string} */ ts) {
    return PAD_L + ((+new Date(ts) - tMin) / tSpan) * innerW;
  }
  function yOf(/** @type {number} */ price) {
    return PAD_T + (1 - (price - yMin) / ySpan) * innerH;
  }

  // Path for the LTP line.
  const ltpPath = $derived.by(() => {
    if (!ticks.length) return '';
    return ticks.map((t, i) =>
      `${i === 0 ? 'M' : 'L'}${xOf(t.ts).toFixed(1)},${yOf(t.ltp).toFixed(1)}`
    ).join(' ');
  });

  // Bid/ask shaded band (faint cyan area between bid and ask paths) —
  // only drawn when both sides are populated, so live/paper mode shows
  // the spread band but pure-LTP-only ticks (rare) skip it cleanly.
  const bandPath = $derived.by(() => {
    if (!ticks.length) return '';
    const top = ticks.filter(t => t.ask != null);
    const bot = ticks.filter(t => t.bid != null);
    if (!top.length || !bot.length) return '';
    const up = top.map(t => `${xOf(t.ts).toFixed(1)},${yOf(/**@type{number}*/(t.ask)).toFixed(1)}`);
    const dn = bot.slice().reverse().map(t => `${xOf(t.ts).toFixed(1)},${yOf(/**@type{number}*/(t.bid)).toFixed(1)}`);
    return `M${up.join(' L')} L${dn.join(' L')} Z`;
  });

  // Event markers — one circle per AlgoOrder lifecycle transition.
  const markerColors = /** @type {Record<string,string>} */ ({
    placed:   '#fbbf24',  // amber
    filled:   '#22c55e',  // emerald
    unfilled: '#ef4444',  // red
    chased:   '#7dd3fc',  // sky
  });

  function showHover(/** @type {any} */ e) {
    hover = {
      x: xOf(e.ts), y: yOf(e.price ?? ticks[ticks.length - 1]?.ltp ?? 0),
      kind: e.kind, side: e.side, price: e.price, ts: e.ts,
      detail: e.detail, order_id: e.order_id,
    };
  }
  function hideHover() { hover = null; }

  function fmtPrice(/** @type {number|null} */ v) {
    if (v == null) return '—';
    return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
  }
  function fmtTime(/** @type {string} */ ts) {
    try { return new Date(ts).toLocaleTimeString('en-IN', { hour12: false }); }
    catch { return ts; }
  }

  // Y-axis labels (3 evenly spaced).
  const yTicks = $derived.by(() => {
    if (!prices.length) return [];
    const n = 3;
    return Array.from({ length: n }, (_, i) => {
      const v = yMin + (ySpan * i) / (n - 1);
      return { v, y: yOf(v) };
    });
  });
</script>

<div class="price-chart" style="--chart-h: {height}px">
  <div class="chart-header">
    <span class="chart-symbol">{symbol || '—'}</span>
    <span class="chart-mode chart-mode-{mode}">{mode?.toUpperCase()}</span>
    {#if loading}
      <span class="chart-status">loading…</span>
    {:else if error}
      <span class="chart-status chart-error" title={error}>error</span>
    {:else}
      <span class="chart-status">{ticks.length} ticks · {events.length} events</span>
    {/if}
  </div>

  {#if !loading && !ticks.length}
    <div class="chart-empty">
      No price ticks captured yet for <span class="font-mono">{symbol}</span>.
      Ticks are recorded once an order is open against the symbol{mode === 'sim' ? ' or the simulator is running' : ''}.
    </div>
  {:else if ticks.length}
    <svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" class="chart-svg">
      <!-- Y-axis grid + labels -->
      {#each yTicks as t}
        <line x1={PAD_L} x2={W - PAD_R} y1={t.y} y2={t.y}
              stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
        <text x={PAD_L - 4} y={t.y + 3} text-anchor="end"
              fill="#7e97b8" font-size="9" font-family="monospace">
          {t.v.toFixed(2)}
        </text>
      {/each}
      <!-- X-axis baseline -->
      <line x1={PAD_L} x2={W - PAD_R} y1={xAxisY} y2={xAxisY}
            stroke="rgba(255,255,255,0.15)" stroke-width="1"/>
      <text x={PAD_L} y={height - 6} fill="#7e97b8" font-size="9" font-family="monospace">
        {fmtTime(ticks[0].ts)}
      </text>
      <text x={W - PAD_R} y={height - 6} text-anchor="end"
            fill="#7e97b8" font-size="9" font-family="monospace">
        {fmtTime(ticks[ticks.length - 1].ts)}
      </text>

      <!-- Bid/ask band -->
      {#if bandPath}
        <path d={bandPath} fill="rgba(125,211,252,0.10)" stroke="none"/>
      {/if}

      <!-- LTP line -->
      <path d={ltpPath} fill="none" stroke="#fbbf24" stroke-width="1.5"/>

      <!-- Order event markers -->
      {#each events as ev}
        {#if ev.ts >= ticks[0].ts && ev.ts <= ticks[ticks.length - 1].ts}
          {@const cx = xOf(ev.ts)}
          {@const cy = yOf(ev.price ?? ticks[ticks.length - 1].ltp)}
          <g class="ev-marker"
             onmouseenter={() => showHover(ev)}
             onmouseleave={hideHover}
             role="img" aria-label="{ev.kind} {ev.side}">
            <circle cx={cx} cy={cy} r="6"
                    fill={markerColors[ev.kind] || '#fff'}
                    fill-opacity="0.18"
                    stroke={markerColors[ev.kind] || '#fff'}
                    stroke-width="1.5"/>
            <circle cx={cx} cy={cy} r="2.5"
                    fill={markerColors[ev.kind] || '#fff'}/>
          </g>
        {/if}
      {/each}

      <!-- Hover tooltip -->
      {#if hover}
        {@const tx = Math.min(W - 180 - PAD_R, Math.max(PAD_L, hover.x + 8))}
        {@const ty = Math.max(PAD_T, hover.y - 60)}
        <g pointer-events="none">
          <rect x={tx} y={ty} width="180" height="56" rx="4"
                fill="#1d2a44" stroke="rgba(251,191,36,0.4)" stroke-width="1"/>
          <text x={tx + 6} y={ty + 14} fill="#fbbf24"
                font-size="10" font-weight="700" font-family="monospace">
            {hover.kind.toUpperCase()} · {hover.side}
          </text>
          <text x={tx + 6} y={ty + 28} fill="#e2e8f0"
                font-size="9" font-family="monospace">
            {fmtPrice(hover.price)} @ {fmtTime(hover.ts)}
          </text>
          <text x={tx + 6} y={ty + 42} fill="#7e97b8"
                font-size="9" font-family="monospace">
            order #{hover.order_id}
          </text>
        </g>
      {/if}
    </svg>
  {/if}
</div>

<style>
  .price-chart {
    background: linear-gradient(180deg, #1d2a44 0%, #152033 100%);
    border: 1px solid rgba(251,191,36,0.18);
    border-left: 3px solid #fbbf24;
    border-radius: 4px;
    padding: 6px 8px 4px;
    width: 100%;
    box-sizing: border-box;
  }
  .chart-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 4px;
    font-size: 0.6rem;
  }
  .chart-symbol {
    font-family: monospace;
    color: #7dd3fc;
    font-weight: 700;
  }
  .chart-mode {
    font-family: monospace;
    font-size: 0.55rem;
    padding: 1px 5px;
    border-radius: 3px;
    font-weight: 700;
    border: 1px solid currentColor;
  }
  .chart-mode-sim   { color: #fbbf24; }
  .chart-mode-paper { color: #7dd3fc; }
  .chart-mode-live  { color: #22c55e; }
  .chart-status {
    color: #7e97b8;
    margin-left: auto;
    font-family: monospace;
  }
  .chart-error { color: #ef4444; }
  .chart-empty {
    height: var(--chart-h, 180px);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #7e97b8;
    font-size: 0.6rem;
    font-family: monospace;
    text-align: center;
    padding: 0 1rem;
  }
  .chart-svg {
    width: 100%;
    height: var(--chart-h, 180px);
    display: block;
  }
  :global(.price-chart .ev-marker) { cursor: pointer; }
</style>
