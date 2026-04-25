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
  import MultiSelect   from '$lib/MultiSelect.svelte';
  import InfoHint      from '$lib/InfoHint.svelte';
  import {
    loadInstruments, suggestUnderlyings,
    listExpiries, listStrikes, findOption,
    listFutures,
  } from '$lib/data/instruments';

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

  // Strategy mode v2 — pick (Account, Underlying) and the matching
  // open positions appear as toggleable candidates below the chart.
  // Each candidate is an option or future on the chosen underlying
  // that exists in one of the selected accounts. Operator checks the
  // ones to include; legs[] is derived from enabled candidates plus
  // any manually-added or chain-picked rows.

  /** @type {string[]} Selected account codes; empty = all accounts */
  let selectedAccounts = $state([]);
  /** @type {string} Underlying name (e.g. NIFTY); '' = pick required */
  let selectedUnderlying = $state('');
  /** @type {Record<string, boolean>} symbol → enabled flag */
  let enabledSymbols = $state({});

  // Manual / chain-picker / hypothetical legs — separate from the
  // book-derived candidates. These persist regardless of the dropdown
  // filter so an operator can build "what if I add NIFTY24500CE that
  // I don't own" alongside their real positions.
  /** @type {Array<{symbol:string, qty:string|number, avg_cost:string|number, ltp:string|number, source:string}>} */
  let legs = $state([]);
  let legPickerValue = $state('');

  // Distinct underlyings + accounts derived from the loaded positions.
  // Falls back to the major indices when the operator hasn't loaded a
  // book yet so the dropdowns never appear empty.
  const accountChoices = $derived.by(() => {
    const accts = new Set();
    for (const p of positions) {
      if (p.account) accts.add(p.account);
    }
    return Array.from(accts).sort();
  });
  const underlyingChoicesFromBook = $derived.by(() => {
    const set = new Set();
    for (const p of positions) {
      if (!/(CE|PE|FUT)$/i.test(p.symbol)) continue;
      // Strip everything from the first digit on — that's where the
      // YY-month-strike block starts. Works for monthly + weekly.
      const u = p.symbol.replace(/\d.*$/, '');
      if (u) set.add(u);
    }
    return Array.from(set).sort();
  });

  // Candidate positions matching the filter. Each candidate is an
  // option or future on the chosen underlying held in one of the
  // selected accounts (or all accounts when none selected).
  /** @type {{symbol:string,account:string,qty:number,avg_cost:number|null,ltp:number|null,source:string,kind:string}[]} */
  const candidatePositions = $derived.by(() => {
    if (!selectedUnderlying) return [];
    const target = selectedUnderlying.toUpperCase();
    /** @type {string[]} */
    const acctFilter = selectedAccounts.length ? selectedAccounts : [];
    /** @type {any[]} */
    const out = [];
    for (const p of positions) {
      if (acctFilter.length && !acctFilter.includes(p.account)) continue;
      const sym = p.symbol;
      // Match option/future by symbol prefix — same convention used by
      // parse_tradingsymbol on the backend.
      if (!new RegExp(`^${target}\\d`, 'i').test(sym)) continue;
      const isFut = /FUT$/i.test(sym);
      const isOpt = /(CE|PE)$/i.test(sym);
      if (!isFut && !isOpt) continue;
      out.push({
        ...p,
        kind: isFut ? 'fut' : 'opt',
      });
    }
    return out;
  });

  // Initialize the enable-flag map when candidates change. Default:
  // every candidate enabled (operator sees their book in the payoff
  // immediately; un-checks to drop a leg).
  $effect(() => {
    void selectedUnderlying; void selectedAccounts;
    /** @type {Record<string, boolean>} */
    const next = {};
    for (const c of candidatePositions) {
      // Preserve existing toggle state for symbols that survive the
      // filter change; default new ones to enabled.
      next[c.symbol] = (c.symbol in enabledSymbols)
        ? enabledSymbols[c.symbol]
        : true;
    }
    enabledSymbols = next;
  });

  // When candidates change OR toggle changes, rebuild the book-derived
  // portion of `legs`. Manual / chain rows (source='manual'/'chain')
  // are preserved verbatim. Live + sim sourced legs are replaced from
  // the current candidates × enabled-flag combination.
  $effect(() => {
    void candidatePositions; void enabledSymbols;
    if (mode !== 'strategy') return;
    const nonBook = legs.filter(l =>
      l.source === 'manual' || l.source === 'chain'
    );
    const book = candidatePositions
      .filter(c => enabledSymbols[c.symbol])
      .map(c => ({
        symbol:   c.symbol,
        qty:      c.qty,
        avg_cost: c.avg_cost ?? '',
        ltp:      c.ltp ?? '',
        source:   c.source,   // 'live' or 'sim'
      }));
    legs = [...book, ...nonBook];
  });

  // ── Option-chain picker (Strategy mode) ───────────────────────────
  // Lets the operator browse strikes for a given underlying + expiry
  // and add legs by clicking CE / PE buttons next to each strike. Pulls
  // the contract universe from the instruments cache (already loaded
  // for /console autocomplete) — no extra API round-trips.
  let instrumentsReady = $state(false);
  let chainUnderlying  = $state('');
  let chainExpiry      = $state('');
  let chainSide        = $state(/** @type {'long'|'short'} */ ('long'));
  // Convenience presets — auto-populate underlying when there's an
  // obvious choice from the operator's existing legs.
  /** @type {string[]} */
  let underlyingChoices = $state([]);

  // Expiry list rebuilds when the operator picks a different underlying.
  const chainExpiries = $derived.by(() => {
    if (!instrumentsReady || !chainUnderlying) return [];
    // Use 'CE' as the type — every option underlying has both CE + PE
    // expiries on the same dates, so checking one is enough.
    return listExpiries(chainUnderlying.toUpperCase(), 'CE');
  });
  // Strike grid for the picked (underlying, expiry).
  const chainStrikes = $derived.by(() => {
    if (!instrumentsReady || !chainUnderlying || !chainExpiry) return [];
    return listStrikes(chainUnderlying.toUpperCase(), 'CE', chainExpiry);
  });

  // Futures contracts on the same underlying — surfaced as a quick-add
  // row above the strike grid. Filter to the selected expiry first; if
  // none match (futures and option expiries can drift by a day in
  // weekly cycles), show whichever future is closest. Futures aren't
  // strikable, so they appear once per chain, not per row.
  const chainFutures = $derived.by(() => {
    if (!instrumentsReady || !chainUnderlying) return [];
    const all = listFutures(chainUnderlying.toUpperCase()) || [];
    if (chainExpiry) {
      const exact = all.filter(f => f.x === chainExpiry);
      if (exact.length) return exact;
    }
    // Return up to 3 nearest futures so the operator can see what's
    // available without a separate "show all expiries" toggle.
    return all.slice(0, 3);
  });

  function addFutureLeg(/** @type {string} */ symbol,
                        /** @type {number} */ lotSize) {
    if (!symbol) return;
    const lot = Number(lotSize || 1);
    const signedQty = chainSide === 'long' ? lot : -lot;
    legs = [...legs, {
      symbol,
      qty:      signedQty,
      avg_cost: '',
      ltp:      '',
      source:   'chain',
    }];
  }

  // Auto-pick first expiry when underlying changes.
  $effect(() => {
    void chainUnderlying;
    if (chainExpiries.length && !chainExpiries.includes(chainExpiry)) {
      chainExpiry = chainExpiries[0];
    }
  });

  function addChainLeg(/** @type {number} */ strike,
                       /** @type {'CE'|'PE'} */ optType) {
    if (!chainUnderlying || !chainExpiry) return;
    const inst = findOption(chainUnderlying.toUpperCase(), optType, strike, chainExpiry);
    if (!inst) return;
    const lot = Number(inst.ls || 1);
    const signedQty = chainSide === 'long' ? lot : -lot;
    legs = [...legs, {
      symbol:   inst.s,
      qty:      signedQty,
      avg_cost: '',
      ltp:      '',
      source:   'chain',
    }];
  }

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

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin'); return;
    }
    loadPositions();
    // Load the instruments cache so the option-chain picker has data.
    // Already cached in IndexedDB after the first /console autocomplete
    // load — most operators will see this resolve from cache instantly.
    try {
      await loadInstruments();
      instrumentsReady = true;
      // Pre-populate underlying choices from common indices first, then
      // anything else the operator has open positions on so the dropdown
      // shows familiar names at the top.
      const seen = new Set();
      const out = [];
      for (const u of ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']) {
        if (!seen.has(u)) { seen.add(u); out.push(u); }
      }
      for (const p of positions) {
        const u = p.symbol.replace(/\d.*$/, '');
        if (u && !seen.has(u)) { seen.add(u); out.push(u); }
      }
      // Fall back to a wider suggest scan so the dropdown isn't tiny on
      // a fresh book — pull every underlying that has CE options.
      for (const u of suggestUnderlyings('', 50)) {
        if (!seen.has(u)) { seen.add(u); out.push(u); }
      }
      underlyingChoices = out;
      if (!chainUnderlying && out.length) chainUnderlying = out[0];
    } catch (_) { /* instruments unreachable — chain picker hides */ }
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
  <InfoHint text={'Pick a position from your live or sim book, or type any option symbol to analyze it as a hypothetical trade. The payoff diagram shows how the position pays at <span class="font-mono">today</span> (Black-Scholes with current DTE/IV) vs <span class="font-mono">expiry</span> (intrinsic only). Side panel: Greeks, IV, theoretical-vs-market gap, max profit / max loss / breakeven / probability of profit. Switch source to <span class="font-mono">Strategy</span> for multi-leg analytics (vertical / iron condor / butterfly).'} />
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
      <!-- Strategy v2 — pick the underlying + accounts. Every option /
           future on that underlying held in those accounts becomes a
           toggleable candidate below the chart. Hypothetical legs go
           through the chain-picker card or the manual + Add row. -->
      <div class="opt-field opt-field-grow">
        <label class="field-label" for="opt-acct">Account</label>
        <MultiSelect id="opt-acct"
          bind:value={selectedAccounts}
          options={accountChoices.map(a => ({ value: a, label: a }))}
          placeholder={accountChoices.length ? 'All accounts' : 'No accounts loaded'} />
      </div>
      <div class="opt-field opt-field-grow">
        <label class="field-label" for="opt-und">Underlying</label>
        <Select id="opt-und"
          bind:value={selectedUnderlying}
          options={underlyingChoicesFromBook.map(u => ({ value: u, label: u }))}
          placeholder={underlyingChoicesFromBook.length ? 'Pick underlying…' : 'No options in book'} />
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

  <!-- Option-chain picker — browse strikes for one underlying / expiry
       and click CE / PE to drop a leg into the basket. Sourced from the
       cached instruments dump (already loaded by /console autocomplete),
       so no extra round-trips. Hidden until instruments finish loading. -->
  {#if instrumentsReady && underlyingChoices.length}
    <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
      <div class="opt-section-h" style="padding-bottom: 0.5rem;">
        Option chain
        <span class="opt-section-meta">
          click CE / PE next to a strike to add a leg ·
          quantity defaults to 1 lot
        </span>
      </div>
      <div class="chain-controls">
        <div class="chain-field">
          <label class="field-label" for="chain-und">Underlying</label>
          <Select id="chain-und"
            bind:value={chainUnderlying}
            options={underlyingChoices.map(u => ({ value: u, label: u }))} />
        </div>
        <div class="chain-field">
          <label class="field-label" for="chain-exp">Expiry</label>
          <Select id="chain-exp"
            bind:value={chainExpiry}
            options={chainExpiries.map(e => ({ value: e, label: e }))}
            placeholder={chainExpiries.length ? 'Pick expiry' : '—'} />
        </div>
        <div class="chain-field">
          <label class="field-label" for="chain-side">Side</label>
          <Select id="chain-side"
            bind:value={chainSide}
            options={[
              { value: 'long',  label: 'Long (+)' },
              { value: 'short', label: 'Short (−)' },
            ]} />
        </div>
      </div>
      {#if chainFutures.length}
        <!-- Futures quick-add row — clicking the contract pill drops it
             into the basket as a Long or Short leg per the Side toggle.
             Useful when building delta-hedged option positions or pure
             futures strategies. -->
        <div class="chain-futures">
          <span class="chain-futures-label">Futures:</span>
          {#each chainFutures as f (f.s)}
            <button type="button"
                    class="chain-fut-pill"
                    title="Add {f.s} as a {chainSide} leg ({f.ls} lot)"
                    onclick={() => addFutureLeg(f.s, f.ls)}>
              + {f.s}
              <span class="chain-fut-meta">lot {f.ls}</span>
            </button>
          {/each}
        </div>
      {/if}
      {#if chainStrikes.length}
        <div class="chain-grid-wrap">
          <table class="chain-grid">
            <thead>
              <tr>
                <th class="chain-th-ce">CE</th>
                <th class="chain-th-strike">Strike</th>
                <th class="chain-th-pe">PE</th>
              </tr>
            </thead>
            <tbody>
              {#each chainStrikes as k (k)}
                <tr>
                  <td class="chain-td-ce">
                    <button type="button" class="chain-btn chain-btn-ce"
                            title="Add {k} CE as a {chainSide} leg"
                            onclick={() => addChainLeg(k, 'CE')}>
                      + CE
                    </button>
                  </td>
                  <td class="chain-td-strike">{k.toFixed(0)}</td>
                  <td class="chain-td-pe">
                    <button type="button" class="chain-btn chain-btn-pe"
                            title="Add {k} PE as a {chainSide} leg"
                            onclick={() => addChainLeg(k, 'PE')}>
                      + PE
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <div class="text-[0.6rem] text-[#7e97b8] italic mt-2">
          No strikes for {chainUnderlying} expiring {chainExpiry || '(pick expiry)'}.
          Try a different underlying or expiry.
        </div>
      {/if}
    </div>
  {/if}

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
          <div class="opt-block-h">
            Greeks (position)
            <InfoHint popup text={'Sum of every leg\'s signed-qty Greeks. Δ tells you the net directional exposure; Θ shows the daily decay (positive when you\'re net short premium); 𝒱 shows your sensitivity to a 1 % IV move (positive = long volatility).'} />
          </div>
          <div class="opt-kv">
            <span class="kv-k">
              Δ delta
              <InfoHint popup text={'Net directional exposure. +50 ≈ "₹50 gained per ₹1 spot rise". 0 ≈ delta-neutral.'} />
            </span>
            <span class="kv-v">{fmtNum(strategy.aggregate_greeks.delta, 1)}</span>
            <span class="kv-k">
              Γ gamma
              <InfoHint popup text={'How fast delta changes as spot moves. Positive = delta helps you on big moves either way; negative = delta hurts more as spot drifts.'} />
            </span>
            <span class="kv-v">{fmtNum(strategy.aggregate_greeks.gamma, 4)}</span>
            <span class="kv-k">
              Θ theta /d
              <InfoHint popup text={'Daily decay in rupees. Credit spreads / iron condors show positive theta (you collect time value); debit spreads / long premium show negative.'} />
            </span>
            <span class="kv-v {strategy.aggregate_greeks.theta < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.theta, 0)}</span>
            <span class="kv-k">
              𝒱 vega /1%IV
              <InfoHint popup text={'P&L change per 1 % IV move. Long volatility (long straddles, calendar spreads) = positive vega; short volatility (iron condors, naked shorts) = negative.'} />
            </span>
            <span class="kv-v {strategy.aggregate_greeks.vega < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.vega, 0)}</span>
            <span class="kv-k">
              ρ rho /1%r
              <InfoHint popup text={'Sensitivity to a 1 % rate change. Cosmetic for short- dated index options; matters for long-dated singles.'} />
            </span>
            <span class="kv-v">{fmtNum(strategy.aggregate_greeks.rho, 0)}</span>
          </div>
        </div>

        <div class="opt-block">
          <div class="opt-block-h">
            Risk &amp; expected value
            <InfoHint popup text={'Aggregate risk + expected value across all legs. Probability-weighted outcomes integrated against the lognormal pdf of the underlying using a qty-weighted IV proxy. POP × magnitudes captures the asymmetry that POP alone misses.'} />
          </div>
          <div class="opt-kv">
            <span class="kv-k">
              Max profit*
              <InfoHint popup text={'Largest possible payoff at expiry, within the spot range we charted (±2.5σ by default). Asterisk because strategies with an unbounded leg (long calls, short puts) clip at the chart edge.'} />
            </span>
            <span class="kv-v kv-pos">{fmtMoney(strategy.risk.max_profit, false)}</span>
            <span class="kv-k">
              Max loss*
              <InfoHint popup text={'Largest loss at expiry within the spot range charted. Asterisk for the same reason as Max profit.'} />
            </span>
            <span class="kv-v kv-neg">{fmtMoney(strategy.risk.max_loss, true)}</span>
            <span class="kv-k">
              R:R
              <InfoHint popup text={'<b>Risk-to-reward</b> = max_profit / |max_loss|. "1 : 0.5" = risk ₹100 to make ₹50. "1 : 3" = risk ₹100 to make ₹300. <b>—</b> when one side is unbounded.'} />
            </span>
            <span class="kv-v">{strategy.risk.rr_ratio == null ? '—' : `1 : ${strategy.risk.rr_ratio.toFixed(2)}`}</span>
            <span class="kv-k">
              Breakevens
              <InfoHint popup text={'Spot prices at expiry where the strategy\'s P&L crosses zero. Iron condors and butterflies have 2 (one upper, one lower); verticals have 1; fully ITM/OTM 0.'} />
            </span>
            <span class="kv-v">
              {#if strategy.risk.breakevens.length}
                {strategy.risk.breakevens.map(/** @param {number} b */ (b) => `₹${b.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`).join(' / ')}
              {:else}—{/if}
            </span>
            <span class="kv-k">
              POP
              <InfoHint popup text={'<b>Probability of profit</b> at expiry — sum of lognormal mass over every contiguous profitable region of the payoff curve. <br>For range strategies (iron condors), this measures "P(spot ends inside the wings)".'} />
            </span>
            <span class="kv-v {strategy.risk.pop > 0.6 ? 'kv-pos' : strategy.risk.pop < 0.4 ? 'kv-neg' : ''}">{fmtPct(strategy.risk.pop)}</span>
            <span class="kv-k">
              EV
              <InfoHint popup text={'<b>Expected value</b> — POP × win-magnitude − (1−POP) × loss-magnitude, integrated against the lognormal pdf of the underlying. <br>Positive EV = the strategy has edge in expectation; negative EV = it doesn\'t, even if POP is high.'} />
            </span>
            <span class="kv-v {strategy.risk.ev > 0 ? 'kv-pos' : strategy.risk.ev < 0 ? 'kv-neg' : ''}">{fmtMoney(strategy.risk.ev)}</span>
            {#if strategy.risk.ev_pct != null}
              <span class="kv-k">
                EV / cost
                <InfoHint popup text={'EV expressed as a percentage of |net cost| — return on capital expectation. +5 % = "on average, my outlay returns 5 % of itself per cycle".'} />
              </span>
              <span class="kv-v {strategy.risk.ev_pct > 0 ? 'kv-pos' : strategy.risk.ev_pct < 0 ? 'kv-neg' : ''}">
                {strategy.risk.ev_pct > 0 ? '+' : ''}{strategy.risk.ev_pct.toFixed(1)}%
              </span>
            {/if}
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
  {/if}

  <!-- Candidate positions panel — every option / future on the picked
       underlying held in one of the chosen accounts. Sits below the
       payoff chart so the operator can scan the working set, uncheck a
       row to drop it from the strategy, and re-Analyze. Stays visible
       even before the chart loads so the operator sees what they're
       working with from the moment they pick an underlying. -->
  {#if selectedUnderlying}
    <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
      <div class="opt-section-h" style="padding-bottom: 0.5rem;">
        Candidates
        <span class="opt-section-tag tag-deriv">{selectedUnderlying}</span>
        <span class="opt-section-meta">
          {candidatePositions.length} matching {selectedAccounts.length ? 'in chosen accounts' : 'across all accounts'} ·
          uncheck to drop a leg from the strategy
        </span>
      </div>
      {#if candidatePositions.length}
        <div class="cand-grid">
          <div class="cand-headrow">
            <span></span>
            <span>Symbol</span>
            <span>Account</span>
            <span>Kind</span>
            <span class="num">Qty</span>
            <span class="num">Avg cost</span>
            <span class="num">LTP</span>
            <span class="num">P&amp;L</span>
            <span>Source</span>
          </div>
          {#each candidatePositions as c (c.source + '|' + c.account + '|' + c.symbol)}
            {@const pnl = (c.ltp != null && c.avg_cost != null) ? (c.ltp - c.avg_cost) * c.qty : null}
            <label class="cand-row" class:cand-disabled={enabledSymbols[c.symbol] === false}>
              <input type="checkbox"
                     checked={enabledSymbols[c.symbol] !== false}
                     onchange={(e) => {
                       const next = { ...enabledSymbols };
                       next[c.symbol] = /** @type {HTMLInputElement} */ (e.currentTarget).checked;
                       enabledSymbols = next;
                     }} />
              <span class="font-mono">{c.symbol}</span>
              <span class="font-mono">{c.account}</span>
              <span class="cand-kind cand-kind-{c.kind}">{c.kind === 'fut' ? 'FUT' : (/CE$/i.test(c.symbol) ? 'CE' : 'PE')}</span>
              <span class="num {c.qty < 0 ? 'kv-neg' : 'kv-pos'}">{c.qty > 0 ? '+' : ''}{c.qty}</span>
              <span class="num">{c.avg_cost != null ? '₹' + c.avg_cost.toFixed(2) : '—'}</span>
              <span class="num">{c.ltp != null ? '₹' + c.ltp.toFixed(2) : '—'}</span>
              <span class="num {pnl == null ? '' : pnl >= 0 ? 'kv-pos' : 'kv-neg'}">
                {pnl == null ? '—' : (pnl >= 0 ? '+' : '−') + '₹' + Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </span>
              <span class="leg-source leg-source-{c.source}">{c.source}</span>
            </label>
          {/each}
        </div>
      {:else}
        <div class="text-[0.6rem] text-[#7e97b8] italic">
          No options or futures on <b>{selectedUnderlying}</b> in
          {selectedAccounts.length ? 'the chosen accounts' : 'any account'}.
          Try a different underlying / account, or use the option-chain picker
          below to add hypothetical legs.
        </div>
      {/if}
    </div>
  {/if}

  {#if strategy}
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
              <td>
                Δ delta
                <InfoHint popup text={'<b>Delta</b> — change in option value per ₹1 change in spot. <br>Long calls: 0 (deep OTM) → 1 (deep ITM). Long puts: 0 → −1. <br>Position-scaled = Δ × signed qty (a short call has negative position-delta). <br>Use it as a directional exposure proxy: position-delta +50 means the book gains ₹50 per ₹1 spot rise.'} />
              </td>
              <td class="num">{fmtNum(analytics.greeks_per_share.delta, 4)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.delta, 1)}</td>
            </tr>
            <tr>
              <td>
                Γ gamma
                <InfoHint popup text={'<b>Gamma</b> — rate-of-change of delta per ₹1 spot move. <br>Long options have positive gamma (delta accelerates in your favour as spot moves); short options negative. <br>ATM near expiry has the highest gamma — small spot moves whip P&L.'} />
              </td>
              <td class="num">{fmtNum(analytics.greeks_per_share.gamma, 6)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.gamma, 4)}</td>
            </tr>
            <tr>
              <td>
                Θ theta /d
                <InfoHint popup text={'<b>Theta</b> — daily time-decay in rupees. <br>Long options: negative (you bleed premium each day). Short options: positive (you collect time value). <br>Position theta of −150 means "this position loses ₹150 per calendar day, holding spot + IV constant".'} />
              </td>
              <td class="num kv-neg">{fmtNum(analytics.greeks_per_share.theta, 2)}</td>
              <td class="num kv-neg">{fmtNum(analytics.greeks_position.theta, 0)}</td>
            </tr>
            <tr>
              <td>
                𝒱 vega /1%IV
                <InfoHint popup text={'<b>Vega</b> — change in option value per <b>1 percentage point</b> of IV. <br>Long options: positive vega (you benefit when IV expands). Short: negative. <br>Position vega of +200 means "if IV rises 1 % across the curve, this position gains ₹200".'} />
              </td>
              <td class="num">{fmtNum(analytics.greeks_per_share.vega, 2)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.vega, 0)}</td>
            </tr>
            <tr>
              <td>
                ρ rho /1%r
                <InfoHint popup text={'<b>Rho</b> — sensitivity to a 1 % change in the risk-free rate. <br>Mostly cosmetic for short-dated index options; matters for long-dated single-stock options where carry has time to compound.'} />
              </td>
              <td class="num">{fmtNum(analytics.greeks_per_share.rho, 2)}</td>
              <td class="num">{fmtNum(analytics.greeks_position.rho, 0)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="opt-block">
        <div class="opt-block-h">
          Risk &amp; expected value
          <InfoHint popup text={'Probability-weighted outcome metrics. POP tells you how often you win; EV captures the win/loss magnitudes; R:R is the asymmetry. All evaluated against the lognormal distribution of underlying spot at expiry, using the IV calibrated above.'} />
        </div>
        <div class="opt-kv">
          <span class="kv-k">
            Max profit
            <InfoHint popup text={'Largest possible payoff for this position at expiry. ∞ for long calls and short puts (one side is unbounded).'} />
          </span>
          <span class="kv-v kv-pos">{analytics.risk.max_profit == null ? '∞' : fmtMoney(analytics.risk.max_profit, false)}</span>
          <span class="kv-k">
            Max loss
            <InfoHint popup text={'Largest possible loss at expiry. ∞ for short calls and long futures-like positions. Always shown as a negative rupee figure.'} />
          </span>
          <span class="kv-v kv-neg">{analytics.risk.max_loss == null ? '∞' : fmtMoney(-analytics.risk.max_loss)}</span>
          <span class="kv-k">
            R:R
            <InfoHint popup text={'<b>Risk-to-reward ratio</b> — max_profit / |max_loss|, displayed as <code>1 : N</code>. "1 : 0.5" means you risk ₹100 to make ₹50. "1 : 3" means risk ₹100 to make ₹300. Shown as <b>—</b> when one side is unbounded.'} />
          </span>
          <span class="kv-v">{analytics.risk.rr_ratio == null ? '—' : `1 : ${analytics.risk.rr_ratio.toFixed(2)}`}</span>
          <span class="kv-k">
            Breakeven
            <InfoHint popup text={'Spot price at expiry where the position\'s P&L is zero. Above (CE) or below (PE) breakeven, you\'re in profit.'} />
          </span>
          <span class="kv-v">₹{analytics.risk.breakeven.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span>
          <span class="kv-k">
            POP
            <InfoHint popup text={'<b>Probability of profit</b> — the chance the position lands in the green at expiry, computed from the lognormal distribution of spot using the calibrated IV. <br>Green when &gt; 60 %, red when &lt; 40 %. <br>POP alone is misleading without EV — a 95 % POP that risks ₹50k to make ₹500 is worse than a 40 % POP that risks ₹10k to make ₹50k.'} />
          </span>
          <span class="kv-v {analytics.risk.pop > 0.6 ? 'kv-pos' : analytics.risk.pop < 0.4 ? 'kv-neg' : ''}">{fmtPct(analytics.risk.pop)}</span>
          <span class="kv-k">
            EV
            <InfoHint popup text={'<b>Expected value</b> — what the position is worth on average, weighting every spot outcome at expiry by its lognormal probability density. POP × win-magnitude − (1−POP) × loss-magnitude, integrated over the curve. <br>Positive EV = the trade has edge in expectation. Negative EV = it doesn\'t, even if POP is high.'} />
          </span>
          <span class="kv-v {analytics.risk.ev > 0 ? 'kv-pos' : analytics.risk.ev < 0 ? 'kv-neg' : ''}">{fmtMoney(analytics.risk.ev)}</span>
          {#if analytics.risk.ev_pct != null}
            <span class="kv-k">
              EV / cost
              <InfoHint popup text={'EV expressed as a percentage of the absolute cost basis — return-on-capital expectation. +5 % = "on average, my ₹100 outlay returns ₹5".'} />
            </span>
            <span class="kv-v {analytics.risk.ev_pct > 0 ? 'kv-pos' : analytics.risk.ev_pct < 0 ? 'kv-neg' : ''}">
              {analytics.risk.ev_pct > 0 ? '+' : ''}{analytics.risk.ev_pct.toFixed(1)}%
            </span>
          {/if}
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
    {:else if historical && !historical.bars.length}
      <div class="text-[0.6rem] text-[#7e97b8] px-1 italic">
        No historical bars available for {analytics.symbol}
        — this contract may be too new, illiquid, or outside the
        broker's instrument cache. Payoff above is unaffected.
      </div>
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
  .kv-k {
    color: #7e97b8;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    /* Narrow labels mean the popup info chip stays close to the
       label text without inflating the column width. */
    flex-wrap: nowrap;
  }
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
  /* Allow popup InfoHint chips to sit inline next to Greek labels in
     the per-share/position table without breaking the row baseline. */
  .opt-table td:first-child {
    display: flex;
    align-items: center;
    gap: 0.3rem;
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

  /* Candidate position toggle list — same monospace look as the leg
     grid but read-only fields (no inputs). Checkbox on the left;
     unchecking dims the row to signal "excluded from strategy". */
  .cand-grid {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    margin-top: 0.4rem;
  }
  .cand-headrow,
  .cand-row {
    display: grid;
    grid-template-columns:
      auto                /* checkbox */
      minmax(0, 2.4fr)    /* symbol */
      minmax(0, 0.9fr)    /* account */
      minmax(0, 0.5fr)    /* kind */
      minmax(0, 0.6fr)    /* qty */
      minmax(0, 0.9fr)    /* avg cost */
      minmax(0, 0.9fr)    /* ltp */
      minmax(0, 1fr)      /* pnl */
      minmax(0, 0.7fr);   /* source */
    gap: 0.4rem;
    align-items: center;
    font-size: 0.62rem;
    font-family: monospace;
  }
  .cand-headrow {
    font-size: 0.55rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding-bottom: 0.15rem;
    border-bottom: 1px solid rgba(251,191,36,0.18);
  }
  .cand-row {
    padding: 0.2rem 0.3rem;
    border-radius: 3px;
    cursor: pointer;
    transition: background 0.1s;
  }
  .cand-row:hover { background: rgba(251,191,36,0.05); }
  .cand-row input[type="checkbox"] {
    accent-color: #fbbf24;
    width: 0.9rem;
    height: 0.9rem;
    cursor: pointer;
  }
  .cand-disabled {
    opacity: 0.45;
  }
  .cand-disabled:hover { background: rgba(248,113,113,0.05); }
  .cand-kind {
    text-align: center;
    font-weight: 700;
    font-size: 0.55rem;
    letter-spacing: 0.05em;
  }
  .cand-kind-fut { color: #c084fc; }
  .cand-kind-opt { color: #7dd3fc; }

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

  /* Option-chain picker — three-column controls (Underlying / Expiry /
     Side) above a CE-strike-PE table. Each row shows one strike with
     Add-leg buttons on either side. Capped height so the page doesn't
     scroll into oblivion when an underlying has 100+ strikes. */
  .chain-controls {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr);
    gap: 0.4rem 0.5rem;
    margin-bottom: 0.5rem;
  }
  @media (max-width: 600px) {
    .chain-controls { grid-template-columns: 1fr; }
  }
  .chain-field {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  /* Futures quick-add row above the strike grid. Same general look as
     the chain CE/PE buttons but tagged sky-blue so it's visually
     distinct from the green/red option buttons below. */
  .chain-futures {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
    margin-bottom: 0.4rem;
    padding: 0.3rem 0.5rem;
    background: rgba(125,211,252,0.05);
    border: 1px solid rgba(125,211,252,0.20);
    border-radius: 3px;
  }
  .chain-futures-label {
    font-family: monospace;
    font-size: 0.55rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #7e97b8;
    margin-right: 0.25rem;
  }
  .chain-fut-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-family: monospace;
    font-size: 0.6rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 2px;
    border: 1px solid rgba(125,211,252,0.45);
    background: rgba(125,211,252,0.08);
    color: #7dd3fc;
    cursor: pointer;
    letter-spacing: 0.03em;
    transition: background 0.12s;
  }
  .chain-fut-pill:hover {
    background: rgba(125,211,252,0.18);
    border-color: rgba(125,211,252,0.65);
  }
  .chain-fut-meta {
    color: #7e97b8;
    font-weight: 400;
    font-size: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .chain-grid-wrap {
    max-height: 18rem;
    overflow-y: auto;
    border: 1px solid rgba(251,191,36,0.18);
    border-radius: 3px;
    background: rgba(0,0,0,0.10);
  }
  .chain-grid {
    width: 100%;
    border-collapse: collapse;
    font-family: monospace;
    font-size: 0.65rem;
  }
  .chain-grid th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: rgba(251,191,36,0.10);
    color: #7e97b8;
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.55rem;
    letter-spacing: 0.04em;
    padding: 0.25rem 0.4rem;
    border-bottom: 1px solid rgba(251,191,36,0.25);
  }
  .chain-th-ce     { text-align: left; color: #22c55e; }
  .chain-th-pe     { text-align: right; color: #f87171; }
  .chain-th-strike { text-align: center; color: #c8d8f0; }
  .chain-grid td {
    padding: 0.18rem 0.4rem;
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .chain-grid tr:last-child td { border-bottom: 0; }
  .chain-td-ce      { text-align: left; }
  .chain-td-pe      { text-align: right; }
  .chain-td-strike  { text-align: center; color: #c8d8f0; font-weight: 700; }
  .chain-btn {
    font-family: monospace;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 1px 8px;
    border-radius: 2px;
    border: 1px solid currentColor;
    background: transparent;
    cursor: pointer;
    letter-spacing: 0.04em;
    transition: background 0.12s;
  }
  .chain-btn-ce { color: #22c55e; }
  .chain-btn-pe { color: #f87171; }
  .chain-btn-ce:hover { background: rgba(34,197,94,0.10); }
  .chain-btn-pe:hover { background: rgba(248,113,113,0.10); }
  /* "chain" source pill on legs added via the chain picker — sky-blue
     to distinguish from manual / live / sim. */
  .leg-source-chain { color: #c084fc; }
</style>
