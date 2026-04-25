<script>
  // Options Analytics dashboard (/admin/options).
  //
  // Distinct from the regular tick-chart pages (/admin/simulator,
  // /admin/paper) — those are tick-by-tick price monitors. THIS page is
  // an options-research workspace: payoff diagram, Greeks, theoretical-
  // vs-market discrepancy, risk metrics, POP, historical price chart.
  //
  // Three input modes:
  //   live          — pick a symbol from broker positions
  //   sim           — pick from active simulator positions
  //   hypothetical  — type any option symbol to dry-analyse pre-trade
  //
  // The analytics endpoint returns everything in one round-trip; this
  // page polls every 5 s while the symbol is set so Greeks + IV + LTP
  // stay current. Historical chart fetches once on symbol change.

  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, visibleInterval } from '$lib/stores';
  import {
    fetchPositions, fetchSimStatus, fetchOptionAnalytics, fetchOptionHistorical,
  } from '$lib/api';
  import OptionsPayoff from '$lib/OptionsPayoff.svelte';
  import PriceChart    from '$lib/PriceChart.svelte';
  import Select        from '$lib/Select.svelte';

  /** @type {'live'|'sim'|'hypothetical'} */
  let mode = $state('live');
  let symbol = $state('');
  let account = $state('');
  // Hypothetical extras — let the operator preview a position they
  // haven't taken yet.
  let hypoQty   = $state(/** @type {number|''} */ (50));
  let hypoCost  = $state(/** @type {number|''} */ (''));

  /** @type {any} */ let analytics = $state(null);
  /** @type {any} */ let historical = $state(null);
  let analyticsErr  = $state('');
  let historicalErr = $state('');
  let loading       = $state(false);
  let teardown;

  // Position lists for the picker.
  /** @type {Array<{symbol:string, account:string, qty:number, source:string}>} */
  let positions = $state([]);

  async function loadPositions() {
    /** @type {any[]} */
    const merged = [];

    // Live broker positions
    try {
      const r = await fetchPositions();
      for (const p of (r?.rows || [])) {
        const sym = p?.tradingsymbol || p?.symbol;
        if (!sym) continue;
        // Only options + futures (skip cash equities — this page is
        // options-only).
        if (!/(CE|PE|FUT)$/i.test(String(sym))) continue;
        merged.push({
          symbol:  String(sym).toUpperCase(),
          account: String(p?.account || ''),
          qty:     Number(p?.quantity || 0),
          source:  'live',
        });
      }
    } catch (_) { /* ignore — show sim only */ }

    // Sim positions
    try {
      const s = await fetchSimStatus();
      for (const p of (s?.positions || [])) {
        const sym = p?.symbol;
        if (!sym) continue;
        if (!/(CE|PE|FUT)$/i.test(String(sym))) continue;
        merged.push({
          symbol:  String(sym).toUpperCase(),
          account: String(p?.account || ''),
          qty:     Number(p?.quantity || 0),
          source:  'sim',
        });
      }
    } catch (_) { /* ignore */ }

    positions = merged;
  }

  // Pickable list — only CE/PE for analytics (futures show on the picker
  // but the analytics endpoint will reject them with a 400; we hide them
  // from the picker to avoid the round-trip).
  const pickerOptions = $derived(
    positions
      .filter(p => /(CE|PE)$/i.test(p.symbol))
      .map(p => ({
        value: `${p.source}|${p.account}|${p.symbol}`,
        label: `${p.source.toUpperCase()} · ${p.symbol} (${p.qty > 0 ? '+' : ''}${p.qty})${p.account ? ' · ' + p.account : ''}`,
      }))
  );

  // Picker state — bound to the Select. Wraps `mode|account|symbol` so
  // we can react to changes via $effect (Select doesn't expose onChange).
  let pickerValue = $state('');
  $effect(() => {
    const v = pickerValue;
    if (!v) return;
    const [src, acct, sym] = v.split('|');
    mode    = /** @type {any} */ (src);
    account = acct || '';
    symbol  = sym  || '';
    loadAnalytics();
    loadHistorical();
  });

  async function loadAnalytics() {
    if (!symbol) { analytics = null; return; }
    loading = true; analyticsErr = '';
    try {
      const opts = { mode, symbol };
      if (account) opts.account = account;
      if (mode === 'hypothetical') {
        if (hypoQty !== '' && hypoQty != null) opts.qty = Number(hypoQty);
        if (hypoCost !== '' && hypoCost != null) opts.avg_cost = Number(hypoCost);
      }
      analytics = await fetchOptionAnalytics(opts);
    } catch (e) {
      analyticsErr = /** @type {any} */ (e).message || String(e);
      analytics = null;
    } finally {
      loading = false;
    }
  }

  async function loadHistorical() {
    if (!symbol) { historical = null; return; }
    historicalErr = '';
    if (mode === 'sim') {
      historicalErr = 'Historical data unavailable for sim positions.';
      historical = null;
      return;
    }
    try {
      historical = await fetchOptionHistorical(symbol, 30, 'day', 'NFO');
    } catch (e) {
      historicalErr = /** @type {any} */ (e).message || String(e);
      historical = null;
    }
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin'); return;
    }
    loadPositions();
    // Re-poll analytics every 5s so Greeks + IV stay live while the
    // operator stares at the page. Historical refreshes only on symbol
    // change (daily candles don't change intra-day).
    teardown = visibleInterval(() => { loadAnalytics(); loadPositions(); }, 5000);
  });
  onDestroy(() => { teardown?.(); });

  // ── Helpers ──────────────────────────────────────────────────────
  function fmtMoney(/** @type {number|null|undefined} */ v, /** @type {boolean} */ signed = true) {
    if (v == null) return '∞';
    const sign = signed ? (v < 0 ? '-' : v > 0 ? '+' : '') : '';
    return `${sign}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  }
  function fmtPct(/** @type {number|null|undefined} */ v) {
    if (v == null) return '—';
    return `${(v * 100).toFixed(1)}%`;
  }
  function fmtNum(/** @type {number|null|undefined} */ v, /** @type {number} */ dp = 4) {
    if (v == null) return '—';
    return v.toFixed(dp);
  }

  // Ad-hoc historical chart payload — adapter to the PriceChart component
  // shape. Each daily bar becomes a tick of `close` price.
  const historicalChartData = $derived.by(() => {
    if (!historical?.bars?.length) return null;
    return {
      mode:       'live',
      symbol:     historical.symbol,
      kind:       'derivative',
      underlying: analytics?.underlying || null,
      ticks:      historical.bars.map(/** @param {any} b */ (b) => ({
        ts: b.ts, ltp: b.close, bid: null, ask: null,
      })),
      events:     [],
    };
  });
</script>

<svelte:head><title>Options Analytics | RamboQuant Analytics</title></svelte:head>

<div class="page-header">
  <h1 class="page-title-chip"
      title="Greeks, payoff diagram, theoretical-vs-market discrepancy, risk metrics, and historical price for any single-leg option position.">
    Options Analytics
  </h1>
  <span class="algo-ts">{clientTimestamp()}</span>
</div>

<p class="text-[0.65rem] text-[#c8d8f0]/70 mb-3 max-w-3xl">
  Pick a position from your live or sim book, or type any option symbol
  to analyze it as a hypothetical trade. The payoff diagram shows how
  the position pays at <span class="font-mono">today</span> (Black-Scholes
  with current DTE/IV) vs <span class="font-mono">expiry</span> (intrinsic
  only). Side panel: Greeks, IV, theoretical-vs-market gap, max profit /
  max loss / breakeven / probability of profit.
</p>

<!-- Picker bar — three input modes share the same row so switching modes
     is a one-click action. -->
<div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
  <div class="opt-picker">
    <div class="opt-field">
      <label class="field-label" for="opt-mode">Source</label>
      <Select id="opt-mode"
        bind:value={mode}
        options={[
          { value: 'live',         label: 'Live position' },
          { value: 'sim',          label: 'Sim position'  },
          { value: 'hypothetical', label: 'Hypothetical'  },
        ]} />
    </div>

    {#if mode !== 'hypothetical'}
      <div class="opt-field opt-field-grow">
        <label class="field-label" for="opt-pos">Position</label>
        <Select id="opt-pos"
          bind:value={pickerValue}
          options={pickerOptions}
          placeholder={pickerOptions.length ? 'Pick a position…' : 'No positions yet — switch to Hypothetical'} />
      </div>
    {:else}
      <div class="opt-field opt-field-grow">
        <label class="field-label" for="opt-sym">Symbol</label>
        <input id="opt-sym" type="text" class="field-input"
          placeholder="NIFTY25APR22000CE"
          bind:value={symbol} />
      </div>
      <div class="opt-field">
        <label class="field-label" for="opt-qty">Qty</label>
        <input id="opt-qty" type="number" class="field-input"
          placeholder="±qty (negative = short)"
          bind:value={hypoQty} />
      </div>
      <div class="opt-field">
        <label class="field-label" for="opt-cost">Avg cost</label>
        <input id="opt-cost" type="number" class="field-input"
          placeholder="(LTP)"
          step="0.05"
          bind:value={hypoCost} />
      </div>
      <button type="button" class="sim-btn sim-btn-order"
        onclick={() => { loadAnalytics(); loadHistorical(); }}>Analyze</button>
    {/if}
  </div>
</div>

{#if analyticsErr}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">{analyticsErr}</div>
{/if}

{#if !analytics && !analyticsErr && !loading}
  <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
    Pick a position above (or switch to Hypothetical and type a symbol)
    to load the analytics workspace.
  </div>
{/if}

{#if analytics}
  <div class="opt-grid">
    <!-- Payoff diagram (large) -->
    <div class="opt-payoff">
      <div class="opt-section-h">
        Payoff
        <span class="opt-section-tag tag-deriv">{analytics.symbol}</span>
        <span class="opt-section-tag tag-{analytics.risk.long_short}">
          {analytics.risk.long_short.toUpperCase()} {Math.abs(analytics.qty)}
        </span>
        <span class="opt-section-meta">
          DTE {analytics.days_to_expiry.toFixed(1)} ·
          IV {(analytics.iv * 100).toFixed(1)}%
        </span>
      </div>
      <OptionsPayoff
        payoff={analytics.payoff}
        spot={analytics.spot}
        strike={analytics.strike}
        breakeven={analytics.risk.breakeven}
        currentPnl={(analytics.ltp - analytics.avg_cost) * analytics.qty}
        height={320} />
    </div>

    <!-- Side panel: pricing + Greeks + risk -->
    <aside class="opt-side">
      <div class="opt-block">
        <div class="opt-block-h">Pricing</div>
        <div class="opt-kv">
          <span class="kv-k">Spot</span>     <span class="kv-v">₹{analytics.spot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">LTP</span>      <span class="kv-v">₹{analytics.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">BS theo</span>  <span class="kv-v">₹{analytics.theoretical.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">Diff</span>
          <span class="kv-v {analytics.discrepancy >= 0 ? 'kv-pos' : 'kv-neg'}">
            {analytics.discrepancy >= 0 ? '+' : ''}₹{analytics.discrepancy.toFixed(2)}
            <span class="kv-sub">({analytics.discrepancy_pct.toFixed(1)}%)</span>
          </span>
          <span class="kv-k">IV</span>       <span class="kv-v">{(analytics.iv * 100).toFixed(2)}%</span>
        </div>
      </div>

      <div class="opt-block">
        <div class="opt-block-h">Greeks</div>
        <table class="opt-table">
          <thead>
            <tr><th></th><th>per share</th><th>position</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Δ delta</td>
              <td class="num">{fmtNum(analytics.greeks_per_share.delta, 4)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.delta, 1)}</td>
            </tr>
            <tr>
              <td>Γ gamma</td>
              <td class="num">{fmtNum(analytics.greeks_per_share.gamma, 6)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.gamma, 4)}</td>
            </tr>
            <tr>
              <td>Θ theta /d</td>
              <td class="num kv-neg">{fmtNum(analytics.greeks_per_share.theta, 2)}</td>
              <td class="num kv-neg">{fmtNum(analytics.greeks_position.theta, 0)}</td>
            </tr>
            <tr>
              <td>𝒱 vega /1%IV</td>
              <td class="num">{fmtNum(analytics.greeks_per_share.vega, 2)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.vega, 0)}</td>
            </tr>
            <tr>
              <td>ρ rho /1%r</td>
              <td class="num">{fmtNum(analytics.greeks_per_share.rho, 2)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.rho, 0)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="opt-block">
        <div class="opt-block-h">Risk</div>
        <div class="opt-kv">
          <span class="kv-k">Max profit</span>
          <span class="kv-v kv-pos">{analytics.risk.max_profit == null ? '∞' : fmtMoney(analytics.risk.max_profit, false)}</span>
          <span class="kv-k">Max loss</span>
          <span class="kv-v kv-neg">{analytics.risk.max_loss == null ? '∞' : fmtMoney(-analytics.risk.max_loss)}</span>
          <span class="kv-k">Breakeven</span>
          <span class="kv-v">₹{analytics.risk.breakeven.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">POP</span>
          <span class="kv-v {analytics.risk.pop > 0.6 ? 'kv-pos' : analytics.risk.pop < 0.4 ? 'kv-neg' : ''}">{fmtPct(analytics.risk.pop)}</span>
        </div>
      </div>
    </aside>
  </div>

  <!-- Historical chart (full width below) -->
  <div class="opt-historical">
    <div class="opt-section-h">
      Historical · last 30 days
      {#if historical}<span class="opt-section-meta">{historical.bars.length} daily bars · token #{historical.instrument_token}</span>{/if}
    </div>
    {#if historicalErr}
      <div class="text-[0.6rem] text-amber-300 px-1">{historicalErr}</div>
    {:else if historicalChartData}
      <PriceChart mode="live"
                  symbol={analytics.symbol}
                  height={200}
                  data={historicalChartData}
                  autoPoll={false} />
    {:else}
      <div class="text-[0.6rem] text-[#7e97b8] px-1 italic">Loading historical bars…</div>
    {/if}
  </div>
{/if}

<style>
  .opt-picker {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 0.5rem;
    align-items: flex-end;
  }
  .opt-field {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 140px;
  }
  .opt-field-grow { flex: 1; min-width: 220px; }

  .opt-grid {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
    gap: 0.6rem;
    margin-bottom: 0.6rem;
  }
  @media (max-width: 980px) {
    .opt-grid { grid-template-columns: 1fr; }
  }

  .opt-section-h {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-family: monospace;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #fbbf24;
    padding: 0 0.25rem 0.4rem;
    flex-wrap: wrap;
  }
  .opt-section-tag {
    font-size: 0.55rem;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid currentColor;
    font-weight: 700;
  }
  .tag-deriv  { color: #7dd3fc; background: rgba(125,211,252,0.10); }
  .tag-long   { color: #22c55e; background: rgba(34,197,94,0.10); }
  .tag-short  { color: #f87171; background: rgba(248,113,113,0.10); }
  .opt-section-meta {
    color: #7e97b8;
    font-weight: 400;
    font-size: 0.55rem;
    margin-left: auto;
  }

  .opt-side {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .opt-block {
    background: linear-gradient(180deg, #1d2a44 0%, #152033 100%);
    border: 1px solid rgba(251,191,36,0.18);
    border-left: 3px solid #fbbf24;
    border-radius: 4px;
    padding: 0.5rem 0.65rem;
  }
  .opt-block-h {
    font-family: monospace;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #fbbf24;
    border-bottom: 1px solid rgba(251,191,36,0.18);
    padding-bottom: 0.25rem;
    margin-bottom: 0.4rem;
  }
  .opt-kv {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.25rem 0.7rem;
    font-family: monospace;
    font-size: 0.65rem;
  }
  .kv-k { color: #7e97b8; }
  .kv-v { color: #c8d8f0; text-align: right; }
  .kv-pos { color: #4ade80; }
  .kv-neg { color: #f87171; }
  .kv-sub { color: #7e97b8; font-size: 0.55rem; margin-left: 0.2rem; }

  .opt-table {
    width: 100%;
    border-collapse: collapse;
    font-family: monospace;
    font-size: 0.6rem;
  }
  .opt-table th {
    text-align: right;
    color: #7e97b8;
    font-weight: 700;
    padding: 0.15rem 0.25rem;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-size: 0.55rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .opt-table th:first-child { text-align: left; }
  .opt-table td {
    padding: 0.18rem 0.25rem;
    color: #c8d8f0;
  }
  .opt-table td.num { text-align: right; }
  .opt-table tbody tr:not(:last-child) td {
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }

  .opt-payoff {
    display: flex;
    flex-direction: column;
  }
  .opt-historical {
    margin-top: 0.3rem;
  }
</style>
