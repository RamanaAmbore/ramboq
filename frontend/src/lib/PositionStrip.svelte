<script>
  // Glanceable position / holdings strip — pinned just under the
  // navbar on every algo page. One static row of aggregates always
  // visible; click to expand a drawer with per-position chips
  // sorted by |day P&L| so the movers are at the front.
  //
  // Reads from dataCache (populated by /dashboard's PerformancePage
  // on mount + every refresh) so no extra API load. When the cache
  // is empty (cold start, anonymous demo on a non-cached page) the
  // strip self-loads positions + holdings via the public /api/
  // endpoints — same surface as the dashboard, identical masking.
  //
  // Industry analogue: IBKR TWS workspace ticker / Bloomberg's
  // workspace strip. Static numbers, not a marquee — operators
  // glance, not track. Above-fold (under the navbar) rather than
  // pinned to the footer where the eye tunes it out.

  import { onMount, onDestroy } from 'svelte';
  import { dataCache, visibleInterval } from '$lib/stores';
  import { fetchPositions, fetchHoldings } from '$lib/api';

  // Local mirror of the cache so the strip re-renders when /dashboard
  // refreshes the snapshot. The cache itself isn't a Svelte store
  // — we self-fetch on mount + refresh on a slow timer.
  let positions = $state(/** @type {any[]} */ ([]));
  let holdings  = $state(/** @type {any[]} */ ([]));
  let lastRefresh = $state('');

  /** @type {ReturnType<typeof visibleInterval> | null} */
  let teardown = null;

  let expanded = $state(false);

  // Demo / anonymous sessions still get real data (with masked
  // accounts) — same path as /performance. The strip only hides
  // when the operator hasn't loaded yet AND the cache is empty.
  async function loadOnce() {
    try {
      // Cache hit — paint instantly, then refresh in the background.
      if (dataCache.positions?.rows) positions = dataCache.positions.rows;
      if (dataCache.holdings?.rows)  holdings  = dataCache.holdings.rows;
      const [p, h] = await Promise.allSettled([fetchPositions(), fetchHoldings()]);
      if (p.status === 'fulfilled') {
        positions = p.value?.rows || [];
        dataCache.positions = p.value;
      }
      if (h.status === 'fulfilled') {
        holdings = h.value?.rows || [];
        dataCache.holdings = h.value;
      }
      lastRefresh = new Date().toLocaleTimeString('en-IN', {
        hour12: false, hour: '2-digit', minute: '2-digit',
      });
    } catch (_) { /* silent — strip just stays at last-good values */ }
  }

  onMount(() => {
    loadOnce();
    // Slow poll — strip is glanceable, not real-time. /performance
    // and /dashboard refresh every 30 s on their own; we mirror that
    // cadence so we don't hammer /api/positions when the operator
    // sits on a different algo page.
    teardown = visibleInterval(loadOnce, 30000);
  });
  onDestroy(() => { teardown?.(); });

  // ── Aggregates ────────────────────────────────────────────────
  // Day P&L: positions.pnl (positions are intraday — pnl IS the day
  // change) + holdings.day_change_val. Total P&L: positions.pnl +
  // holdings.pnl. Two distinct numbers because holdings carry an
  // unrealised P&L from the entry price, separate from today's move.
  const dayPnl = $derived.by(() => {
    let s = 0;
    for (const p of positions) s += Number(p?.pnl || 0);
    for (const h of holdings)  s += Number(h?.day_change_val || 0);
    return s;
  });
  const totalPnl = $derived.by(() => {
    let s = 0;
    for (const p of positions) s += Number(p?.pnl || 0);
    for (const h of holdings)  s += Number(h?.pnl || 0);
    return s;
  });

  /** Per-row chip data — merged positions + holdings, sorted by
   *  |day P&L| descending so the movers come first. Each chip
   *  carries enough to identify the symbol + read the day's
   *  direction at a glance.
   *
   *  IMPORTANT: only include rows with NON-ZERO quantity. Kite's
   *  /positions returns closed intraday positions with quantity=0
   *  (so callers can still read realised P&L), and stale holdings
   *  fully sold off mid-day surface the same way. Showing them as
   *  chips makes the strip look like it's tracking ghosts. The
   *  aggregate (DAY / TOTAL above) DOES keep their P&L — closed
   *  positions still contributed to the day's move. */
  const chips = $derived.by(() => {
    const out = [];
    for (const p of positions) {
      const qty = Number(p?.quantity || 0);
      if (qty === 0) continue;        // closed intraday — history only
      const dayChg = Number(p?.pnl || 0);
      const ltp    = Number(p?.close_price || 0);
      // Position day-pct ≈ pnl / (avg × |qty|). Avg can be 0 on a
      // freshly-opened intraday — fall back to ltp so we still get
      // a magnitude.
      const denom  = Math.abs(Number(p?.average_price || ltp || 0) * qty);
      const dayPct = denom > 0 ? (dayChg / denom) * 100 : 0;
      out.push({
        kind:    'position',
        symbol:  String(p?.tradingsymbol || ''),
        qty,
        ltp,
        dayChg,
        dayPct,
        account: String(p?.account || ''),
      });
    }
    for (const h of holdings) {
      const qty = Number(h?.quantity || 0);
      if (qty === 0) continue;        // sold-off holding — no live exposure
      out.push({
        kind:    'holding',
        symbol:  String(h?.tradingsymbol || ''),
        qty,
        ltp:     Number(h?.close_price || 0),
        dayChg:  Number(h?.day_change_val || 0),
        dayPct:  Number(h?.day_change_percentage || 0),
        account: String(h?.account || ''),
      });
    }
    out.sort((a, b) => Math.abs(b.dayChg) - Math.abs(a.dayChg));
    return out;
  });

  // Counts shown in the meta pill — only LIVE rows (qty != 0).
  // Mismatch with chips.length is impossible by construction.
  const livePositionCount = $derived(positions.filter(p => Number(p?.quantity || 0) !== 0).length);
  const liveHoldingCount  = $derived(holdings.filter(h => Number(h?.quantity || 0) !== 0).length);

  const hasContent = $derived(chips.length > 0);

  // How many chips fit in the collapsed strip without expanding?
  // We show the top 6 movers by default; "+N more" links to the
  // dashboard for the full picture. 6 is enough to cover a typical
  // multi-account book without dominating the navbar zone.
  const TOP_N = 6;
  const topChips      = $derived(chips.slice(0, TOP_N));
  const overflowCount = $derived(Math.max(0, chips.length - TOP_N));

  function fmtMoney(/** @type {number} */ v) {
    if (!isFinite(v)) return '—';
    const sign = v > 0 ? '+' : v < 0 ? '−' : '';
    return `${sign}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  }
  function fmtPct(/** @type {number} */ v) {
    if (!isFinite(v) || v === 0) return '0.00%';
    const sign = v > 0 ? '+' : '−';
    return `${sign}${Math.abs(v).toFixed(2)}%`;
  }
</script>

{#if hasContent}
  <div class="ps-strip" class:ps-strip-expanded={expanded}>
    <!-- Aggregates row — always visible. Click anywhere on this row
         (except the dashboard link) to toggle the per-position
         drawer. -->
    <button type="button" class="ps-row ps-row-summary"
            aria-expanded={expanded}
            aria-label="{expanded ? 'Collapse' : 'Expand'} position list"
            onclick={() => expanded = !expanded}>
      <span class="ps-chevron">{expanded ? '▾' : '▸'}</span>
      <span class="ps-agg">
        <span class="ps-agg-k">DAY</span>
        <span class={'ps-agg-v ' + (dayPnl > 0 ? 'ps-pos' : dayPnl < 0 ? 'ps-neg' : 'ps-flat')}>
          {fmtMoney(dayPnl)}
        </span>
      </span>
      <span class="ps-agg">
        <span class="ps-agg-k">TOTAL</span>
        <span class={'ps-agg-v ' + (totalPnl > 0 ? 'ps-pos' : totalPnl < 0 ? 'ps-neg' : 'ps-flat')}>
          {fmtMoney(totalPnl)}
        </span>
      </span>
      <span class="ps-agg ps-agg-meta">
        <span class="ps-agg-k">{livePositionCount}P · {liveHoldingCount}H</span>
      </span>
      {#if !expanded && chips.length > 0}
        <!-- Inline preview of the top 3 movers when collapsed —
             gives a glanceable cue without expanding. -->
        <span class="ps-preview">
          {#each chips.slice(0, 3) as c (c.kind + '|' + c.symbol)}
            <span class={'ps-preview-chip ' + (c.dayChg > 0 ? 'ps-pos-bg' : c.dayChg < 0 ? 'ps-neg-bg' : '')}>
              <span class="ps-preview-sym">{c.symbol}</span>
              <span class="ps-preview-pct">{fmtPct(c.dayPct)}</span>
            </span>
          {/each}
        </span>
      {/if}
      {#if lastRefresh}
        <span class="ps-refresh" title="Last refreshed (auto every 30 s)">{lastRefresh}</span>
      {/if}
    </button>

    {#if expanded}
      <!-- Per-position drawer — top N movers as chips, "+N more"
           link to /dashboard for the full grid. -->
      <div class="ps-drawer" role="region" aria-label="Position chips by day P&L">
        {#each topChips as c (c.kind + '|' + c.account + '|' + c.symbol)}
          <span class="ps-chip" class:ps-chip-pos={c.dayChg > 0} class:ps-chip-neg={c.dayChg < 0}
                title={`${c.kind === 'position' ? 'Position' : 'Holding'} · ${c.account || '—'} · ${c.qty} · LTP ₹${c.ltp || 0}`}>
            <span class="ps-chip-sym">{c.symbol}</span>
            <span class="ps-chip-qty">×{c.qty}</span>
            <span class="ps-chip-pct">{fmtPct(c.dayPct)}</span>
            <span class="ps-chip-money">{fmtMoney(c.dayChg)}</span>
          </span>
        {/each}
        {#if overflowCount > 0}
          <a class="ps-more" href="/dashboard"
             title="See the full {chips.length}-row dashboard">
            +{overflowCount} more →
          </a>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  /* Strip — pinned full-width just under the navbar (parent
     layout's ordering puts us between <header> and <main>).
     Single dark row matching the algo nav palette so the strip
     reads as part of the chrome, not the page content. */
  .ps-strip {
    background: linear-gradient(180deg, #0a1020 0%, #131c33 100%);
    border-bottom: 1px solid rgba(251,191,36,0.18);
    color: #c8d8f0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.6rem;
    letter-spacing: 0.04em;
    user-select: none;
  }

  /* Summary row — clickable, full-width. Reset button defaults so
     it inherits the strip's dark background instead of the OS
     button chrome. */
  .ps-row-summary {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    width: 100%;
    padding: 0.3rem 0.85rem;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    text-align: left;
    font: inherit;
    transition: background 0.08s;
  }
  .ps-row-summary:hover {
    background: rgba(251,191,36,0.06);
  }
  .ps-strip-expanded .ps-row-summary {
    border-bottom: 1px dashed rgba(251,191,36,0.18);
  }

  .ps-chevron {
    color: #fbbf24;
    font-size: 0.6rem;
    width: 0.9rem;
    text-align: center;
  }

  /* Aggregates — DAY / TOTAL labels in muted grey, values bigger
     and color-coded vs zero. */
  .ps-agg {
    display: inline-flex;
    align-items: baseline;
    gap: 0.3rem;
  }
  .ps-agg-k {
    color: #7e97b8;
    font-size: 0.5rem;
    font-weight: 700;
    text-transform: uppercase;
  }
  .ps-agg-v {
    font-size: 0.7rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .ps-agg-meta { margin-left: auto; }

  .ps-pos  { color: #4ade80; }
  .ps-neg  { color: #f87171; }
  .ps-flat { color: #c8d8f0; }

  .ps-pos-bg { background: rgba(74,222,128,0.10); }
  .ps-neg-bg { background: rgba(248,113,113,0.10); }

  .ps-refresh {
    color: rgba(180,200,230,0.5);
    font-size: 0.5rem;
    margin-left: 0.5rem;
  }

  /* Inline preview chips when collapsed — top 3 movers. */
  .ps-preview {
    display: inline-flex;
    gap: 0.35rem;
    flex: 1 1 auto;
    overflow: hidden;
  }
  .ps-preview-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 0.3rem;
    padding: 0.05rem 0.4rem;
    border-radius: 2px;
    border: 1px solid rgba(255,255,255,0.06);
    font-size: 0.55rem;
    white-space: nowrap;
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ps-preview-sym {
    color: #c8d8f0;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ps-preview-pct {
    color: inherit;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  /* Drawer — full chip list, sorted, with "+N more" overflow. */
  .ps-drawer {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    padding: 0.35rem 0.85rem 0.45rem;
    background: rgba(10,16,32,0.6);
  }
  .ps-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 0.4rem;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    font-size: 0.6rem;
    font-variant-numeric: tabular-nums;
  }
  .ps-chip-sym  { color: #fbbf24; font-weight: 700; }
  .ps-chip-qty  { color: #7e97b8; font-size: 0.55rem; }
  .ps-chip-pct  { color: #c8d8f0; font-weight: 700; }
  .ps-chip-money { color: #c8d8f0; }
  .ps-chip-pos {
    border-color: rgba(74,222,128,0.35);
    background: rgba(74,222,128,0.08);
  }
  .ps-chip-pos .ps-chip-pct,
  .ps-chip-pos .ps-chip-money { color: #4ade80; }
  .ps-chip-neg {
    border-color: rgba(248,113,113,0.35);
    background: rgba(248,113,113,0.08);
  }
  .ps-chip-neg .ps-chip-pct,
  .ps-chip-neg .ps-chip-money { color: #f87171; }

  .ps-more {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.55rem;
    border-radius: 3px;
    border: 1px dashed rgba(251,191,36,0.45);
    color: #fbbf24;
    text-decoration: none;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.05em;
  }
  .ps-more:hover {
    background: rgba(251,191,36,0.10);
    border-color: rgba(251,191,36,0.7);
  }

  @media (max-width: 640px) {
    .ps-row-summary { gap: 0.45rem; padding: 0.3rem 0.55rem; }
    .ps-preview { display: none; }   /* drawer is the read on mobile */
    .ps-refresh { display: none; }
    .ps-agg-meta { display: none; }
    .ps-drawer  { padding: 0.35rem 0.55rem 0.45rem; }
  }
</style>
