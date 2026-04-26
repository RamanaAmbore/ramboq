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

  import { onMount, onDestroy, untrack } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, visibleInterval } from '$lib/stores';
  import {
    fetchPositions, fetchSimStatus, fetchStrategyAnalytics,
  } from '$lib/api';
  import OptionsPayoff from '$lib/OptionsPayoff.svelte';
  import Select        from '$lib/Select.svelte';
  import MultiSelect   from '$lib/MultiSelect.svelte';
  import InfoHint      from '$lib/InfoHint.svelte';
  import {
    loadInstruments, suggestUnderlyings,
    listExpiries, listStrikes, findOption,
    listFutures,
  } from '$lib/data/instruments';

  // Source card semantics (v4): no more single-vs-multi distinction.
  // Everything is multi-leg. One leg analyses fine through the strategy
  // endpoint; the operator just sees the same payoff + Greeks + risk
  // panel regardless of how many legs are checked.
  //
  // Data source is auto-detected: when a sim is running, the page works
  // off sim positions; otherwise it works off live broker positions.
  // Drafts (operator-typed hypothetical positions) layer on top in
  // either case.
  /** @type {any} */ let strategy   = $state(null);
  let strategyErr   = $state('');
  let loading       = $state(false);
  let teardown;
  let posTeardown;
  let simTeardown;

  // Sim status — when true, the candidates panel shows sim positions
  // instead of live. Polled every few seconds.
  let simActive = $state(false);

  // "+ Add" panel toggle — when on, the option-chain picker opens to
  // let the operator browse strikes for the underlying and drop legs
  // into Drafts.
  let showAddPanel = $state(false);

  // Drafts — hypothetical positions the operator types in. They sit
  // beside live + sim positions in the Candidates panel and feed into
  // either single-leg or strategy analytics. `id` is a stable client-
  // side key so the panel rows don't lose their state when one is
  // removed mid-edit.
  let _draftSeq = 0;
  /** @type {Array<{id:number, symbol:string, qty:number|'', avg_cost:number|'', ltp:number|''}>} */
  let drafts = $state([]);
  function addDraft() {
    drafts = [...drafts, { id: ++_draftSeq, symbol: '', qty: '', avg_cost: '', ltp: '' }];
  }
  function removeDraft(/** @type {number} */ id) {
    drafts = drafts.filter(d => d.id !== id);
  }

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

  // Legs sent to the strategy endpoint — built from candidate positions
  // (live or sim, depending on simActive) plus drafts that match the
  // selected underlying, intersected with the operator's checked rows
  // in the Candidates panel.
  /** @type {Array<{symbol:string, qty:any, avg_cost:any, ltp:any, source:string}>} */
  let legs = $state([]);

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

  // Candidate positions matching the filter. Live + sim positions on
  // the chosen underlying held in one of the chosen accounts, plus all
  // drafts whose symbol matches the underlying prefix. Source is a
  // per-row property (badge in the panel), not a mode-level filter.
  /** @type {{symbol:string,account:string,qty:number,avg_cost:number|null,ltp:number|null,source:string,kind:string,draftId?:number}[]} */
  const candidatePositions = $derived.by(() => {
    if (!selectedUnderlying) return [];
    const target = selectedUnderlying.toUpperCase();
    /** @type {string[]} */
    const acctFilter = selectedAccounts.length ? selectedAccounts : [];
    /** @type {any[]} */
    const out = [];
    // Source filter — when a sim is active, work off the sim book only;
    // otherwise the live book. Drafts are always visible regardless.
    const wantedSource = simActive ? 'sim' : 'live';
    for (const p of positions) {
      if (p.source !== wantedSource) continue;
      if (acctFilter.length && !acctFilter.includes(p.account)) continue;
      const sym = p.symbol;
      if (!new RegExp(`^${target}\\d`, 'i').test(sym)) continue;
      const isFut = /FUT$/i.test(sym);
      const isOpt = /(CE|PE)$/i.test(sym);
      if (!isFut && !isOpt) continue;
      out.push({
        ...p,
        kind: isFut ? 'fut' : 'opt',
      });
    }
    // Drafts — matched by symbol prefix; no account filter (drafts
    // aren't tied to a broker account).
    for (const d of drafts) {
      const sym = String(d.symbol || '').toUpperCase();
      if (!sym) continue;
      if (!new RegExp(`^${target}\\d`, 'i').test(sym)) continue;
      const isFut = /FUT$/i.test(sym);
      const isOpt = /(CE|PE)$/i.test(sym);
      if (!isFut && !isOpt) continue;
      const qty = d.qty === '' || d.qty == null ? 0 : Number(d.qty);
      const cost = d.avg_cost === '' || d.avg_cost == null ? null : Number(d.avg_cost);
      const ltp  = d.ltp      === '' || d.ltp      == null ? null : Number(d.ltp);
      out.push({
        symbol: sym,
        account: '',
        qty,
        avg_cost: cost,
        ltp,
        source: 'draft',
        kind: isFut ? 'fut' : 'opt',
        draftId: d.id,
      });
    }
    return out;
  });

  // Initialize the enable-flag map when candidates change. Default:
  // every candidate enabled (operator sees their book in the payoff
  // immediately; un-checks to drop a leg).
  // ── untrack the read of `enabledSymbols` so this effect re-runs only
  //    when the candidate set itself changes; otherwise the assignment
  //    on line below would re-trigger this effect → infinite loop hang.
  $effect(() => {
    const cands = candidatePositions;
    untrack(() => {
      /** @type {Record<string, boolean>} */
      const next = {};
      let changed = false;
      const prevKeys = Object.keys(enabledSymbols);
      if (prevKeys.length !== cands.length) changed = true;
      for (const c of cands) {
        if (!(c.symbol in enabledSymbols)) changed = true;
        next[c.symbol] = (c.symbol in enabledSymbols)
          ? enabledSymbols[c.symbol]
          : true;
      }
      // Skip the write entirely when nothing meaningful changed —
      // assigning a new ref would still trigger downstream effects.
      if (changed) enabledSymbols = next;
    });
  });

  // Rebuild legs from the current candidates × enabled-flag combination.
  // Drafts already live in candidatePositions (with source='draft'),
  // so this single derivation covers live + sim + draft uniformly.
  $effect(() => {
    void candidatePositions; void enabledSymbols;
    untrack(() => {
      legs = candidatePositions
        .filter(c => enabledSymbols[c.symbol] !== false)
        .map(c => ({
          symbol:   c.symbol,
          qty:      c.qty,
          avg_cost: c.avg_cost ?? '',
          ltp:      c.ltp ?? '',
          source:   c.source,
        }));
    });
  });

  // Auto-trigger strategy analytics whenever the leg set changes — no
  // explicit Analyze button needed.
  $effect(() => {
    void legs;
    untrack(() => loadStrategy());
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

  // Auto-pick first expiry when chain underlying changes.
  $effect(() => {
    void chainUnderlying;
    if (chainExpiries.length && !chainExpiries.includes(chainExpiry)) {
      chainExpiry = chainExpiries[0];
    }
  });

  // Chain "+" button handlers — drop the picked contract into Drafts.
  // The Drafts panel surfaces editable rows; whatever lands here can be
  // fine-tuned (qty / cost / ltp) before the next strategy refresh.
  function addChainDraft(/** @type {number} */ strike,
                         /** @type {'CE'|'PE'} */ optType) {
    if (!chainUnderlying || !chainExpiry) return;
    const inst = findOption(chainUnderlying.toUpperCase(), optType, strike, chainExpiry);
    if (!inst) return;
    const lot = Number(inst.ls || 1);
    const signedQty = chainSide === 'long' ? lot : -lot;
    drafts = [...drafts, {
      id: ++_draftSeq, symbol: inst.s, qty: signedQty, avg_cost: '', ltp: '',
    }];
    // Auto-align the page underlying so the new draft shows in
    // candidates immediately.
    if (!selectedUnderlying) selectedUnderlying = chainUnderlying.toUpperCase();
  }
  function addFutureDraft(/** @type {string} */ sym,
                          /** @type {number} */ lotSize) {
    if (!sym) return;
    const lot = Number(lotSize || 1);
    const signedQty = chainSide === 'long' ? lot : -lot;
    drafts = [...drafts, {
      id: ++_draftSeq, symbol: sym, qty: signedQty, avg_cost: '', ltp: '',
    }];
    if (!selectedUnderlying) selectedUnderlying = chainUnderlying.toUpperCase();
  }

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

  async function loadSimStatus() {
    try {
      const s = await fetchSimStatus();
      simActive = !!s?.active;
    } catch (_) { simActive = false; }
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
    loadSimStatus();
    teardown    = visibleInterval(loadStrategy,  5000);
    posTeardown = visibleInterval(loadPositions, 30000);
    simTeardown = visibleInterval(loadSimStatus,  5000);
  });
  onDestroy(() => { teardown?.(); posTeardown?.(); simTeardown?.(); });

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

</script>

<svelte:head><title>Options Analytics | RamboQuant Analytics</title></svelte:head>

<div class="page-header">
  <h1 class="page-title-chip">Options Analytics</h1>
  <InfoHint text={'Pick an underlying to load every option / future on it from your ' + (simActive ? '<b>simulator</b> book' : '<b>live</b> book') + '. The payoff diagram below charts the aggregated position; uncheck a row in the Candidates panel to drop it from the payoff. Click <b>+ Add</b> to open the option chain and pick draft strikes (modelled as hypothetical positions). Stats below the chart explain themselves — click any <span class="font-mono">(i)</span> chip for a definition.'} />
  <span class="algo-ts">{clientTimestamp()}</span>
  {#if simActive}
    <span class="opt-mode-pill opt-mode-sim" title="A simulator run is active. Candidates and analytics are sourced from the sim book.">SIMULATOR</span>
  {/if}
</div>

<!-- Picker bar — two dropdowns + a "+" toggle for the option-chain
     picker. Strategy auto-recomputes whenever the leg set changes;
     no Analyze button needed. -->
<div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
  <div class="opt-picker">
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
    <button type="button"
            class="opt-add-btn"
            class:opt-add-btn-on={showAddPanel}
            title={showAddPanel ? 'Close the option chain picker' : 'Open the option chain to add draft positions'}
            aria-label={showAddPanel ? 'Close picker' : 'Open picker'}
            onclick={() => showAddPanel = !showAddPanel}>{showAddPanel ? '−' : '+'}</button>
  </div>
</div>

{#if strategyErr}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">{strategyErr}</div>
{/if}

{#if !strategy && !strategyErr && !loading && !selectedUnderlying && !drafts.length}
  <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
    Pick an underlying to surface {simActive ? 'sim' : 'live'} candidates, or click
    <b>+ Add</b> to drop a draft strike into the payoff.
  </div>
{/if}

<!-- Drafts editor — operator-typed hypothetical positions. Each row has
     editable symbol/qty/avg_cost/ltp + a delete. Drafts whose symbol
     matches the selected underlying also appear (read-only) in the
     Candidates panel below so they can be picked / checked alongside
     live + sim positions. -->
{#if drafts.length}
  <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
    <div class="opt-section-h" style="padding-bottom: 0.5rem;">
      Drafts <span class="opt-section-meta">({drafts.length}) — hypothetical positions; appear in Candidates when their symbol matches the underlying</span>
    </div>
    <div class="leg-grid">
      <div class="leg-headrow">
        <span>Symbol</span>
        <span>Qty</span>
        <span>Avg cost</span>
        <span>LTP</span>
        <span>Source</span>
        <span></span>
      </div>
      {#each drafts as _d, i (drafts[i].id)}
        <div class="leg-row">
          <input type="text" class="field-input"
            placeholder="NIFTY25APR22000CE"
            bind:value={drafts[i].symbol} />
          <input type="number" class="field-input"
            placeholder="±qty"
            bind:value={drafts[i].qty} />
          <input type="number" class="field-input"
            placeholder="₹"
            step="0.05"
            bind:value={drafts[i].avg_cost} />
          <input type="number" class="field-input"
            placeholder="₹ (auto from broker)"
            step="0.05"
            bind:value={drafts[i].ltp} />
          <span class="leg-source leg-source-draft">draft</span>
          <button type="button" class="leg-del"
                  title="Remove this draft"
                  onclick={() => removeDraft(drafts[i].id)}>×</button>
        </div>
      {/each}
    </div>
  </div>
{/if}

<!-- ───── Option-chain picker — opens via "+ Add" button ───────────────
     Browse strikes for the chosen underlying and click +CE / +PE / a
     futures pill to drop a draft into the Drafts panel. Drafts that
     match the page's selected underlying then auto-show in Candidates,
     re-running the strategy analytics with the new leg included. -->
{#if showAddPanel}
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
                    onclick={() => addFutureDraft(f.s, f.ls)}>
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
                            onclick={() => addChainDraft(k, 'CE')}>
                      + CE
                    </button>
                  </td>
                  <td class="chain-td-strike">{k.toFixed(0)}</td>
                  <td class="chain-td-pe">
                    <button type="button" class="chain-btn chain-btn-pe"
                            title="Add {k} PE as a {chainSide} leg"
                            onclick={() => addChainDraft(k, 'PE')}>
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

<!-- Candidates — sits immediately under the payoff chart so the
     operator can scan the working set + uncheck rows to drop them
     from the payoff, all without scrolling away from the chart.
     Replaces the old Per-leg breakdown card (the same backend data
     showed twice, once with checkboxes here and once read-only
     below). Horizontal + vertical overflow scrolling so wide rows
     and long lists never break the card layout. -->
{#if selectedUnderlying || drafts.length}
  <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
    <div class="opt-section-h" style="padding-bottom: 0.5rem;">
      Candidates
      {#if selectedUnderlying}
        <span class="opt-section-tag tag-deriv">{selectedUnderlying}</span>
      {/if}
      <span class="opt-section-meta">
        {candidatePositions.length} matching {selectedAccounts.length ? 'in chosen accounts' : 'across all accounts'} ·
        uncheck to drop a leg from the payoff
      </span>
    </div>
    {#if candidatePositions.length}
      <div class="cand-scroll">
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
      </div>
    {:else}
      <div class="text-[0.6rem] text-[#7e97b8] italic">
        No options or futures on <b>{selectedUnderlying}</b> in
        {selectedAccounts.length ? 'the chosen accounts' : 'any account'}.
        Try a different underlying / account, or click <b>+</b> to drop a
        draft strike into the payoff.
      </div>
    {/if}
  </div>
{/if}

  {#if !strategy && !strategyErr && !legs.length}
    <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
      No legs yet. Pick an underlying above to surface candidates, or click
      <b>+</b> to drop a draft strike into the payoff.
    </div>
  {/if}


<style>
  /* Picker bar — Account + Underlying + + Add fit on a single row at
     all reasonable viewport widths. Account values are short (ZG####
     codes, 6 chars) and Underlying values are short (NIFTY, BANKNIFTY,
     up to ~12 chars), so each control claims a modest min-width. The
     row only wraps below ~520px viewport, where mobile layout takes
     over anyway. */
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
    min-width: 110px;
  }
  /* Account: short codes (~6 chars). Underlying: index/stock names
     (~12 chars). Both controls grow proportionally so the row fills
     available width without forcing a wrap. */
  .opt-field-grow { flex: 1; min-width: 150px; }

  /* "+" toggle button — fixed-width amber pill that sits flush at the
     end of the picker row. Square aspect so the symbol reads as a
     single glyph not a labelled button. Flips to "−" while the chain
     panel is open. */
  .opt-add-btn {
    width: 1.9rem;
    height: 1.9rem;
    flex: 0 0 auto;
    align-self: flex-end;
    margin-bottom: 1px;          /* line up baseline with the Selects */
    border-radius: 0.25rem;
    border: 1px solid rgba(251,191,36,0.5);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
    font-size: 1rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.1s, border-color 0.1s, color 0.1s;
  }
  .opt-add-btn:hover {
    background: rgba(251,191,36,0.22);
    border-color: rgba(251,191,36,0.75);
  }
  .opt-add-btn-on {
    background: #fbbf24;
    color: #0c1830;
    border-color: #fbbf24;
  }

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
  .leg-source-draft  { color: #f0abfc; }
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

  /* Candidate position toggle list — sits immediately under the
     payoff chart. The wrapping `.cand-scroll` handles overflow:
       - horizontal: when the row is wider than the card (narrow
         viewport, long symbols), the table scrolls within the card
         instead of breaking layout
       - vertical: capped at ~16 rows; longer lists scroll inside
   */
  .cand-scroll {
    overflow-x: auto;
    overflow-y: auto;
    max-height: 22rem;
    margin-top: 0.4rem;
    /* Compact scrollbar styling — works on WebKit; falls back to
       browser default elsewhere. */
    scrollbar-width: thin;
    scrollbar-color: rgba(251,191,36,0.4) transparent;
  }
  .cand-scroll::-webkit-scrollbar { height: 6px; width: 6px; }
  .cand-scroll::-webkit-scrollbar-thumb {
    background: rgba(251,191,36,0.35);
    border-radius: 3px;
  }
  .cand-scroll::-webkit-scrollbar-thumb:hover {
    background: rgba(251,191,36,0.55);
  }
  .cand-grid {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    /* Min-width enforces a sensible row width; the wrapping
       .cand-scroll handles the horizontal overflow when the viewport
       is narrower than this. */
    min-width: 720px;
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

  /* Click-to-pick row variant — used in live / sim mode where the
     candidate is a single-select. Reset button defaults so the row
     reads as plain text not a button, then layer the pick-state styling
     on top (active row gets an amber border + bg). */
  .cand-row-btn {
    background: transparent;
    border: 1px solid transparent;
    color: inherit;
    text-align: left;
    width: 100%;
  }
  .cand-row-btn:hover { background: rgba(251,191,36,0.08); }
  .cand-row-active {
    background: rgba(251,191,36,0.15) !important;
    border-color: rgba(251,191,36,0.55);
  }
  .cand-row-disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .cand-row-disabled:hover { background: transparent; }
  .cand-bullet {
    color: #fbbf24;
    font-size: 0.75rem;
    text-align: center;
    width: 0.9rem;
    line-height: 1;
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
