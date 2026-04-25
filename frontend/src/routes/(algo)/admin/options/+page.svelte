<script>
  // Options Analytics dashboard (/admin/options).
  //
  // Distinct from the regular tick-chart pages (/admin/simulator,
  // /admin/paper) — those are tick-by-tick price monitors. THIS page is
  // an options-research workspace: payoff diagram, Greeks, theoretical-
  // vs-market discrepancy, risk metrics, POP, historical price chart.
  //
  // Four input modes:
  //   live          — pick a symbol from broker positions
  //   sim           — pick from active simulator positions
  //   hypothetical  — type any option symbol to dry-analyse pre-trade
  //   strategy      — combine multiple legs (vertical, iron condor, …)
  //
  // The analytics endpoint returns everything in one round-trip; this
  // page polls every 5 s while the symbol is set so Greeks + IV + LTP
  // stay current. Historical chart fetches once on symbol change.

  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, visibleInterval } from '$lib/stores';
  import {
    fetchPositions, fetchSimStatus, fetchOptionAnalytics, fetchOptionHistorical,
    fetchStrategyAnalytics,
  } from '$lib/api';
  import OptionsPayoff from '$lib/OptionsPayoff.svelte';
  import PriceChart    from '$lib/PriceChart.svelte';
  import Select        from '$lib/Select.svelte';
  import InfoHint      from '$lib/InfoHint.svelte';

  /** @type {'live'|'sim'|'hypothetical'|'strategy'} */
  let mode = $state('live');
  let symbol = $state('');
  let account = $state('');
  // Hypothetical extras — let the operator preview a position they
  // haven't taken yet.
  let hypoQty   = $state(/** @type {number|''} */ (50));
  let hypoCost  = $state(/** @type {number|''} */ (''));

  /** @type {any} */ let analytics = $state(null);
  /** @type {any} */ let historical = $state(null);
  /** @type {any} */ let strategy = $state(null);
  let analyticsErr  = $state('');
  let historicalErr = $state('');
  let strategyErr   = $state('');
  let loading       = $state(false);
  let teardown;
  let posTeardown;

  // Strategy legs — operator builds a list, "Add from book" auto-fills
  // from a live or sim position so sim legs ship their own ltp + cost
  // (no broker round-trip needed). Manual rows leave ltp blank and the
  // backend fetches it from the broker.
  /** @type {Array<{symbol:string, qty:string|number, avg_cost:string|number, ltp:string|number, source:string}>} */
  let legs = $state([]);
  let legPickerValue = $state('');

  function addLegRow() {
    legs = [...legs, { symbol: '', qty: '', avg_cost: '', ltp: '', source: 'manual' }];
  }
  function removeLegRow(/** @type {number} */ i) {
    legs = legs.filter((_, idx) => idx !== i);
  }
  function clearLegs() { legs = []; strategy = null; strategyErr = ''; }

  // When the operator picks an existing position from the leg picker,
  // append it as a new leg with ltp + avg_cost captured at click-time
  // (sim positions need this because the backend can't fetch their ltp).
  $effect(() => {
    const v = legPickerValue;
    if (!v) return;
    const [src, acct, sym] = v.split('|');
    const found = positions.find(p => p.source === src && p.account === acct && p.symbol === sym);
    if (!found) return;
    legs = [...legs, {
      symbol:   found.symbol,
      qty:      found.qty,
      avg_cost: found.avg_cost ?? '',
      ltp:      found.ltp ?? '',
      source:   src,
    }];
    legPickerValue = '';   // reset picker for next add
  });

  // Position lists for the picker. Carries avg_cost + ltp so that
  // the strategy leg-builder can ship them inline (sim legs need this
  // because the backend can't fetch their ltp from the broker).
  /** @type {Array<{symbol:string, account:string, qty:number, source:string, avg_cost:number|null, ltp:number|null}>} */
  let positions = $state([]);

  async function loadPositions() {
    /** @type {Array<{symbol:string, account:string, qty:number, source:string, avg_cost:number|null, ltp:number|null}>} */
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
          symbol:   String(sym).toUpperCase(),
          account:  String(p?.account || ''),
          qty:      Number(p?.quantity || 0),
          source:   'live',
          avg_cost: p?.average_price != null ? Number(p.average_price) : null,
          ltp:      p?.last_price    != null ? Number(p.last_price)    : null,
        });
      }
    } catch (_) { /* ignore — show sim only */ }

    // Sim positions — capture last_price + average_price from the
    // driver state at click time so the strategy endpoint can compute
    // analytics without round-tripping back to the broker.
    try {
      const s = await fetchSimStatus();
      for (const p of (s?.positions || [])) {
        const sym = p?.symbol;
        if (!sym) continue;
        if (!/(CE|PE|FUT)$/i.test(String(sym))) continue;
        merged.push({
          symbol:   String(sym).toUpperCase(),
          account:  String(p?.account || ''),
          qty:      Number(p?.quantity || 0),
          source:   'sim',
          avg_cost: p?.average_price != null ? Number(p.average_price) : null,
          ltp:      p?.last_price    != null ? Number(p.last_price)    : null,
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

  async function loadStrategy() {
    const cleanLegs = legs
      .map(l => ({
        symbol:   String(l.symbol || '').trim().toUpperCase(),
        qty:      l.qty === '' || l.qty == null ? 0 : Number(l.qty),
        avg_cost: l.avg_cost === '' || l.avg_cost == null ? null : Number(l.avg_cost),
        ltp:      l.ltp      === '' || l.ltp      == null ? null : Number(l.ltp),
      }))
      .filter(l => l.symbol && l.qty);
    if (!cleanLegs.length) {
      strategy = null; strategyErr = '';
      return;
    }
    loading = true; strategyErr = '';
    try {
      strategy = await fetchStrategyAnalytics(cleanLegs);
    } catch (e) {
      strategyErr = /** @type {any} */ (e).message || String(e);
      strategy = null;
    } finally {
      loading = false;
    }
  }

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
    // Two separate cadences:
    //   - hot (5 s): analytics / strategy aggregate — Greeks + IV move
    //     intra-tick so the operator wants this fresh.
    //   - cold (30 s): the picker's position list — the broker book
    //     changes on the order of minutes; polling it every 5 s wasted
    //     a /api/positions/ + /api/simulator/status round-trip per tick
    //     for no operator-visible benefit.
    // Historical refreshes only on symbol change (daily candles don't
    // change intra-day).
    teardown = visibleInterval(() => {
      if (mode === 'strategy') loadStrategy();
      else                     loadAnalytics();
    }, 5000);
    posTeardown = visibleInterval(loadPositions, 30000);
  });
  onDestroy(() => { teardown?.(); posTeardown?.(); });

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
  <h1 class="page-title-chip">Options Analytics</h1>
  <InfoHint>
    Pick a position from your live or sim book, or type any option symbol
    to analyze it as a hypothetical trade. The payoff diagram shows how
    the position pays at <span class="font-mono">today</span>
    (Black-Scholes with current DTE/IV) vs
    <span class="font-mono">expiry</span> (intrinsic only). Side panel:
    Greeks, IV, theoretical-vs-market gap, max profit / max loss /
    breakeven / probability of profit. Switch source to
    <span class="font-mono">Strategy</span> for multi-leg analytics
    (vertical / iron condor / butterfly).
  </InfoHint>
  <span class="algo-ts">{clientTimestamp()}</span>
</div>

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
          { value: 'strategy',     label: 'Strategy (multi-leg)' },
        ]} />
    </div>

    {#if mode === 'strategy'}
      <!-- Multi-leg builder. Two ways to add a leg:
           1. Pick from existing live or sim positions — captures the
              current avg_cost + ltp at click time, so sim legs ship
              their own LTP (no broker round-trip needed).
           2. + Add row — empty row for hypothetical legs; ltp blank means
              the backend fetches it from the broker. -->
      <div class="opt-field opt-field-grow">
        <label class="field-label" for="opt-leg-pick">Add leg from book</label>
        <Select id="opt-leg-pick"
          bind:value={legPickerValue}
          options={pickerOptions}
          placeholder={pickerOptions.length ? 'Pick a position to add as a leg…' : 'No positions in book — type rows manually below'} />
      </div>
      <button type="button" class="sim-btn sim-btn-order"
              title="Append a blank leg row for hypothetical / manual entry"
              onclick={addLegRow}>+ Add row</button>
      <button type="button" class="sim-btn sim-btn-order"
              title="Compute aggregate analytics + payoff for the current legs"
              onclick={loadStrategy}>Analyze</button>
      {#if legs.length}
        <button type="button" class="sim-btn sim-btn-order opt-clear"
                title="Discard every leg and reset"
                onclick={clearLegs}>Clear</button>
      {/if}
    {:else if mode !== 'hypothetical'}
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

{#if analyticsErr && mode !== 'strategy'}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">{analyticsErr}</div>
{/if}
{#if strategyErr && mode === 'strategy'}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">{strategyErr}</div>
{/if}

{#if mode !== 'strategy' && !analytics && !analyticsErr && !loading}
  <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
    Pick a position above (or switch to Hypothetical and type a symbol)
    to load the analytics workspace.
  </div>
{/if}

<!-- ───────────────────────── STRATEGY (multi-leg) ───────────────────── -->
{#if mode === 'strategy'}
  <!-- Leg-builder table — operator's working set. Each row carries the
       full leg state (symbol/qty/avg_cost/ltp) and ships verbatim to the
       backend on Analyze. Sim-sourced legs already have LTP filled; live
       legs can leave LTP blank and the backend pulls it from broker. -->
  <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
    <div class="opt-section-h" style="padding-bottom: 0.5rem;">
      Legs <span class="opt-section-meta">({legs.length})</span>
    </div>
    {#if !legs.length}
      <div class="text-[0.6rem] text-[#7e97b8] italic">
        No legs yet. Pick from <b>Add leg from book</b> above (live or sim
        positions) or click <b>+ Add row</b> for a blank line you can fill
        manually.
      </div>
    {:else}
      <div class="leg-grid">
        <div class="leg-headrow">
          <span>Symbol</span>
          <span>Qty</span>
          <span>Avg cost</span>
          <span>LTP</span>
          <span>Source</span>
          <span></span>
        </div>
        {#each legs as _l, i (i)}
          <div class="leg-row">
            <input type="text" class="field-input"
              placeholder="NIFTY25APR22000CE"
              bind:value={legs[i].symbol} />
            <input type="number" class="field-input"
              placeholder="±qty"
              bind:value={legs[i].qty} />
            <input type="number" class="field-input"
              placeholder="₹"
              step="0.05"
              bind:value={legs[i].avg_cost} />
            <input type="number" class="field-input"
              placeholder={legs[i].source === 'sim' ? '₹ (required for sim)' : '₹ (auto from broker)'}
              step="0.05"
              bind:value={legs[i].ltp} />
            <span class="leg-source leg-source-{legs[i].source}">{legs[i].source}</span>
            <button type="button" class="leg-del"
                    title="Remove this leg"
                    onclick={() => removeLegRow(i)}>×</button>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  {#if strategy}
    <div class="opt-grid">
      <div class="opt-payoff">
        <div class="opt-section-h">
          Aggregate Payoff
          <span class="opt-section-tag tag-deriv">{strategy.underlying}</span>
          <span class="opt-section-tag tag-{strategy.net_cost > 0 ? 'long' : strategy.net_cost < 0 ? 'short' : 'long'}">
            {strategy.net_cost > 0 ? 'NET DEBIT' : strategy.net_cost < 0 ? 'NET CREDIT' : 'FREE'}
            {fmtMoney(Math.abs(strategy.net_cost), false)}
          </span>
          <span class="opt-section-meta">
            DTE {strategy.days_to_expiry.toFixed(1)} ·
            σ-proxy {(strategy.iv_proxy * 100).toFixed(1)}% ·
            {strategy.legs.length} legs
          </span>
        </div>
        <OptionsPayoff
          payoff={strategy.payoff}
          spot={strategy.spot}
          strikes={strategy.legs.map(l => l.strike)}
          breakevens={strategy.risk.breakevens}
          height={320} />
      </div>

      <aside class="opt-side">
        <div class="opt-block">
          <div class="opt-block-h">Aggregate</div>
          <div class="opt-kv">
            <span class="kv-k">Underlying</span> <span class="kv-v">{strategy.underlying}</span>
            <span class="kv-k">Spot</span>       <span class="kv-v">₹{strategy.spot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
            <span class="kv-k">Expiry</span>     <span class="kv-v">{strategy.expiry}</span>
            <span class="kv-k">Net cost</span>
            <span class="kv-v {strategy.net_cost > 0 ? 'kv-neg' : strategy.net_cost < 0 ? 'kv-pos' : ''}">
              {strategy.net_cost > 0 ? '−' : '+'}{fmtMoney(Math.abs(strategy.net_cost), false)}
            </span>
          </div>
        </div>

        <div class="opt-block">
          <div class="opt-block-h">Greeks (position)</div>
          <div class="opt-kv">
            <span class="kv-k">Δ delta</span>     <span class="kv-v">{fmtNum(strategy.aggregate_greeks.delta, 1)}</span>
            <span class="kv-k">Γ gamma</span>     <span class="kv-v">{fmtNum(strategy.aggregate_greeks.gamma, 4)}</span>
            <span class="kv-k">Θ theta /d</span>
            <span class="kv-v {strategy.aggregate_greeks.theta < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.theta, 0)}</span>
            <span class="kv-k">𝒱 vega /1%IV</span>
            <span class="kv-v {strategy.aggregate_greeks.vega < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.vega, 0)}</span>
            <span class="kv-k">ρ rho /1%r</span>  <span class="kv-v">{fmtNum(strategy.aggregate_greeks.rho, 0)}</span>
          </div>
        </div>

        <div class="opt-block">
          <div class="opt-block-h">Risk</div>
          <div class="opt-kv">
            <span class="kv-k">Max profit*</span>
            <span class="kv-v kv-pos">{fmtMoney(strategy.risk.max_profit, false)}</span>
            <span class="kv-k">Max loss*</span>
            <span class="kv-v kv-neg">{fmtMoney(strategy.risk.max_loss, true)}</span>
            <span class="kv-k">Breakevens</span>
            <span class="kv-v">
              {#if strategy.risk.breakevens.length}
                {strategy.risk.breakevens.map(/** @param {number} b */ (b) => `₹${b.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`).join(' / ')}
              {:else}—{/if}
            </span>
            <span class="kv-k">POP</span>
            <span class="kv-v {strategy.risk.pop > 0.6 ? 'kv-pos' : strategy.risk.pop < 0.4 ? 'kv-neg' : ''}">{fmtPct(strategy.risk.pop)}</span>
          </div>
          <div class="text-[0.5rem] text-[#7e97b8] mt-1 italic">
            * numerical max/min within
            {#if strategy.span_sigmas > 0}
              ±{strategy.span_sigmas.toFixed(1)}σ
              ({(strategy.span_pct * 100).toFixed(1)}%)
              spot range at expiry
            {:else}
              ±{(strategy.span_pct * 100).toFixed(1)}% spot range
            {/if}
          </div>
        </div>
      </aside>
    </div>

    <!-- Per-leg breakdown table — what each leg contributes. -->
    <div class="algo-status-card p-3 mb-3" data-status="inactive">
      <div class="opt-section-h" style="padding-bottom: 0.5rem;">Per-leg breakdown</div>
      <table class="leg-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Type</th>
            <th class="num">Strike</th>
            <th class="num">Qty</th>
            <th class="num">Cost</th>
            <th class="num">LTP</th>
            <th>Src</th>
            <th class="num">BS</th>
            <th class="num">Diff</th>
            <th class="num">IV</th>
            <th class="num">Δ</th>
            <th class="num">Θ/d</th>
            <th class="num">𝒱/1%</th>
          </tr>
        </thead>
        <tbody>
          {#each strategy.legs as l}
            <tr>
              <td class="font-mono">{l.symbol}</td>
              <td><span class="leg-type-{l.opt_type}">{l.opt_type}</span></td>
              <td class="num">{l.strike.toFixed(0)}</td>
              <td class="num {l.qty < 0 ? 'kv-neg' : 'kv-pos'}">{l.qty > 0 ? '+' : ''}{l.qty}</td>
              <td class="num">₹{l.avg_cost.toFixed(2)}</td>
              <td class="num">₹{l.ltp.toFixed(2)}</td>
              <td>
                {#if l.ltp_source === 'live' || l.ltp_source === 'override' || l.ltp_source === 'sim'}
                  <span class="leg-src leg-src-fresh">{l.ltp_source}</span>
                {:else}
                  <span class="leg-src leg-src-stale" title="LTP came from a fallback — treat numbers with care">{l.ltp_source}</span>
                {/if}
              </td>
              <td class="num">₹{l.theoretical.toFixed(2)}</td>
              <td class="num {l.discrepancy >= 0 ? 'kv-pos' : 'kv-neg'}">{l.discrepancy >= 0 ? '+' : ''}{l.discrepancy.toFixed(2)}</td>
              <td class="num">
                {(l.iv * 100).toFixed(1)}%
                {#if l.iv_source === 'default'}
                  <span class="src-tag src-warn">·dflt</span>
                {/if}
              </td>
              <td class="num">{l.greeks.delta.toFixed(3)}</td>
              <td class="num kv-neg">{l.greeks.theta.toFixed(2)}</td>
              <td class="num">{l.greeks.vega.toFixed(2)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if !strategyErr && !legs.length}
    <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
      Add at least one leg above, then click <b>Analyze</b>. All legs must
      share the same underlying and same expiry (calendar / diagonal
      spreads aren't supported in this version).
    </div>
  {/if}
{/if}

{#if mode !== 'strategy' && analytics}
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
          {#if analytics.span_sigmas > 0}
            · ±{analytics.span_sigmas.toFixed(1)}σ ({(analytics.span_pct * 100).toFixed(1)}%)
          {:else}
            · ±{(analytics.span_pct * 100).toFixed(1)}%
          {/if}
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
        <div class="opt-block-h">
          Pricing
          {#if analytics.ltp_source === 'estimated'}
            <span class="src-chip src-warn" title="Broker market-data unreachable — payoff drawn against an estimated LTP at default IV. Treat absolute numbers with care.">
              estimated
            </span>
          {:else if analytics.ltp_source !== 'live' && analytics.ltp_source !== 'override' && analytics.ltp_source !== 'sim'}
            <span class="src-chip src-stale" title="Live LTP unavailable — using {analytics.ltp_source}">
              stale: {analytics.ltp_source}
            </span>
          {/if}
          {#if analytics.spot_source === 'fallback'}
            <span class="src-chip src-warn" title="Underlying spot unavailable — using strike as synthetic spot. Payoff shape is preserved; absolute P&L is not reliable.">
              spot: synthetic
            </span>
          {/if}
        </div>
        <div class="opt-kv">
          <span class="kv-k">Spot</span>
          <span class="kv-v">
            ₹{analytics.spot.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            {#if analytics.spot_source !== 'live' && analytics.spot_source !== 'override' && analytics.spot_source !== 'sim'}
              <span class="src-tag" title="spot source = {analytics.spot_source}">·{analytics.spot_source}</span>
            {/if}
          </span>
          <span class="kv-k">LTP</span>
          <span class="kv-v">
            ₹{analytics.ltp.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
            <span class="src-tag" title="ltp source = {analytics.ltp_source}">·{analytics.ltp_source}</span>
          </span>
          <span class="kv-k">BS theo</span>  <span class="kv-v">₹{analytics.theoretical.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">Diff</span>
          <span class="kv-v {analytics.discrepancy >= 0 ? 'kv-pos' : 'kv-neg'}">
            {analytics.discrepancy >= 0 ? '+' : ''}₹{analytics.discrepancy.toFixed(2)}
            <span class="kv-sub">({analytics.discrepancy_pct.toFixed(1)}%)</span>
          </span>
          <span class="kv-k">IV</span>
          <span class="kv-v">
            {(analytics.iv * 100).toFixed(2)}%
            {#if analytics.iv_source === 'default'}
              <span class="src-tag src-warn" title="Calibration fell back to default 15% — LTP/spot data was insufficient">·default</span>
            {/if}
          </span>
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
      {#if historical}<span class="opt-section-meta">{historical.bars.length} daily bars · token {historical.instrument_token}</span>{/if}
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

  /* Leg builder — compact monospace grid mirroring the simulator's
     custom-positions panel so the two read as siblings. */
  .leg-grid {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-top: 0.4rem;
  }
  .leg-headrow,
  .leg-row {
    display: grid;
    grid-template-columns: minmax(0, 2.2fr) minmax(0, 0.9fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0.8fr) auto;
    gap: 0.35rem;
    align-items: center;
  }
  .leg-headrow {
    font-family: monospace;
    font-size: 0.55rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding-bottom: 0.15rem;
    border-bottom: 1px solid rgba(251,191,36,0.18);
  }
  :global(.leg-row .field-input) {
    font-size: 0.62rem;
    padding: 0.25rem 0.4rem;
    font-family: monospace;
  }
  .leg-source {
    font-family: monospace;
    font-size: 0.55rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #7e97b8;
    text-align: center;
  }
  .leg-source-live   { color: #22c55e; }
  .leg-source-sim    { color: #fbbf24; }
  .leg-source-manual { color: #7dd3fc; }
  .leg-del {
    width: 1.4rem;
    height: 1.4rem;
    border-radius: 3px;
    border: 1px solid rgba(248,113,113,0.4);
    background: rgba(248,113,113,0.08);
    color: #f87171;
    font-size: 0.85rem;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
  }
  .leg-del:hover {
    background: rgba(248,113,113,0.18);
    border-color: rgba(248,113,113,0.65);
  }

  /* Per-leg breakdown table — same monospace look as the Greeks table on
     the single-leg view, but wider (more columns to read). */
  .leg-table {
    width: 100%;
    border-collapse: collapse;
    font-family: monospace;
    font-size: 0.6rem;
  }
  .leg-table th {
    text-align: left;
    color: #7e97b8;
    font-weight: 700;
    padding: 0.2rem 0.35rem;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-size: 0.55rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    background: rgba(251,191,36,0.04);
  }
  .leg-table th.num,
  .leg-table td.num { text-align: right; }
  .leg-table td {
    padding: 0.22rem 0.35rem;
    color: #c8d8f0;
  }
  .leg-table tbody tr:not(:last-child) td {
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .leg-type-CE {
    color: #22c55e;
    background: rgba(34,197,94,0.10);
    border: 1px solid rgba(34,197,94,0.4);
    border-radius: 2px;
    padding: 0 4px;
    font-weight: 700;
    font-size: 0.55rem;
  }
  .leg-type-PE {
    color: #f87171;
    background: rgba(248,113,113,0.10);
    border: 1px solid rgba(248,113,113,0.4);
    border-radius: 2px;
    padding: 0 4px;
    font-weight: 700;
    font-size: 0.55rem;
  }

  /* "Clear" button styled subtly red so the destructive action stands
     out from "+ Add row" / "Analyze" without being scary. */
  :global(.opt-clear) {
    border-color: rgba(248,113,113,0.45) !important;
    color: #f87171 !important;
  }
  :global(.opt-clear:hover) {
    background: rgba(248,113,113,0.10) !important;
  }

  /* Stale-LTP / fallback-source chips — surfaced when broker live price
     wasn't available and the engine fell back (close/depth/avg_cost/
     default IV). Lets the operator know which numbers to treat with
     extra care, without burying the result. */
  .src-chip {
    margin-left: 0.5rem;
    font-family: monospace;
    font-size: 0.5rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid currentColor;
  }
  .src-stale {
    color: #fbbf24;
    background: rgba(251,191,36,0.10);
  }
  .src-tag {
    margin-left: 0.3rem;
    font-family: monospace;
    font-size: 0.5rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .src-warn { color: #fbbf24; font-weight: 700; }
  /* When .src-warn is paired with .src-chip (background context), give
     it the same amber-tinted background as .src-stale so the chip looks
     like a chip and not just amber text floating on the panel. */
  .src-chip.src-warn { background: rgba(251,191,36,0.14); }

  /* Per-leg LTP source pill — fresh = sky-blue, stale = amber. Sits in
     its own column on the breakdown table. */
  .leg-src {
    display: inline-block;
    font-family: monospace;
    font-size: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid currentColor;
    font-weight: 700;
  }
  .leg-src-fresh { color: #7dd3fc; background: rgba(125,211,252,0.10); }
  .leg-src-stale { color: #fbbf24; background: rgba(251,191,36,0.10); }
</style>
