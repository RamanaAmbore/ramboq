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
    fetchAccounts, fetchOptionsSpot, placeTicketOrder,
  } from '$lib/api';
  import OptionsPayoff from '$lib/OptionsPayoff.svelte';
  import OrderTicket   from '$lib/order/OrderTicket.svelte';
  import Select        from '$lib/Select.svelte';
  import MultiSelect   from '$lib/MultiSelect.svelte';
  import InfoHint      from '$lib/InfoHint.svelte';
  import {
    loadInstruments, suggestUnderlyings,
    listExpiries, listStrikes, findOption,
    listFutures, getInstrument,
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
  /** @type {string} Expiry filter (YYYY-MM-DD); '' = all expiries.
   *  When the underlying has options across multiple expiries, the
   *  strategy endpoint rejects mixed-expiry baskets — so the picker
   *  forces the operator to nominate one expiry. Auto-picked to the
   *  nearest available expiry when the underlying changes. */
  let selectedExpiry = $state('');
  /** @type {Record<string, boolean>} symbol → enabled flag */
  let enabledSymbols = $state({});

  // Legs sent to the strategy endpoint — built from candidate positions
  // (live or sim, depending on simActive) plus drafts that match the
  // selected underlying, intersected with the operator's checked rows
  // in the Candidates panel.
  /** @type {Array<{symbol:string, qty:any, avg_cost:any, ltp:any, source:string}>} */
  let legs = $state([]);

  // Legs panel collapsed/expanded — operator may want to fold it
  // away once they've vetted the basket so the chart + cards have
  // more vertical room.
  let legsOpen = $state(true);

  /** Lookup map: symbol → backend leg analytics (greeks, iv, …) from
   *  the latest strategy response. Lets the Candidates panel show
   *  per-row IV / Δ / Θ / 𝒱 without a second endpoint. */
  const legAnalyticsBySymbol = $derived.by(() => {
    /** @type {Record<string, any>} */
    const out = {};
    if (!strategy?.legs) return out;
    for (const l of strategy.legs) out[l.symbol] = l;
    return out;
  });

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

  // Auto-select the first underlying from the loaded book when the
  // page lands without a cached selection. Saves the operator a click;
  // the page is essentially useless without an underlying picked, so
  // defaulting feels right. Untrack the read of selectedUnderlying so
  // operator-driven changes don't re-trigger this.
  $effect(() => {
    void underlyingChoicesFromBook;
    untrack(() => {
      const list = underlyingChoicesFromBook;
      if (!selectedUnderlying && list.length) {
        selectedUnderlying = list[0];
      }
    });
  });

  /** Distinct expiries (YYYY-MM-DD) available on the chosen
   *  underlying — derived by looking up each loaded position's
   *  symbol in the instruments cache. Drafts contribute too. */
  const expiryChoicesForUnderlying = $derived.by(() => {
    if (!instrumentsReady || !selectedUnderlying) return [];
    const target = selectedUnderlying.toUpperCase();
    // Construct the symbol-prefix regex once per re-derivation; the
    // closure below would otherwise rebuild it for every position/draft.
    const prefixRe = new RegExp(`^${target}\\d`, 'i');
    const set = new Set();
    const consider = /** @param {string} sym */ (sym) => {
      const upper = String(sym || '').toUpperCase();
      if (!upper || !prefixRe.test(upper)) return;
      const inst = getInstrument(upper);
      if (inst?.x) set.add(inst.x);
    };
    for (const p of positions) consider(p.symbol);
    for (const d of drafts)    consider(d.symbol);
    return Array.from(set).sort();
  });

  /** Auto-pick the first expiry when the underlying changes (and
   *  drop the picked expiry if it disappears from the list). */
  $effect(() => {
    void selectedUnderlying;
    untrack(() => {
      const list = expiryChoicesForUnderlying;
      if (!list.length) {
        if (selectedExpiry) selectedExpiry = '';
        return;
      }
      if (!list.includes(selectedExpiry)) selectedExpiry = list[0];
    });
  });

  // Candidate positions matching the filter. Live + sim positions on
  // the chosen underlying held in one of the chosen accounts, plus all
  // drafts whose symbol matches the underlying prefix. Source is a
  // per-row property (badge in the panel), not a mode-level filter.
  /** @type {{symbol:string,account:string,qty:number,avg_cost:number|null,ltp:number|null,pnl?:number,source:string,kind:string,draftId?:number}[]} */
  const candidatePositions = $derived.by(() => {
    if (!selectedUnderlying) return [];
    const target = selectedUnderlying.toUpperCase();
    /** @type {string[]} */
    const acctFilter = selectedAccounts.length ? selectedAccounts : [];
    // Hoisted regexes — constructed once per re-derivation rather than
    // once per position/draft. The literal /FUT$/ and /(CE|PE)$/ are
    // already cached at parse time; the dynamic prefix regex is the
    // only one that needs hoisting.
    const prefixRe = new RegExp(`^${target}\\d`, 'i');
    /** @type {any[]} */
    const out = [];
    // Source filter — when a sim is active, work off the sim book only;
    // otherwise the live book. Drafts are always visible regardless.
    // Expiry filter — when an expiry is selected, only legs whose
    // contract expires on that date appear (strategy endpoint
    // rejects mixed-expiry baskets).
    const wantedSource = simActive ? 'sim' : 'live';
    const matchExpiry = /** @param {string} sym */ (sym) => {
      if (!selectedExpiry) return true;
      const inst = getInstrument(String(sym || '').toUpperCase());
      return inst?.x === selectedExpiry;
    };
    for (const p of positions) {
      if (p.source !== wantedSource) continue;
      if (acctFilter.length && !acctFilter.includes(p.account)) continue;
      const sym = p.symbol;
      if (!prefixRe.test(sym)) continue;
      const isFut = /FUT$/i.test(sym);
      const isOpt = /(CE|PE)$/i.test(sym);
      if (!isFut && !isOpt) continue;
      // Closed positions (qty=0) bypass the expiry filter. Their
      // contract often expired in the past, OR the instruments cache
      // has already evicted them — so matchExpiry would always reject
      // them and the row would silently disappear from the legs panel
      // even though it still shows in the dashboard positions grid.
      // Operator wanted parity with the grid: show every closed
      // position regardless of selected expiry.
      const isClosed = Number(p.qty || 0) === 0;
      if (!isClosed && !matchExpiry(sym)) continue;
      out.push({
        ...p,
        kind: isFut ? 'fut' : 'opt',
      });
    }
    // Drafts — matched by symbol prefix; no account filter (drafts
    // aren't tied to a broker account).
    for (const d of drafts) {
      const sym = String(d.symbol || '').toUpperCase();
      if (!sym || !prefixRe.test(sym)) continue;
      const isFut = /FUT$/i.test(sym);
      const isOpt = /(CE|PE)$/i.test(sym);
      if (!isFut && !isOpt) continue;
      if (!matchExpiry(sym)) continue;
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
    // Closed positions (qty=0 — Kite returns these so realised P/L
    // stays visible) sort to the END of the legs list. Live exposure
    // first, history last; stable order otherwise.
    out.sort((a, b) => {
      const ac = (Number(a?.qty || 0) === 0) ? 1 : 0;
      const bc = (Number(b?.qty || 0) === 0) ? 1 : 0;
      return ac - bc;
    });
    return out;
  });

  // Realised P&L from positions that have been closed today (qty=0,
  // pnl carries the realised number from the broker). Folded into
  // chartPnlOffset below so the payoff curve renders in sync with
  // the dashboard's per-underlying P&L.
  const realizedPnl = $derived.by(() => {
    let s = 0;
    for (const c of candidatePositions) {
      if (Number(c.qty || 0) === 0) s += Number(c.pnl || 0);
    }
    return s;
  });

  // Total chart-vs-dashboard P&L gap, applied as a vertical offset
  // to the payoff curve so the chart's TDAY at the current spot
  // matches the dashboard's per-underlying P&L exactly. Two
  // contributions:
  //
  //   1. Realised P&L from CLOSED positions (qty=0). These sit in
  //      candidatePositions but never reach the strategy endpoint
  //      (filter `l.qty` drops them) — so the BS curve from the
  //      backend doesn't account for them at all. Constant offset.
  //
  //   2. Theoretical-vs-LTP gap on OPEN legs. The backend prices
  //      each leg at Black-Scholes theoretical against a calibrated
  //      σ; the dashboard's broker pnl uses the actual market LTP.
  //      For illiquid contracts (especially MCX commodity options)
  //      these can drift several %. Per-leg gap is
  //          (ltp - theoretical) * qty
  //      and the strategy endpoint already returns ltp + theoretical
  //      per leg, so we sum locally without a second backend call.
  //
  // The combined offset shifts the entire today + expiry curves up
  // (or down) by `chartPnlOffset` rupees. At any spot, the chart
  // value ≈ what the dashboard would show if the underlying moved
  // there. At the current spot specifically, chart = dashboard ₹
  // exactly (within float-rounding).
  const chartPnlOffset = $derived.by(() => {
    let off = realizedPnl;
    for (const lg of (strategy?.legs || [])) {
      const ltp  = Number(lg?.ltp || 0);
      const theo = Number(lg?.theoretical || 0);
      const qty  = Number(lg?.qty || 0);
      if (ltp > 0 && theo > 0 && qty !== 0) {
        off += (ltp - theo) * qty;
      }
    }
    return off;
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
  // OChain kind toggle — 'opt' shows the CE/PE strike grid (default,
  // matches the existing options-trader workflow); 'fut' shows the
  // futures contracts only. Operator request: hide the futures pills
  // by default, surface them via an explicit checkbox so they don't
  // crowd the strike grid.
  let chainKind        = $state(/** @type {'opt'|'fut'} */ ('opt'));
  // chainSide stays as the (i) launcher's default leg side (long).
  // Per-row +/− buttons override on a per-pick basis (each button
  // explicitly passes its own side to addChainDraft), so the outer
  // toggle no longer carries operator-meaningful state.
  let chainSide        = $state(/** @type {'long'|'short'} */ ('long'));
  // chainLots is now only the FALLBACK qty multiplier the (i) modal
  // path uses when opening OrderTicket directly. The fast +/− path
  // owns its own per-click lots state via quickPicker below.
  let chainLots        = $state(1);

  // ── Inline quick-place picker ─────────────────────────────────────
  // Click +/− on a strike (or a futures pill) → cell collapses to an
  // inline `[B/S] [Lots#] [✓] [✕]` mini-form. Press ✓ → submits a
  // PAPER MARKET order via /api/orders/ticket directly, no modal.
  // Press ✕ or Escape → cancel; Enter → place. The (i) button is
  // the slow path (still opens the full OrderTicket).
  /** @type {null | {
   *   strike: number, optType: 'CE'|'PE'|'',
   *   side: 'long'|'short',
   *   lots: number,
   *   isFuture: boolean,
   *   sym: string|null,
   *   lotSize: number,
   * }} */
  let quickPicker      = $state(null);
  let quickPlacing     = $state(false);
  let quickError       = $state('');
  // Key of the cell that just placed successfully — drives the
  // brief inline "✓ placed" toast. Auto-clears after ~1.5 s.
  /** @type {string|null} */
  let quickJustPlaced  = $state(null);

  function _quickKeyOpt(strike, optType) { return `o:${strike}:${optType}`; }
  function _quickKeyFut(sym)             { return `f:${sym}`; }
  function isQuickActive(strike, optType) {
    return !!quickPicker
      && !quickPicker.isFuture
      && quickPicker.strike === strike
      && quickPicker.optType === optType;
  }
  function isQuickActiveFut(sym) {
    return !!quickPicker && quickPicker.isFuture && quickPicker.sym === sym;
  }
  function openQuickPicker(strike, optType, side) {
    // Look up the contract's lot size up-front so the picker can
    // surface the `(× lot N)` meta tag alongside the stepper. Falls
    // back to 0 on cache miss — the meta tag hides in that case.
    let lot = 0;
    try {
      if (chainUnderlying && chainExpiry) {
        const inst = findOption(
          chainUnderlying.toUpperCase(), optType, strike, chainExpiry,
        );
        lot = Number(inst?.ls || 0) || 0;
      }
    } catch (_) { lot = 0; }
    quickPicker = {
      strike, optType, side,
      lots: 1, isFuture: false, sym: null, lotSize: lot,
    };
    quickError      = '';
    quickJustPlaced = null;
  }
  function openQuickPickerFut(sym, lotSize, side) {
    quickPicker = {
      strike: 0, optType: '', side,
      lots: 1, isFuture: true, sym, lotSize,
    };
    quickError      = '';
    quickJustPlaced = null;
  }
  function cancelQuickPicker() {
    quickPicker = null;
    quickError  = '';
  }
  /** +/− stepper actions on the inline lots input. Floored at 1 lot
   *  (zero / negative would post a no-op order). No upper cap —
   *  operator can size as large as their margin allows; the
   *  basket_margin pre-flight on the backend rejects anything that
   *  blows the avail margin. */
  function quickStepLots(delta) {
    if (!quickPicker) return;
    const cur = Math.max(1, Math.floor(Number(quickPicker.lots) || 1));
    quickPicker.lots = Math.max(1, cur + delta);
  }
  // Esc-to-cancel for the inline quick-picker. The +/− stepper
  // buttons replaced the number input that previously hosted the
  // keydown handler; this $effect is the global equivalent so Esc
  // still bails out of an open picker even when no field has focus.
  $effect(() => {
    if (!quickPicker) return;
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Escape') { e.preventDefault(); cancelQuickPicker(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  /** Submit a paper MARKET order directly. No price field needed —
   *  the broker's market routing fills at the opposing top-of-book.
   *  Keeps the fast path truly one-click + lots; advanced limit /
   *  chase / mode / qty edits live on the (i) modal path. */
  async function quickPlace() {
    if (!quickPicker || quickPlacing) return;

    let sym, exchange, lot;
    if (quickPicker.isFuture) {
      sym = String(quickPicker.sym || '');
      const inst = getInstrument(sym.toUpperCase());
      exchange = inst?.e || 'NFO';
      lot      = Number(quickPicker.lotSize || inst?.ls || 1);
    } else {
      const inst = findOption(
        chainUnderlying.toUpperCase(),
        quickPicker.optType,
        quickPicker.strike,
        chainExpiry,
      );
      if (!inst) { quickError = 'Symbol not in instruments cache.'; return; }
      sym       = inst.s;
      exchange  = inst.e || 'NFO';
      lot       = Number(inst.ls || 1);
    }

    const lots = Math.max(1, Math.floor(Number(quickPicker.lots) || 1));
    const acct = _ticketAccountDefault();
    if (!acct) { quickError = 'No routable account selected.'; return; }

    const key = quickPicker.isFuture
      ? _quickKeyFut(sym)
      : _quickKeyOpt(quickPicker.strike, quickPicker.optType);

    quickPlacing = true;
    quickError   = '';
    try {
      await placeTicketOrder({
        mode:          'paper',
        side:          quickPicker.side === 'long' ? 'BUY' : 'SELL',
        tradingsymbol: sym,
        quantity:      lot * lots,
        exchange,
        product:       'NRML',
        order_type:    'MARKET',
        variety:       'regular',
        account:       acct,
      });
      quickJustPlaced = key;
      quickPicker     = null;
      setTimeout(() => {
        if (quickJustPlaced === key) quickJustPlaced = null;
      }, 1500);
    } catch (e) {
      quickError = String(e?.message || e || 'Place failed');
    } finally {
      quickPlacing = false;
    }
  }

  /** Underlyings the chain picker offers, in priority order:
   *  1. The page's currently-selected underlying (the operator's
   *     anchor — first thing they see).
   *  2. Underlyings already on the operator's loaded book (positions
   *     and holdings).
   *  3. Common indices + MCX commodities — quick-access bucket so
   *     the operator can pivot to a new instrument without typing.
   *  4. Everything else from the instruments cache, alphabetical.
   *  Re-derives whenever the page's selectedUnderlying, positions,
   *  or instrumentsReady changes — the chain picker always reflects
   *  the freshest book without a manual refresh. */
  const _COMMON_INDICES_AND_COMMODITIES = [
    'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX',
    'CRUDEOIL', 'CRUDEOILM', 'NATURALGAS', 'NATGASMINI',
    'GOLD', 'GOLDM', 'GOLDMINI', 'GOLDPETAL',
    'SILVER', 'SILVERM', 'SILVERMINI', 'SILVERMIC',
    'COPPER', 'ZINC', 'ZINCMINI', 'LEAD', 'LEADMINI',
    'ALUMINIUM', 'ALUMINI', 'NICKEL',
    'MENTHAOIL', 'COTTON',
  ];
  const underlyingChoices = $derived.by(() => {
    if (!instrumentsReady) return [];
    const seen = new Set();
    /** @type {string[]} */
    const out = [];
    const push = (/** @type {string|null|undefined} */ u) => {
      if (!u) return;
      const k = String(u).toUpperCase();
      if (seen.has(k)) return;
      seen.add(k);
      out.push(k);
    };
    // 1. Currently-selected underlying — top of the list.
    push(selectedUnderlying);
    // 2. Underlyings the operator already holds.
    for (const p of positions) {
      push(String(p.symbol || '').replace(/\d.*$/, ''));
    }
    // 3. Common indices + MCX commodities.
    for (const u of _COMMON_INDICES_AND_COMMODITIES) push(u);
    // 4. Everything else from the instruments cache.
    for (const u of suggestUnderlyings('', 1000)) push(u);
    return out;
  });

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

  /** Spot fetched directly via /api/options/spot for the current
   *  (chainUnderlying, chainExpiry) pair. Lets the chain picker
   *  anchor the ATM highlight + spot pill on whatever underlying
   *  the operator switches to, even when it doesn't match the
   *  page's primary underlying. Refreshes on every chain pivot
   *  (effect below). Stays null until the first fetch lands; the
   *  derived `chainSpot` falls back to strategy.spot when this is
   *  unavailable. */
  /** @type {{spot:number, source:string, prevClose:number|null} | null} */
  let chainSpotFetched = $state(null);
  let chainSpotKey = ''; // last-fetched cache key — skip duplicate calls
  $effect(() => {
    void chainUnderlying; void chainExpiry; void showAddPanel;
    untrack(() => {
      if (!showAddPanel || !chainUnderlying) {
        chainSpotFetched = null;
        chainSpotKey = '';
        return;
      }
      const key = `${chainUnderlying.toUpperCase()}|${chainExpiry || ''}`;
      if (key === chainSpotKey) return;
      chainSpotKey = key;
      const u = chainUnderlying;
      const e = chainExpiry || null;
      fetchOptionsSpot(u, e).then((r) => {
        // Race guard — operator may have flipped the picker between
        // the request and this resolution.
        if (chainSpotKey !== key) return;
        chainSpotFetched = r ? {
          spot:      Number(r.spot) || 0,
          source:    String(r.spot_source || ''),
          prevClose: r.spot_prev_close != null ? Number(r.spot_prev_close) : null,
        } : null;
      }).catch(() => {
        if (chainSpotKey !== key) return;
        // 502 / 4xx — broker unreachable. Suppress the highlight
        // rather than anchoring on a synthetic value.
        chainSpotFetched = null;
      });
    });
  });

  /** Spot for the chain underlying. Prefers the strategy response's
   *  spot when chainUnderlying matches the page's primary underlying
   *  (free, no extra round-trip); otherwise uses whatever the
   *  /options/spot fetch returned. Null when neither is available
   *  — the picker collapses the ATM highlight + spot pill rather
   *  than anchoring on a synthetic value. */
  const chainSpot = $derived.by(() => {
    if (!chainUnderlying) return null;
    const cU = chainUnderlying.toUpperCase();
    if (strategy) {
      const sUnd = String(strategy.underlying || '').toUpperCase();
      if (sUnd && sUnd === cU) return Number(strategy.spot) || null;
    }
    if (chainSpotFetched && chainSpotFetched.spot > 0) {
      return chainSpotFetched.spot;
    }
    return null;
  });

  /** Strike closest to the underlying spot — the ATM row. Used to
   *  highlight the row in the chain table and auto-scroll it into
   *  view when the chain opens. Null when chainSpot is unknown
   *  (different underlying or no strategy yet). */
  const chainAtmStrike = $derived.by(() => {
    if (chainSpot == null || !chainStrikes.length) return null;
    let best = chainStrikes[0];
    let bestDiff = Math.abs(best - chainSpot);
    for (const k of chainStrikes) {
      const d = Math.abs(k - chainSpot);
      if (d < bestDiff) { best = k; bestDiff = d; }
    }
    return best;
  });

  /** ATM-row DOM ref — captured via the `chainAtmRow` Svelte action
   *  attached to the ATM <tr>. The action fires when the element
   *  mounts (or remounts due to a key change), updates the ref, and
   *  the effect below scrolls it into view. Using an action sidesteps
   *  the `bind:this` constraint (which only accepts a plain
   *  identifier, not a conditional expression). */
  /** @type {HTMLTableRowElement | null} */
  let chainAtmRowEl = $state(null);
  /** Svelte action — captures the <tr> element on mount, releases it
   *  on destroy. Used in place of `bind:this` since the ATM row's
   *  identity flips between strike rows as the underlying spot moves. */
  /** @type {(node: HTMLTableRowElement) => { destroy(): void }} */
  const chainAtmRow = (node) => {
    chainAtmRowEl = node;
    return {
      destroy() { if (chainAtmRowEl === node) chainAtmRowEl = null; },
    };
  };
  $effect(() => {
    void chainAtmRowEl;
    void chainAtmStrike;
    void showAddPanel;
    if (chainAtmRowEl && showAddPanel) {
      // Defer one tick so the row has been laid out before we scroll.
      queueMicrotask(() => {
        // Scroll INSIDE .chain-grid-wrap only — earlier we used
        // rowEl.scrollIntoView({block:'center'}) which propagates up
        // every scrollable ancestor and yanks the whole page up,
        // hiding the Account / Underlying / Expiry picker bar at the
        // top of the panel. Computing scrollTop on the wrapper keeps
        // the page in place and only moves the chain grid.
        const row  = chainAtmRowEl;
        if (!row) return;
        const wrap = row.closest('.chain-grid-wrap');
        if (wrap) {
          const target = row.offsetTop - (wrap.clientHeight - row.offsetHeight) / 2;
          wrap.scrollTop = Math.max(0, target);
        } else {
          row.scrollIntoView({ block: 'nearest', behavior: 'auto' });
        }
      });
    }
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

  // Default the chain underlying to the top of the priority list
  // (selectedUnderlying when set, otherwise the operator's first
  // book underlying) once the instruments cache has loaded. Empty
  // out the picked value if it disappears from the list.
  $effect(() => {
    const list = underlyingChoices;
    untrack(() => {
      if (!list.length) {
        if (chainUnderlying) chainUnderlying = '';
        return;
      }
      if (!chainUnderlying || !list.includes(chainUnderlying)) {
        chainUnderlying = list[0];
      }
    });
  });

  // Auto-pick first expiry when chain underlying changes.
  $effect(() => {
    void chainUnderlying;
    if (chainExpiries.length && !chainExpiries.includes(chainExpiry)) {
      chainExpiry = chainExpiries[0];
    }
  });

  // Order-ticket state — chain clicks open the reusable
  // <OrderTicket> modal; on DRAFT submit we append to drafts. Phase
  // 2 / 3 add PAPER / LIVE submit paths through the ticket without
  // touching this file.
  /** @type {any} */
  let ticketProps = $state(null);
  function openTicket(/** @type {any} */ p) { ticketProps = p; }
  function closeTicket() { ticketProps = null; }

  // Chain "+" handlers — open the OrderTicket pre-filled. The ticket
  // routes back here via onSubmit when the operator confirms; in
  // DRAFT mode we just push onto the drafts array (the existing
  // strategy auto-recompute picks it up).
  // Account hand-off: pre-select when the operator filtered to one
  // account; otherwise leave blank and let the ticket force a pick.
  // The ticket itself owns the dropdown UI, so pages just pass the
  // candidate list + an optional default.
  /** Account name "looks real" — i.e. it's not the masked `ZG####`
   *  form that non-admin sessions see on positions/holdings. The
   *  OrderTicket needs the real account_id to route correctly, so
   *  we filter masked entries out of any default-pick logic. */
  function _isRealAccount(/** @type {string|null|undefined} */ a) {
    return !!(a && !String(a).includes('#'));
  }
  function _ticketAccountDefault() {
    // Prefer the operator's filter (single account picked in the
    // multiselect) when it's a real value. Then a single available
    // real account. Then the masked-but-only choice — falls back to
    // empty so the picker forces an explicit pick. Never returns a
    // masked value that the order endpoint can't route on.
    if (selectedAccounts.length === 1 && _isRealAccount(selectedAccounts[0])) {
      return selectedAccounts[0];
    }
    if (realAccounts.length === 1) return realAccounts[0];
    if (accountChoices.length === 1 && _isRealAccount(accountChoices[0])) {
      return String(accountChoices[0]);
    }
    return '';
  }
  // Per-row buttons pass the side explicitly. Default to chainSide so
  // any caller that hasn't been migrated yet still works. Qty sizing:
  // contract lot size × chainLots, clamped so a 0/blank lots input
  // doesn't post a zero-qty order.
  function addChainDraft(/** @type {number} */ strike,
                         /** @type {'CE'|'PE'} */ optType,
                         /** @type {'long'|'short'} */ side = chainSide) {
    if (!chainUnderlying || !chainExpiry) return;
    const inst = findOption(chainUnderlying.toUpperCase(), optType, strike, chainExpiry);
    if (!inst) return;
    const lot  = Number(inst.ls || 1);
    const lots = Math.max(1, Number(chainLots) || 1);
    openTicket({
      symbol:   inst.s,
      // Exchange comes from the instruments cache (Kite's authoritative
      // `e` field per contract). CRUDEOIL options live on MCX, NIFTY
      // options on NFO, BSE options on BFO — hardcoding NFO would route
      // every depth lookup to the wrong exchange and the ladder would
      // come back empty.
      exchange: inst.e || 'NFO',
      side:     side === 'long' ? 'BUY' : 'SELL',
      qty:      lot * lots,
      lotSize:  lot,
      accounts: ticketAccounts,
      account:  _ticketAccountDefault(),
    });
  }
  function addFutureDraft(/** @type {string} */ sym,
                          /** @type {number} */ lotSize,
                          /** @type {'long'|'short'} */ side = chainSide) {
    if (!sym) return;
    const lot  = Number(lotSize || 1);
    const lots = Math.max(1, Number(chainLots) || 1);
    // Look up the instrument so we route to the right exchange
    // (commodity futures live on MCX, not NFO).
    const inst = getInstrument(sym.toUpperCase());
    openTicket({
      symbol:   sym,
      exchange: inst?.e || 'NFO',
      side:     side === 'long' ? 'BUY' : 'SELL',
      qty:      lot * lots,
      lotSize:  lot,
      accounts: ticketAccounts,
      account:  _ticketAccountDefault(),
    });
  }

  /** Pre-fill account when the row already names one. Falls back
   *  to the page-level default. Masked (`ZG####`) values get
   *  filtered so the ticket never seeds with an unroutable
   *  account. */
  function _rowTicketAccount(/** @type {{account?: string}} */ c) {
    const fromRow = String(c.account || '').trim();
    if (_isRealAccount(fromRow)) return fromRow;
    return _ticketAccountDefault();
  }

  /** Click-on-row handler — opens the OrderTicket pre-filled to
   *  close the row's position. Skipped for drafts (no real
   *  exposure to close) and zero-qty rows (already closed —
   *  sorted to end of list, included for visibility). The
   *  checkbox inside the row stops propagation so its toggle
   *  doesn't double-fire as a close. */
  function closePosition(/** @type {any} */ c) {
    if (!c?.symbol || c.source === 'draft') return;
    const qty = Math.abs(Number(c.qty || 0));
    if (!qty) return;       // already closed
    const inst = getInstrument(String(c.symbol).toUpperCase());
    const lot  = Number(inst?.ls || 1);
    openTicket({
      symbol:   c.symbol,
      exchange: inst?.e || 'NFO',
      side:     c.qty < 0 ? 'BUY' : 'SELL',   // opposite of held
      action:   'close',
      qty,
      lotSize:  lot,
      // Pass signed qty so the OrderTicket can label the side toggle
      // as ADD / CLOSE (instead of BUY / SELL) — operator thinks in
      // "I want to close this position" terms when clicking on a
      // current position row.
      currentQty: Number(c.qty || 0),
      accounts: ticketAccounts,
      account:  _rowTicketAccount(c),
    });
  }

  // Ticket → drafts: signed qty (BUY = +qty, SELL = −qty) so the
  // existing payoff math keeps working. Auto-aligns the page
  // underlying so the new draft surfaces in candidates immediately.
  function onTicketSubmit(/** @type {any} */ payload) {
    if (payload.mode !== 'draft') return;   // PAPER / LIVE land in phase 2/3
    const signedQty = payload.side === 'BUY'
      ? Math.abs(Number(payload.quantity || 0))
      : -Math.abs(Number(payload.quantity || 0));
    drafts = [...drafts, {
      id:       ++_draftSeq,
      symbol:   String(payload.symbol),
      qty:      signedQty,
      avg_cost: payload.price != null ? Number(payload.price) : '',
      ltp:      '',
    }];
    if (!selectedUnderlying && chainUnderlying) {
      selectedUnderlying = chainUnderlying.toUpperCase();
    }
  }

  // Position lists for the picker. Carries avg_cost + ltp so that
  // the strategy leg-builder can ship them inline (sim legs need this
  // because the backend can't fetch their ltp from the broker).
  /** @type {Array<{symbol:string, account:string, qty:number, source:string, avg_cost:number|null, ltp:number|null}>} */
  let positions = $state([]);

  /** Real (unmasked) broker account IDs from /api/accounts/. Loaded
   *  separately from positions because /positions masks the account
   *  field for non-admin signed-in users (server-side mask_column),
   *  which would leave the OrderTicket with un-tradeable "ZG####"
   *  options. The /accounts endpoint is jwt-guarded but doesn't
   *  mask, so any signed-in user gets the real account_ids and the
   *  ticket can route the order to the right Kite handle.
   *
   *  Stays empty for anonymous demo sessions — the OrderTicket
   *  routes such orders through the demo paper-engine path which
   *  doesn't need a real account anyway. */
  /** @type {string[]} */
  let realAccounts = $state([]);

  async function loadRealAccounts() {
    try {
      const r = await fetchAccounts();
      const list = (r?.accounts || [])
        .map(/** @param {any} a */ (a) => String(a?.account_id || ''))
        .filter(Boolean);
      realAccounts = list;
    } catch (_) {
      // 401 / 403 (anonymous demo on prod) — keep realAccounts
      // empty; the ticket falls back to the masked accountChoices.
      realAccounts = [];
    }
  }

  /** Account list to feed the OrderTicket — prefers the unmasked
   *  /api/accounts/ result; falls back to whatever's on the loaded
   *  positions (which may be masked for non-admin sessions). */
  const ticketAccounts = $derived(
    realAccounts.length ? realAccounts : accountChoices.map(String)
  );

  /** Chain picker is gated on having exactly ONE real (un-masked)
   *  account selected at the page level. Reasoning:
   *   - Every leg added through the chain goes straight to OrderTicket
   *     for placement, and an order needs exactly one routing account.
   *   - With zero accounts picked, the picker would default to "all
   *     accounts" which is meaningless for placement.
   *   - With multiple accounts picked, the picker has no way to know
   *     which account a basket leg should land on — operator could
   *     pick the wrong one in the ticket and split a strategy across
   *     accounts by accident.
   *  Forcing a single-account filter makes the routing unambiguous;
   *  the OrderTicket inherits that account via _ticketAccountDefault. */
  const chainEnabled = $derived(
    selectedAccounts.length === 1 && _isRealAccount(selectedAccounts[0])
  );

  // Auto-close the chain panel when the operator de-selects / multi-
  // selects accounts after opening it — otherwise a stale picker
  // would sit open with the buttons greyed.
  $effect(() => {
    if (!chainEnabled && showAddPanel) showAddPanel = false;
  });

  async function loadPositions() {
    /** @type {Array<{symbol:string, account:string, qty:number, source:string, avg_cost:number|null, ltp:number|null, pnl:number}>} */
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
          // Broker P&L (realised + unrealised). For qty=0 closed-out
          // intraday rows this is the realized P&L; the chart adds it
          // up separately so the legs panel + dashboard reconcile.
          pnl:      p?.pnl != null ? Number(p.pnl) : 0,
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
          pnl:      p?.pnl != null ? Number(p.pnl) : 0,
        });
      }
    } catch (_) { /* ignore */ }

    positions = merged;
    _saveCache();
  }

  // Consecutive-failure counter for loadStrategy. Suppresses the
  // error banner on a single transient hiccup (page reopen during
  // a backend redeploy, slow first response on a cold connection,
  // etc.) — only escalates after 2+ failures in a row so the user
  // sees the chart appear cleanly when the next poll succeeds.
  let _stratFails = 0;
  async function loadStrategy() {
    const cleanLegs = legs
      .map(l => {
        const sym = String(l.symbol || '').trim().toUpperCase();
        // Look up the contract's actual expiry from the instruments
        // cache. Kite stores per-contract expiries on the `x` field —
        // authoritative for every exchange. Critical for MCX
        // commodities (GOLDM/CRUDEOIL/etc.) where the backend's
        // symbol parser would otherwise infer the NSE-F&O last-
        // Thursday rule and land 1-3 days off the real expiry.
        const inst    = sym ? getInstrument(sym) : null;
        const expiry  = inst?.x || null;
        return {
          symbol:   sym,
          qty:      l.qty === '' || l.qty == null ? 0 : Number(l.qty),
          avg_cost: l.avg_cost === '' || l.avg_cost == null ? null : Number(l.avg_cost),
          // Only inline ltp for sources whose price isn't on the wire
          // (sim driver state, operator drafts). For live broker
          // positions, drop ltp so the backend re-fetches a fresh
          // quote every poll — otherwise the stale `last_price` from
          // the 30s position poll overrides every subsequent broker
          // fetch and the chart's spot/Greeks/EV freeze even though
          // analytics is polling at 5s.
          ltp: (l.source === 'sim' || l.source === 'draft')
            ? (l.ltp === '' || l.ltp == null ? null : Number(l.ltp))
            : null,
          expiry,
        };
      })
      .filter(l => l.symbol && l.qty);
    if (!cleanLegs.length) {
      strategy = null; strategyErr = ''; _stratFails = 0;
      return;
    }
    loading = true;
    try {
      strategy = await fetchStrategyAnalytics(cleanLegs);
      strategyErr = '';
      _stratFails = 0;
      _saveCache();
    } catch (e) {
      _stratFails += 1;
      // Banner shows only when (a) we have no prior chart to fall
      // back on AND (b) we've failed at least twice in a row. A
      // first-load transient — common on tab reopen during a deploy
      // or after a wifi reconnect — stays silent and the next poll
      // brings the chart in cleanly. The api-layer logger still
      // records the raw error in the browser console for debugging.
      if (!strategy && _stratFails >= 2) {
        strategyErr = /** @type {any} */ (e).message || String(e);
      }
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

  // ── Stale-while-revalidate cache ──────────────────────────────────
  // sessionStorage-backed snapshot of the page's data + operator
  // selections so a tab reopen / SPA back-nav comes up with the
  // previous view (chart, dropdowns, leg toggles, drafts) instead of
  // a blank page. The first fresh fetch overwrites the snapshot;
  // entries > 5 minutes old are discarded so the operator never sees
  // a wildly stale chart.
  const _CACHE_KEY = 'ramboq:options-state';
  const _CACHE_MAX_AGE_MS = 5 * 60 * 1000;
  function _saveCache() {
    if (typeof sessionStorage === 'undefined') return;
    try {
      sessionStorage.setItem(_CACHE_KEY, JSON.stringify({
        ts: Date.now(),
        positions, strategy, drafts,
        selectedAccounts, selectedUnderlying, selectedExpiry,
        enabledSymbols,
      }));
    } catch (_) { /* quota / private mode — silent */ }
  }
  function _loadCache() {
    if (typeof sessionStorage === 'undefined') return false;
    try {
      const raw = sessionStorage.getItem(_CACHE_KEY);
      if (!raw) return false;
      const d = JSON.parse(raw);
      if (!d || (Date.now() - (d.ts || 0)) > _CACHE_MAX_AGE_MS) return false;
      // Restore data first, then selections — derived state (candidates,
      // legs) recomputes off the restored positions + drafts.
      if (Array.isArray(d.positions)) positions = d.positions;
      if (d.strategy)                  strategy  = d.strategy;
      if (Array.isArray(d.drafts))     drafts    = d.drafts;
      if (Array.isArray(d.selectedAccounts)) selectedAccounts = d.selectedAccounts;
      if (typeof d.selectedUnderlying === 'string') selectedUnderlying = d.selectedUnderlying;
      if (typeof d.selectedExpiry === 'string')      selectedExpiry    = d.selectedExpiry;
      if (d.enabledSymbols && typeof d.enabledSymbols === 'object') {
        enabledSymbols = d.enabledSymbols;
      }
      return true;
    } catch (_) { return false; }
  }

  onMount(async () => {
    // Auth/redirect handled by the algo layout; demo visitors view
    // this page read-only.
    // Stale-while-revalidate: paint the previous session's view first
    // (positions populate the dropdowns, strategy renders the chart)
    // so the page never shows up empty on a tab reopen. Background
    // fetches below replace the snapshot once the broker responds.
    _loadCache();
    loadPositions();
    // Real broker accounts — needed by the OrderTicket so the
    // operator can pick which Kite handle the order routes through.
    // Fetched separately from positions because /positions masks
    // the account field for non-admin signed-in users; /accounts
    // returns unmasked account_ids to any authenticated user.
    loadRealAccounts();
    // Load the instruments cache so the option-chain picker has data.
    // Already cached in IndexedDB after the first /console autocomplete
    // load — most operators will see this resolve from cache instantly.
    // `underlyingChoices` is a $derived that recomputes off
    // instrumentsReady + selectedUnderlying + positions, so flipping
    // the flag is enough to populate the chain picker's dropdown.
    try {
      await loadInstruments();
      instrumentsReady = true;
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
<!-- Picker bar — no card wrapper. Account + Underlying + + sit
     directly on the page so they read as inline page-level
     controls rather than as content inside a panel. -->
<div class="opt-picker mb-3">
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
  <div class="opt-field">
    <label class="field-label" for="opt-exp">Expiry</label>
    <Select id="opt-exp"
      bind:value={selectedExpiry}
      options={expiryChoicesForUnderlying.map(x => ({ value: x, label: x }))}
      placeholder={expiryChoicesForUnderlying.length ? 'Pick expiry' : '—'} />
  </div>
  <!-- OChain launcher — single toggle that opens / closes the chain
       picker. Per-row +/− inside the picker decides each leg's side
       (BUY / SELL); the outer button is now purely "show / hide
       picker." Disabled until the operator picks exactly one real
       account on the page — every leg landed via the chain routes
       through OrderTicket which needs an unambiguous routing
       account. -->
  <div class="opt-trade" role="group" aria-label="Open chain picker">
    <button type="button"
            class="opt-add-btn opt-add-btn-ochain"
            class:opt-add-btn-on={showAddPanel}
            disabled={!chainEnabled}
            title={chainEnabled
              ? (showAddPanel ? 'Hide the chain picker' : 'Open the chain picker')
              : 'Pick exactly one account to enable the chain picker'}
            aria-label="Toggle chain picker"
            aria-pressed={showAddPanel}
            onclick={() => {
              // Seed the chain picker from the operator's already-
              // chosen underlying / expiry on the picker bar above.
              // Earlier the chain picker kept its own independent
              // chainUnderlying state, defaulting to NIFTY — an
              // operator analysing BANKNIFTY / GOLDM had to pick the
              // underlying again inside the panel.
              if (!showAddPanel) {
                if (selectedUnderlying) chainUnderlying = selectedUnderlying;
                if (selectedExpiry)     chainExpiry     = selectedExpiry;
              }
              showAddPanel = !showAddPanel;
            }}>OChain</button>
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
        {#if chainSpot != null}
          <span class="chain-spot-pill" title="Underlying spot — ATM strike highlighted in the grid below">
            SPOT ₹{chainSpot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            {#if chainAtmStrike != null}
              · ATM {chainAtmStrike.toFixed(0)}
            {/if}
          </span>
        {/if}
        <!-- The trailing "click CE / PE next to a strike to add a leg
             · quantity defaults to 1 lot" hint was dropped per
             operator request: with it gone, Option chain + SPOT/ATM
             pill fit on a single line at narrow widths. -->
      </div>
      <div class="chain-controls">
        <div class="chain-field">
          <label class="field-label" for="chain-und">Underlying</label>
          <Select id="chain-und"
            bind:value={chainUnderlying}
            searchable={true}
            searchPlaceholder="Type 3+ chars to filter…"
            options={underlyingChoices.map(u => ({ value: u, label: u }))} />
        </div>
        <div class="chain-field">
          <label class="field-label" for="chain-exp">Expiry</label>
          <Select id="chain-exp"
            bind:value={chainExpiry}
            options={chainExpiries.map(e => ({ value: e, label: e }))}
            placeholder={chainExpiries.length ? 'Pick expiry' : '—'} />
        </div>
        <!-- Options / Futures toggle — radio-style. Default lands on
             Options (the strike grid); flip to Futures to hide the
             grid and expose the futures pills. Operator preference:
             futures shouldn't crowd the strike grid by default. -->
        <div class="chain-field chain-kind-field">
          <span class="field-label">Kind</span>
          <div class="chain-kind-toggle" role="radiogroup" aria-label="Chain kind">
            <label class="chain-kind-pill" class:on={chainKind === 'opt'}>
              <input type="radio" name="chain-kind" value="opt"
                     bind:group={chainKind} class="chain-kind-radio"/>
              Options
            </label>
            <label class="chain-kind-pill" class:on={chainKind === 'fut'}>
              <input type="radio" name="chain-kind" value="fut"
                     bind:group={chainKind} class="chain-kind-radio"/>
              Futures
            </label>
          </div>
        </div>
      </div>
      {#if chainKind === 'fut' && chainFutures.length}
        <!-- Futures quick-add row — paired BUY (+) / SELL (−) pills
             open the inline lots-picker; (i) opens the full
             OrderTicket modal pre-filled. Same fast/slow split as
             the strike rows. Gated on chainKind='fut' so the
             futures pills don't crowd the default options view. -->
        <div class="chain-futures">
          <span class="chain-futures-label">Futures:</span>
          {#each chainFutures as f (f.s)}
            {@const futKey = _quickKeyFut(f.s)}
            {#if isQuickActiveFut(f.s)}
              <span class="chain-quick chain-quick-{quickPicker.side}">
                <span class="chain-quick-tag">{quickPicker.side === 'long' ? 'B' : 'S'}</span>
                <span class="chain-quick-sym">{f.s}</span>
                <button type="button" class="chain-quick-step"
                        onclick={() => quickStepLots(-1)}
                        aria-label="Decrease lots"
                        disabled={(quickPicker.lots || 1) <= 1}>−</button>
                <span class="chain-quick-lots-val"
                      aria-label="Lots: {quickPicker.lots}">{quickPicker.lots}</span>
                <button type="button" class="chain-quick-step"
                        onclick={() => quickStepLots(1)}
                        aria-label="Increase lots">+</button>
                {#if quickPicker.lotSize > 0}
                  <span class="chain-quick-meta">(× {quickPicker.lotSize} = {(quickPicker.lots || 1) * quickPicker.lotSize})</span>
                {/if}
                <button type="button" class="chain-quick-ok"
                        disabled={quickPlacing}
                        title="Place paper MARKET order"
                        onclick={quickPlace}>{quickPlacing ? '…' : '✓'}</button>
                <button type="button" class="chain-quick-cancel"
                        title="Cancel" onclick={cancelQuickPicker}>✕</button>
              </span>
              {#if quickError}<span class="chain-quick-err">{quickError}</span>{/if}
            {:else if quickJustPlaced === futKey}
              <span class="chain-quick-toast">✓ {f.s} placed</span>
            {:else}
              <span class="chain-fut-pair">
                <button type="button"
                        class="chain-fut-pill chain-fut-pill-buy"
                        title="BUY {f.s} — pick lots inline ({f.ls} per lot)"
                        onclick={() => openQuickPickerFut(f.s, f.ls, 'long')}>
                  + {f.s}
                  <span class="chain-fut-meta">lot {f.ls}</span>
                </button>
                <button type="button"
                        class="chain-fut-pill chain-fut-pill-sell"
                        title="SELL {f.s} — pick lots inline"
                        onclick={() => openQuickPickerFut(f.s, f.ls, 'short')}>
                  − {f.s}
                </button>
                <button type="button"
                        class="chain-fut-pill chain-fut-pill-info"
                        title="Open full ticket for {f.s} (edit qty / price / mode)"
                        onclick={() => addFutureDraft(f.s, f.ls, 'long')}>i</button>
              </span>
            {/if}
          {/each}
        </div>
      {/if}
      {#if chainKind === 'opt' && chainStrikes.length}
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
                {@const isAtm = chainAtmStrike != null && k === chainAtmStrike}
                {@const dir   = chainSpot != null
                                ? (k < chainSpot ? 'itm-call'
                                  : k > chainSpot ? 'itm-put' : 'atm')
                                : ''}
                <!-- Each strike row exposes BOTH BUY (+) and SELL (−)
                     for both CE and PE — 4 buttons total — so the
                     operator can land mixed long/short legs across
                     strikes in one open-then-pick session without
                     toggling the outer +/− between picks. -->
                <!-- Buttons drop the CE/PE suffix — the column header
                     (CE | Strike | PE) already attributes side, so the
                     glyph alone is enough. (i) opens the full
                     OrderTicket pre-filled for that side+type as the
                     advanced / "edit before placing" path. -->
                <!-- + / − fast path: opens the inline lots-picker
                     in-cell. Press ✓ → submits a paper MARKET order
                     directly. (i) is the slow path: opens the full
                     OrderTicket modal pre-filled. -->
                {@const ceKey = _quickKeyOpt(k, 'CE')}
                {@const peKey = _quickKeyOpt(k, 'PE')}
                {#if isAtm}
                  <tr use:chainAtmRow class="chain-row chain-row-{dir} chain-row-atm">
                    <td class="chain-td-ce">
                      {#if isQuickActive(k, 'CE')}
                        <span class="chain-quick chain-quick-{quickPicker.side}">
                          <span class="chain-quick-tag">{quickPicker.side === 'long' ? 'B' : 'S'}</span>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(-1)}
                                  aria-label="Decrease lots"
                                  disabled={(quickPicker.lots || 1) <= 1}>−</button>
                          <select class="chain-quick-select"
                                  bind:value={quickPicker.lots}
                                  aria-label="Lots">
                            {#each [1, 2, 3, 5, 10, 25, 50, 75, 100] as n}
                              <option value={n}>{n}</option>
                            {/each}
                            {#if ![1, 2, 3, 5, 10, 25, 50, 75, 100].includes(quickPicker.lots)}
                              <option value={quickPicker.lots}>{quickPicker.lots}</option>
                            {/if}
                          </select>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(1)}
                                  aria-label="Increase lots">+</button>
                          {#if quickPicker.lotSize > 0}
                            <span class="chain-quick-meta">(× {quickPicker.lotSize} = {(quickPicker.lots || 1) * quickPicker.lotSize})</span>
                          {/if}
                          <button type="button" class="chain-quick-ok"
                                  disabled={quickPlacing}
                                  title="Place paper MARKET order"
                                  onclick={quickPlace}>{quickPlacing ? '…' : '✓'}</button>
                          <button type="button" class="chain-quick-cancel"
                                  title="Cancel" onclick={cancelQuickPicker}>✕</button>
                        </span>
                        {#if quickError}<span class="chain-quick-err">{quickError}</span>{/if}
                      {:else if quickJustPlaced === ceKey}
                        <span class="chain-quick-toast">✓ placed</span>
                      {:else}
                        <span class="chain-btn-pair">
                          <button type="button" class="chain-btn chain-btn-buy"
                                  title="BUY {k} CE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'CE', 'long')}>+</button>
                          <button type="button" class="chain-btn chain-btn-sell"
                                  title="SELL {k} CE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'CE', 'short')}>−</button>
                          <button type="button" class="chain-btn chain-btn-info"
                                  title="Open full ticket for {k} CE (edit qty / price / mode)"
                                  onclick={() => addChainDraft(k, 'CE', 'long')}>i</button>
                        </span>
                      {/if}
                    </td>
                    <td class="chain-td-strike">
                      {k.toFixed(0)}<span class="chain-atm-tag">ATM</span>
                    </td>
                    <td class="chain-td-pe">
                      {#if isQuickActive(k, 'PE')}
                        <span class="chain-quick chain-quick-{quickPicker.side}">
                          <span class="chain-quick-tag">{quickPicker.side === 'long' ? 'B' : 'S'}</span>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(-1)}
                                  aria-label="Decrease lots"
                                  disabled={(quickPicker.lots || 1) <= 1}>−</button>
                          <select class="chain-quick-select"
                                  bind:value={quickPicker.lots}
                                  aria-label="Lots">
                            {#each [1, 2, 3, 5, 10, 25, 50, 75, 100] as n}
                              <option value={n}>{n}</option>
                            {/each}
                            {#if ![1, 2, 3, 5, 10, 25, 50, 75, 100].includes(quickPicker.lots)}
                              <option value={quickPicker.lots}>{quickPicker.lots}</option>
                            {/if}
                          </select>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(1)}
                                  aria-label="Increase lots">+</button>
                          {#if quickPicker.lotSize > 0}
                            <span class="chain-quick-meta">(× {quickPicker.lotSize} = {(quickPicker.lots || 1) * quickPicker.lotSize})</span>
                          {/if}
                          <button type="button" class="chain-quick-ok"
                                  disabled={quickPlacing}
                                  title="Place paper MARKET order"
                                  onclick={quickPlace}>{quickPlacing ? '…' : '✓'}</button>
                          <button type="button" class="chain-quick-cancel"
                                  title="Cancel" onclick={cancelQuickPicker}>✕</button>
                        </span>
                        {#if quickError}<span class="chain-quick-err">{quickError}</span>{/if}
                      {:else if quickJustPlaced === peKey}
                        <span class="chain-quick-toast">✓ placed</span>
                      {:else}
                        <span class="chain-btn-pair">
                          <button type="button" class="chain-btn chain-btn-buy"
                                  title="BUY {k} PE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'PE', 'long')}>+</button>
                          <button type="button" class="chain-btn chain-btn-sell"
                                  title="SELL {k} PE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'PE', 'short')}>−</button>
                          <button type="button" class="chain-btn chain-btn-info"
                                  title="Open full ticket for {k} PE (edit qty / price / mode)"
                                  onclick={() => addChainDraft(k, 'PE', 'long')}>i</button>
                        </span>
                      {/if}
                    </td>
                  </tr>
                {:else}
                  <tr class="chain-row chain-row-{dir}">
                    <td class="chain-td-ce">
                      {#if isQuickActive(k, 'CE')}
                        <span class="chain-quick chain-quick-{quickPicker.side}">
                          <span class="chain-quick-tag">{quickPicker.side === 'long' ? 'B' : 'S'}</span>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(-1)}
                                  aria-label="Decrease lots"
                                  disabled={(quickPicker.lots || 1) <= 1}>−</button>
                          <select class="chain-quick-select"
                                  bind:value={quickPicker.lots}
                                  aria-label="Lots">
                            {#each [1, 2, 3, 5, 10, 25, 50, 75, 100] as n}
                              <option value={n}>{n}</option>
                            {/each}
                            {#if ![1, 2, 3, 5, 10, 25, 50, 75, 100].includes(quickPicker.lots)}
                              <option value={quickPicker.lots}>{quickPicker.lots}</option>
                            {/if}
                          </select>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(1)}
                                  aria-label="Increase lots">+</button>
                          {#if quickPicker.lotSize > 0}
                            <span class="chain-quick-meta">(× {quickPicker.lotSize} = {(quickPicker.lots || 1) * quickPicker.lotSize})</span>
                          {/if}
                          <button type="button" class="chain-quick-ok"
                                  disabled={quickPlacing}
                                  title="Place paper MARKET order"
                                  onclick={quickPlace}>{quickPlacing ? '…' : '✓'}</button>
                          <button type="button" class="chain-quick-cancel"
                                  title="Cancel" onclick={cancelQuickPicker}>✕</button>
                        </span>
                        {#if quickError}<span class="chain-quick-err">{quickError}</span>{/if}
                      {:else if quickJustPlaced === ceKey}
                        <span class="chain-quick-toast">✓ placed</span>
                      {:else}
                        <span class="chain-btn-pair">
                          <button type="button" class="chain-btn chain-btn-buy"
                                  title="BUY {k} CE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'CE', 'long')}>+</button>
                          <button type="button" class="chain-btn chain-btn-sell"
                                  title="SELL {k} CE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'CE', 'short')}>−</button>
                          <button type="button" class="chain-btn chain-btn-info"
                                  title="Open full ticket for {k} CE (edit qty / price / mode)"
                                  onclick={() => addChainDraft(k, 'CE', 'long')}>i</button>
                        </span>
                      {/if}
                    </td>
                    <td class="chain-td-strike">{k.toFixed(0)}</td>
                    <td class="chain-td-pe">
                      {#if isQuickActive(k, 'PE')}
                        <span class="chain-quick chain-quick-{quickPicker.side}">
                          <span class="chain-quick-tag">{quickPicker.side === 'long' ? 'B' : 'S'}</span>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(-1)}
                                  aria-label="Decrease lots"
                                  disabled={(quickPicker.lots || 1) <= 1}>−</button>
                          <select class="chain-quick-select"
                                  bind:value={quickPicker.lots}
                                  aria-label="Lots">
                            {#each [1, 2, 3, 5, 10, 25, 50, 75, 100] as n}
                              <option value={n}>{n}</option>
                            {/each}
                            {#if ![1, 2, 3, 5, 10, 25, 50, 75, 100].includes(quickPicker.lots)}
                              <option value={quickPicker.lots}>{quickPicker.lots}</option>
                            {/if}
                          </select>
                          <button type="button" class="chain-quick-step"
                                  onclick={() => quickStepLots(1)}
                                  aria-label="Increase lots">+</button>
                          {#if quickPicker.lotSize > 0}
                            <span class="chain-quick-meta">(× {quickPicker.lotSize} = {(quickPicker.lots || 1) * quickPicker.lotSize})</span>
                          {/if}
                          <button type="button" class="chain-quick-ok"
                                  disabled={quickPlacing}
                                  title="Place paper MARKET order"
                                  onclick={quickPlace}>{quickPlacing ? '…' : '✓'}</button>
                          <button type="button" class="chain-quick-cancel"
                                  title="Cancel" onclick={cancelQuickPicker}>✕</button>
                        </span>
                        {#if quickError}<span class="chain-quick-err">{quickError}</span>{/if}
                      {:else if quickJustPlaced === peKey}
                        <span class="chain-quick-toast">✓ placed</span>
                      {:else}
                        <span class="chain-btn-pair">
                          <button type="button" class="chain-btn chain-btn-buy"
                                  title="BUY {k} PE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'PE', 'long')}>+</button>
                          <button type="button" class="chain-btn chain-btn-sell"
                                  title="SELL {k} PE — pick lots inline"
                                  onclick={() => openQuickPicker(k, 'PE', 'short')}>−</button>
                          <button type="button" class="chain-btn chain-btn-info"
                                  title="Open full ticket for {k} PE (edit qty / price / mode)"
                                  onclick={() => addChainDraft(k, 'PE', 'long')}>i</button>
                        </span>
                      {/if}
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        </div>
      {:else if chainKind === 'opt'}
        <div class="text-[0.6rem] text-[#a3b9d0] italic mt-2">
          No strikes for {chainUnderlying} expiring {chainExpiry || '(pick expiry)'}.
          Try a different underlying or expiry.
        </div>
      {:else if chainKind === 'fut' && !chainFutures.length}
        <div class="text-[0.6rem] text-[#a3b9d0] italic mt-2">
          No futures contracts for {chainUnderlying}.
        </div>
      {/if}
    </div>
  {/if}
{/if}

{#if strategy}
  <div class="opt-payoff opt-payoff-full mb-3">
    <!-- Single-row header — title + Net debit/credit + Max profit /
         Max loss chips. DTE / σ / LEGS / SPOT / TDAY / EXP live in
         the on-chart stat overlay; MAX P / MAX L stay outside the
         chart so the at-a-glance "what can this strategy make/lose"
         pair reads at the page-header altitude. -->
    <div class="opt-section-h opt-section-h-grid">
      <div class="opt-section-row">
        <span class="opt-section-title">Payoff</span>
        <span class="opt-section-tag tag-{strategy.net_cost > 0 ? 'long' : strategy.net_cost < 0 ? 'short' : 'long'}">
          {strategy.net_cost > 0 ? 'NET DR' : strategy.net_cost < 0 ? 'NET CR' : 'FREE'}
          {fmtMoney(Math.abs(strategy.net_cost), false)}
        </span>
        <span class="opt-section-tag tag-long" title="Max profit">
          MAX P {fmtMoney(strategy.risk.max_profit, false)}
        </span>
        <span class="opt-section-tag tag-short" title="Max loss">
          MAX L {fmtMoney(strategy.risk.max_loss, false)}
        </span>
        <!-- The dedicated REAL chip in the header was retired —
             realised P&L is now folded into chartPnlOffset and
             applied as a vertical curve shift inside OptionsPayoff,
             so the chart's TDAY at any spot already matches the
             dashboard total. The breakdown (open theoretical-vs-LTP
             gap + closed realised) is surfaced inline as the RLZ
             row in the chart's stat overlay. -->
      </div>
    </div>
    <OptionsPayoff
      payoff={strategy.payoff}
      spot={strategy.spot}
      prevClose={strategy.spot_prev_close}
      breakevens={strategy.risk.breakevens}
      intermediateCurves={strategy.intermediate_curves || []}
      spanSigmas={strategy.span_sigmas}
      spanPct={strategy.span_pct}
      dte={strategy.days_to_expiry}
      ivProxy={strategy.iv_proxy}
      legCount={strategy.legs.length}
      realizedPnl={chartPnlOffset}
      loading={loading}
      onRefresh={() => { loadPositions(); loadSimStatus(); loadStrategy(); }}
      height={320} />
  </div>
{/if}

<!-- Candidates — sits between the payoff chart above and the
     Aggregate / Greeks / Risk cards below. Reading order: see the
     chart → see which legs feed it → see the maths beneath. Each
     row carries position info (qty / cost / LTP / P&L) plus per-leg
     analytics (IV / Δ / Θ / 𝒱) joined from the latest strategy
     response by symbol. Horizontal + vertical overflow scrolling. -->
{#if selectedUnderlying || drafts.length}
  <div class="algo-status-card cmd-surface p-3 mb-3" data-status="inactive">
    <button type="button"
            class="legs-header"
            aria-expanded={legsOpen}
            title={legsOpen ? 'Collapse leg list' : 'Expand leg list'}
            onclick={() => legsOpen = !legsOpen}>
      <span class="legs-chevron">{legsOpen ? '▾' : '▸'}</span>
      <span>Legs</span>
      {#if selectedUnderlying}
        <span class="opt-section-tag tag-deriv">{selectedUnderlying}</span>
      {/if}
      <span class="opt-section-meta">{candidatePositions.length}</span>
    </button>
    {#if legsOpen && candidatePositions.length}
      {@const hideAcct = selectedAccounts.length === 1}
      <div class="cand-scroll">
        <div class="cand-grid" class:cand-grid-noacct={hideAcct}>
          <div class="cand-headrow">
            <span></span>
            <span>Symbol</span>
            {#if !hideAcct}<span>Acct</span>{/if}
            <span class="num">Qty</span>
            <span class="num">P&amp;L</span>
            <span class="num">Cost</span>
            <span class="num">LTP</span>
            <span class="num">IV</span>
            <span class="num">Δ</span>
            <span class="num">Θ</span>
            <span class="num">𝒱</span>
          </div>
          {#each candidatePositions as c (c.source + '|' + c.account + '|' + c.symbol)}
            {@const lg = legAnalyticsBySymbol[c.symbol]}
            {@const ltp = lg && lg.ltp != null ? lg.ltp : c.ltp}
            {@const cost = c.avg_cost != null ? c.avg_cost : (lg ? lg.avg_cost : null)}
            {@const pnl = (ltp != null && cost != null) ? (ltp - cost) * c.qty : null}
            {@const dir = c.qty < 0 ? 'short' : c.qty > 0 ? 'long' : 'flat'}
            {@const isClosed = Number(c.qty || 0) === 0}
            {@const isClosable = !isClosed && c.source !== 'draft'}
            <!-- Row click → close-position ticket. Skipped on
                 drafts (no real exposure) and zero-qty rows
                 (already closed — sorted to end of list, kept
                 visible for context). The checkbox stops
                 propagation so toggling a leg doesn't
                 inadvertently fire the close handler. -->
            <div class="cand-row cand-row-{dir}"
                 class:cand-disabled={enabledSymbols[c.symbol] === false}
                 class:cand-closed={isClosed}
                 role="button"
                 tabindex={isClosable ? 0 : -1}
                 aria-disabled={!isClosable}
                 title={isClosable
                   ? `Close ${Math.abs(c.qty)} ${c.symbol}`
                   : isClosed ? 'Closed position' : ''}
                 onclick={() => { if (isClosable) closePosition(c); }}
                 onkeydown={(e) => {
                   if (!isClosable) return;
                   if (e.key === 'Enter' || e.key === ' ') {
                     e.preventDefault();
                     closePosition(c);
                   }
                 }}>
              <input type="checkbox"
                     checked={enabledSymbols[c.symbol] !== false}
                     onclick={(e) => e.stopPropagation()}
                     onchange={(e) => {
                       const next = { ...enabledSymbols };
                       next[c.symbol] = /** @type {HTMLInputElement} */ (e.currentTarget).checked;
                       enabledSymbols = next;
                     }} />
              <span class="font-mono">{c.symbol}</span>
              {#if !hideAcct}<span class="font-mono">{c.account}</span>{/if}
              <span class="num {c.qty < 0 ? 'kv-neg' : 'kv-pos'}">{c.qty > 0 ? '+' : ''}{c.qty}</span>
              <span class="num cand-pnl {pnl == null ? '' : pnl >= 0 ? 'cand-pnl-pos' : 'cand-pnl-neg'}">
                {pnl == null ? '—' : (pnl >= 0 ? '+' : '−') + '₹' + Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </span>
              <span class="num">{cost != null ? '₹' + cost.toFixed(2) : '—'}</span>
              <span class="num">{ltp != null ? '₹' + ltp.toFixed(2) : '—'}</span>
              <span class="num">{lg ? (lg.iv * 100).toFixed(1) + '%' : '—'}</span>
              <span class="num">{lg ? lg.greeks.delta.toFixed(2) : '—'}</span>
              <span class="num {lg && lg.greeks.theta < 0 ? 'kv-neg' : ''}">{lg ? lg.greeks.theta.toFixed(0) : '—'}</span>
              <span class="num">{lg ? lg.greeks.vega.toFixed(0) : '—'}</span>
            </div>
          {/each}
        </div>
      </div>
    {:else if legsOpen}
      <div class="text-[0.6rem] text-[#7e97b8] italic">
        No options or futures on <b>{selectedUnderlying}</b> in
        {selectedAccounts.length ? 'the chosen accounts' : 'any account'}.
        Try a different underlying / account, or click <b>+</b> to drop a
        draft strike into the payoff.
      </div>
    {/if}
  </div>
{/if}

<!-- Aggregate / Greeks / Risk cards — three cards in a horizontal
     flex row under the candidates panel. Each card has its own
     internal kv-pair flow. -->
{#if strategy}
  <aside class="opt-side opt-side-row">

        <div class="opt-block">
          <div class="opt-block-h">
            Greeks (position)
            <InfoHint popup text={'Sum of every leg\'s signed-qty Greeks. Δ = net directional exposure; Θ = daily decay (positive when net short premium); 𝒱 = sensitivity to a 1 % IV move.'} />
          </div>
          <div class="opt-kv opt-kv-greeks">
            <div class="kv-pair" title="Delta — net directional exposure. +50 ≈ ₹50 gained per ₹1 spot rise.">
              <span class="kv-k kv-k-greek">Δ</span>
              <span class="kv-v">{fmtNum(strategy.aggregate_greeks.delta, 2)}</span>
            </div>
            <div class="kv-pair" title="Gamma — rate-of-change of delta as spot moves.">
              <span class="kv-k kv-k-greek">Γ</span>
              <span class="kv-v">{fmtNum(strategy.aggregate_greeks.gamma, 2)}</span>
            </div>
            <div class="kv-pair" title="Theta — daily decay in rupees. Positive when net short premium.">
              <span class="kv-k kv-k-greek">Θ</span>
              <span class="kv-v {strategy.aggregate_greeks.theta < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.theta, 2)}</span>
            </div>
            <div class="kv-pair" title="Vega — P&L change per 1 % IV move. Positive = long volatility.">
              <span class="kv-k kv-k-greek">𝒱</span>
              <span class="kv-v {strategy.aggregate_greeks.vega < 0 ? 'kv-neg' : 'kv-pos'}">{fmtNum(strategy.aggregate_greeks.vega, 2)}</span>
            </div>
            <div class="kv-pair" title="Rho — sensitivity to a 1 % rate change. Mostly cosmetic for short-dated index options.">
              <span class="kv-k kv-k-greek">ρ</span>
              <span class="kv-v">{fmtNum(strategy.aggregate_greeks.rho, 2)}</span>
            </div>
          </div>
        </div>

        <div class="opt-block">
          <div class="opt-block-h">
            Risk &amp; expected value
            <InfoHint popup text={'Aggregate risk + expected value across all legs. Probability-weighted outcomes integrated against the lognormal pdf of the underlying using a qty-weighted IV proxy. POP × magnitudes captures the asymmetry that POP alone misses.'} />
          </div>
          <div class="opt-kv">
            <div class="kv-pair">
              <span class="kv-k">R:R <InfoHint popup text={'<b>Risk-to-reward</b> = max_profit / |max_loss|. "1 : 0.5" = risk ₹100 to make ₹50. "1 : 3" = risk ₹100 to make ₹300. <b>—</b> when one side is unbounded.'} /></span>
              <span class="kv-v">{strategy.risk.rr_ratio == null ? '—' : `1 : ${strategy.risk.rr_ratio.toFixed(2)}`}</span>
            </div>
            <div class="kv-pair">
              <span class="kv-k">Breakevens <InfoHint popup text={'<b>Breakevens</b> — spot prices at expiry where the strategy\'s P&L crosses zero. Iron condors and butterflies have 2; verticals have 1; fully ITM/OTM 0.'} /></span>
              <span class="kv-v">
                {#if strategy.risk.breakevens.length}
                  {strategy.risk.breakevens.map(/** @param {number} b */ (b) => `₹${b.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`).join(' / ')}
                {:else}—{/if}
              </span>
            </div>
            <div class="kv-pair">
              <span class="kv-k">POP <InfoHint popup text={'<b>Probability of profit</b> at expiry — sum of lognormal mass over every contiguous profitable region of the payoff curve. For range strategies (iron condors), this measures "P(spot ends inside the wings)".'} /></span>
              <span class="kv-v {strategy.risk.pop > 0.6 ? 'kv-pos' : strategy.risk.pop < 0.4 ? 'kv-neg' : ''}">{fmtPct(strategy.risk.pop)}</span>
            </div>
            <div class="kv-pair">
              <span class="kv-k">EV <InfoHint popup text={'<b>Expected value</b> — POP × win-magnitude − (1−POP) × loss-magnitude, integrated against the lognormal pdf of the underlying. Positive EV = edge in expectation; negative EV = no edge, even if POP is high.'} /></span>
              <span class="kv-v {strategy.risk.ev > 0 ? 'kv-pos' : strategy.risk.ev < 0 ? 'kv-neg' : ''}">{fmtMoney(strategy.risk.ev)}</span>
            </div>
            {#if strategy.risk.ev_pct != null}
              <div class="kv-pair">
                <span class="kv-k">EV / cost <InfoHint popup text={'<b>EV / cost</b> — EV as a percentage of |net cost|. Return-on-capital expectation. +5 % = "on average, my outlay returns 5 % of itself per cycle".'} /></span>
                <span class="kv-v {strategy.risk.ev_pct > 0 ? 'kv-pos' : strategy.risk.ev_pct < 0 ? 'kv-neg' : ''}">
                  {strategy.risk.ev_pct > 0 ? '+' : ''}{strategy.risk.ev_pct.toFixed(1)}%
                </span>
              </div>
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
{/if}


  {#if !strategy && !strategyErr && !legs.length}
    <div class="text-[0.65rem] text-[#7e97b8] italic mb-3">
      No legs yet. Pick an underlying above to surface candidates, or click
      <b>+</b> to drop a draft strike into the payoff.
    </div>
  {/if}

<!-- Reusable order ticket — opens via the option-chain CE/PE/futures
     buttons. Phase 1: DRAFT mode wired (appends to local drafts on
     submit). Phase 2 / 3: PAPER + LIVE submit paths land in the
     ticket itself; this page won't need to change. -->
{#if ticketProps}
  <!-- Spread every prop the calling site set onto the ticket. The
       earlier hand-listed pass-through dropped accounts / account /
       action / defaultMode / availableModes / orderId on the floor —
       so chain + futures clicks opened the ticket without an account
       picker (PAPER / LIVE submit blocked) and closePosition's
       action='close' never reached the modal. Spread keeps any
       future ticketProps field flowing through automatically. -->
  <OrderTicket
    {...ticketProps}
    onSubmit={onTicketSubmit}
    onClose={closeTicket} />
{/if}

<style>
  /* Picker bar — Account / Underlying / Expiry / + always on a
     single row, even on narrow viewports. flex-wrap: nowrap forces
     the row; min-width: 0 on each field lets the Selects shrink to
     fit (their content scrolls / truncates inside the trigger).
     Equal `flex: 1 1 0` on the three Selects so they share the
     available width proportionally. */
  .opt-picker {
    display: flex;
    flex-wrap: nowrap;
    gap: 0.4rem 0.4rem;
    align-items: flex-end;
  }
  .opt-field {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    flex: 1 1 0;
    min-width: 0;          /* allow shrink past content size */
  }
  /* All three Select fields share the same flex weight so each gets
     a third of the leftover space after the + button. */
  .opt-field-grow { flex: 1 1 0; min-width: 0; }

  /* Chain-launcher slot — single OChain pill aligned with the
     Select-trigger row. (Earlier this hosted a paired BUY (+) /
     SELL (−) toggle; per-row +/− inside the picker now decides
     side, so the outer is just an open / close affordance.) */
  .opt-trade {
    display: inline-flex;
    flex: 0 0 auto;
    align-self: flex-end;
  }
  /* OChain pill — height matches the Select trigger
     (min-height: 1.55rem) so the row reads as one consistent
     control bar. Amber palette to identify it as an action button
     in the same family as the chart-corner Refresh. Wider than
     the old square pills since "OChain" needs the room. */
  .opt-add-btn {
    height: 1.55rem;
    min-height: 1.55rem;
    padding: 0 0.65rem;
    flex: 0 0 auto;
    align-self: flex-end;
    border-radius: 3px;          /* match Select's 3px radius */
    border: 1px solid rgba(251,191,36,0.5);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.06em;
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
  /* Disabled state — chain picker requires exactly one account
     selected on the page. Greyed border + faded glyph + not-allowed
     cursor; hover styling suppressed so it doesn't flash on
     mouse-over. */
  .opt-add-btn:disabled,
  .opt-add-btn[disabled] {
    opacity: 0.45;
    cursor: not-allowed;
    background: rgba(126,151,184,0.08);
    border-color: rgba(126,151,184,0.30);
    color: #a3b9d0;
  }
  .opt-add-btn:disabled:hover,
  .opt-add-btn[disabled]:hover {
    background: rgba(126,151,184,0.08);
    border-color: rgba(126,151,184,0.30);
  }
  /* Active (panel-open) — invert the palette so the OChain pill
     visually links to the picker panel below it. */
  .opt-add-btn-on {
    background: #fbbf24;
    color: #0c1830;
    border-color: #fbbf24;
  }

  /* Refresh button moved onto the chart's top-right corner — see
     OptionsPayoff.svelte for its styles. The picker bar now ends
     with the "+" toggle. */

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
  /* Two-row variant — title + chips on row 1, meta line on row 2.
     Each row independently flex-wraps so chips squeeze together
     before pushing the meta line down. */
  .opt-section-h-grid {
    display: grid;
    grid-template-rows: auto auto;
    row-gap: 0.3rem;
  }
  .opt-section-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .opt-section-title {
    color: #fbbf24;
    font-weight: 700;
    font-size: 0.7rem;          /* slightly larger than meta so the
                                   header reads as the section anchor */
    letter-spacing: 0.06em;
  }
  .opt-section-tag {
    font-size: 0.65rem;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid currentColor;
    font-weight: 700;
    white-space: nowrap;
  }
  /* Compact mobile rendering — keeps the NET DEBIT / MAX PROFIT /
     MAX LOSS chips on one line by trimming font + padding + the
     section gap so the row fits inside a ~360px viewport. */
  @media (max-width: 600px) {
    .opt-section-h { gap: 0.25rem; flex-wrap: nowrap; overflow-x: auto; }
    .opt-section-tag { font-size: 0.6rem; padding: 1px 3px; letter-spacing: 0.02em; }
  }
  .tag-deriv  { color: #7dd3fc; background: rgba(125,211,252,0.10); }
  .tag-long   { color: #4ade80; background: rgba(74,222,128,0.10); }
  .tag-short  { color: #f87171; background: rgba(248,113,113,0.10); }
  .opt-section-meta {
    color: #a3b9d0;
    font-weight: 400;
    font-size: 0.65rem;
    margin-left: auto;
  }

  /* Default: legacy stacked aside (column of cards). Used when the
     side panel sat next to the chart. */
  .opt-side {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  /* Row variant: the three cards (Aggregate / Greeks / Risk) sit
     side by side under the candidates panel. Each card grows
     proportionally; on narrower viewports the row wraps to a column. */
  .opt-side-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.6rem;
    margin-bottom: 0.6rem;
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
  /* kv-pairs flow TWO per row, with label and value SIDE BY SIDE
     within each pair: "Underlying  CRUDE OIL", "Spot  ₹9000". Two
     pairs per row keeps the cards compact; labels and values
     align flush-left / flush-right so the eye scans cleanly across
     pairs. */
  .opt-kv {
    display: grid;
    grid-template-columns: 1fr 1fr;
    column-gap: 0.7rem;
    row-gap: 0.3rem;
    font-family: monospace;
  }
  .kv-pair {
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    min-width: 0;
  }
  .kv-k {
    color: #a3b9d0;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.6rem;
    flex: 0 0 auto;
    flex-wrap: nowrap;
  }
  .kv-v {
    color: #c8d8f0;
    font-size: 0.7rem;
    font-weight: 600;
    margin-left: auto;          /* push value to the right of pair */
    text-align: right;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* Greek symbols — clean, slightly heavier than other labels but
     not oversize. The visual identity of each Greek pair without
     overpowering the value next to it. */
  .kv-k-greek {
    font-size: 0.7rem;
    font-weight: 700;
    color: #c8d8f0;
  }
  /* Greeks card — all five pairs in a single row. The narrow
     `max-content auto` per slot lets each pair size to its own
     content; column-gap stays tight so the row feels uniform. */
  .opt-kv-greeks {
    display: grid;
    grid-template-columns: repeat(5, max-content auto);
    column-gap: 0.45rem;
    row-gap: 0;
  }
  .opt-kv-greeks .kv-pair {
    /* Each pair contributes label + value into two adjacent grid
       cells via `display: contents` — the pair wrapper itself
       doesn't take a grid slot. */
    display: contents;
  }
  .opt-kv-greeks .kv-v {
    font-size: 0.65rem;
    margin-left: 0.15rem;
    margin-right: 0.5rem;
    text-align: left;
  }
  .kv-pos { color: #4ade80; }
  .kv-neg { color: #f87171; }
  .kv-sub { color: #a3b9d0; font-size: 0.65rem; margin-left: 0.2rem; }

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
    font-size: 0.65rem;
    color: #a3b9d0;
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
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #a3b9d0;
    text-align: center;
  }
  .leg-source-live   { color: #4ade80; }
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
  /* Legs panel header — collapsable. Reset button defaults so it
     still picks up the .opt-section-h typography but with a click
     affordance + a rotating chevron on the left. */
  .legs-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    background: none;
    border: 0;
    padding: 0 0.25rem 0.5rem;
    cursor: pointer;
    color: #fbbf24;
    font-family: monospace;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    text-align: left;
    flex-wrap: wrap;
  }
  .legs-header:hover { color: #fde047; }
  .legs-chevron {
    /* Bumped to match the Select / MultiSelect dropdown carets
       (0.95rem amber + weight 700). Earlier 0.6rem read as a stray
       glyph; now consistent with the other open/close affordances
       across the algo theme. */
    font-size: 0.95rem;
    line-height: 1;
    font-weight: 700;
    color: #fbbf24;
    width: 1rem;
    text-align: center;
    transition: transform 0.12s ease;
  }

  /* Parent grid — defines column tracks once. Children (`.cand-headrow`
     and each `.cand-row`) consume the same tracks via `subgrid` so
     headers + data cells line up precisely.
     Column order (post-Apr-2026 reshuffle): checkbox · Symbol ·
     Account · Qty · P&L · Cost · LTP · IV · Δ · Θ · 𝒱 · Source.
     P&L sits between Qty and Cost so the operator's eye scans
     "what I have → what I'm making/losing → what I paid". */
  /* Content-sized tracks across the board so the row reads dense
     instead of stretched. Numeric columns (qty / P&L / cost / LTP /
     greeks) use `max-content` so each cell sizes to its widest
     value; the row keeps a tight 0.6 rem gap. Earlier `fr` units
     stretched columns to fill the wrapper width, leaving lots of
     empty space between cells when the panel sat in a wide card. */
  .cand-grid {
    display: grid;
    grid-template-columns:
      auto         /* checkbox */
      max-content  /* symbol */
      max-content  /* account */
      max-content  /* qty */
      max-content  /* pnl */
      max-content  /* cost */
      max-content  /* ltp */
      max-content  /* iv */
      max-content  /* delta */
      max-content  /* theta */
      max-content; /* vega */
    column-gap: 0.6rem;
    row-gap: 0.2rem;
    /* No min-width — the grid is naturally as wide as its content.
       The wrapping .cand-scroll still handles overflow when the
       viewport is narrower than the row. */
    width: max-content;
  }
  /* When the operator filters to a single account, the Account
     column is implicit (every row carries the same value) — drop
     the column entirely. */
  .cand-grid-noacct {
    grid-template-columns:
      auto         /* checkbox */
      max-content  /* symbol */
      max-content  /* qty */
      max-content  /* pnl */
      max-content  /* cost */
      max-content  /* ltp */
      max-content  /* iv */
      max-content  /* delta */
      max-content  /* theta */
      max-content; /* vega */
  }
  /* Single parent grid via subgrid. Each row inherits the parent's
     column tracks — so headers and data cells line up exactly,
     regardless of which row has the longest content per column.
     Earlier each row was its own `display: grid` with `max-content`
     which sized columns per-row → header columns drifted out of
     alignment with data columns. */
  .cand-headrow,
  .cand-row {
    display: grid;
    grid-template-columns: subgrid;
    grid-column: 1 / -1;
    /* Subgrid inherits column-gap from .cand-grid (0.6rem). Don't
       set `gap` here — that overrides the parent and decouples the
       rows' spacing from the header's. */
    padding: 0.1rem 0.2rem;
    align-items: center;
    font-size: 0.62rem;
    font-family: monospace;
    font-variant-numeric: tabular-nums;
  }
  .cand-headrow {
    font-size: 0.65rem;
    color: #a3b9d0;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding-bottom: 0.15rem;
    border-bottom: 1px solid rgba(251,191,36,0.18);
  }
  /* Numeric column cells — right-aligned (industry-standard for
     trade panels) so digits in different rows line up cleanly under
     each column header. tabular-nums on the row already keeps glyph
     widths even, so a "+12,500" lands directly above a "−300" with
     digits stacked in the same columns. */
  .cand-headrow > .num,
  .cand-row > .num {
    text-align: right;
    justify-self: end;
  }
  .cand-row {
    padding: 0.2rem 0.3rem;
    border-radius: 3px;
    cursor: pointer;
    transition: background 0.1s;
  }
  .cand-row:hover { background: rgba(251,191,36,0.05); }
  /* Closed positions (qty=0) — sorted to end of list, kept
     visible for context. Dim them so live rows pop, and disable
     the click-to-close affordance (no exposure to close). */
  .cand-row.cand-closed {
    opacity: 0.45;
    cursor: default;
  }
  .cand-row.cand-closed:hover { background: transparent; }

  /* Long / short row tint — mirrors the /dashboard ag-theme-algo
     palette: sky-cyan for long positions, warm-orange for short.
     Faint left + right inset bars on the row scope the direction
     cue to the row body without flooding the whole table. */
  .cand-row-long {
    background-color: rgba(56,189,248,0.08);
    box-shadow: inset 3px 0 0 rgba(56,189,248,0.75),
                inset -3px 0 0 rgba(56,189,248,0.75);
  }
  .cand-row-short {
    background-color: rgba(251,146,60,0.08);
    box-shadow: inset 3px 0 0 rgba(251,146,60,0.75),
                inset -3px 0 0 rgba(251,146,60,0.75);
  }
  .cand-row-long:hover  { background-color: rgba(56,189,248,0.16); }
  .cand-row-short:hover { background-color: rgba(251,146,60,0.16); }

  /* P&L cell — same green/red scheme as /dashboard's pnl-gain /
     pnl-loss classes. Subtle background tint for a glanceable
     "win or lose?" cue at row-scan speed; bold weight so the
     numbers pop alongside the otherwise-muted row content. */
  .cand-pnl {
    border-radius: 2px;
    padding: 0 0.25rem;
    font-weight: 700;
  }
  .cand-pnl-pos {
    color: #4ade80;
    background-color: rgba(74,222,128,0.10);
  }
  .cand-pnl-neg {
    color: #f87171;
    background-color: rgba(248,113,113,0.10);
  }

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
    font-size: 0.65rem;
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

  .leg-type-CE {
    color: #4ade80;
    background: rgba(74,222,128,0.10);
    border: 1px solid rgba(74,222,128,0.4);
    border-radius: 2px;
    padding: 0 4px;
    font-weight: 700;
    font-size: 0.65rem;
  }
  .leg-type-PE {
    color: #f87171;
    background: rgba(248,113,113,0.10);
    border: 1px solid rgba(248,113,113,0.4);
    border-radius: 2px;
    padding: 0 4px;
    font-weight: 700;
    font-size: 0.65rem;
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
    font-size: 0.6rem;
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
    font-size: 0.6rem;
    color: #a3b9d0;
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
    font-size: 0.6rem;
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
    /* Underlying + Expiry occupy equal space on the same line; Kind
       toggle takes only the room it needs (compact 2-pill segmented
       control). Operator request: equal-width Underlying / Expiry. */
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    gap: 0.4rem 0.5rem;
    margin-bottom: 0.5rem;
    align-items: end;
  }
  @media (max-width: 600px) {
    .chain-controls { grid-template-columns: 1fr; }
  }
  .chain-field {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  /* Options / Futures toggle — radio-style pill pair. The native
     <input type="radio"> is visually hidden; the wrapping <label>
     carries the rendered pill. Active state inverts to filled
     amber to match the OChain button + other selected affordances
     across the algo theme. */
  .chain-kind-toggle {
    display: inline-flex;
    border-radius: 3px;
    border: 1px solid rgba(126,151,184,0.35);
    overflow: hidden;
    align-self: flex-start;
  }
  .chain-kind-pill {
    flex: 0 0 auto;
    padding: 0 0.55rem;
    height: 1.55rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #a3b9d0;
    background: transparent;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    user-select: none;
  }
  .chain-kind-pill:hover {
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
  }
  .chain-kind-pill.on {
    background: rgba(251,191,36,0.18);
    color: #fbbf24;
  }
  .chain-kind-pill + .chain-kind-pill {
    border-left: 1px solid rgba(126,151,184,0.30);
  }
  .chain-kind-radio {
    /* Native radio hidden; the surrounding pill is the visual. */
    position: absolute;
    opacity: 0;
    pointer-events: none;
    width: 0;
    height: 0;
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
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #a3b9d0;
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
    color: #a3b9d0;
    font-weight: 400;
    font-size: 0.6rem;
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
    color: #a3b9d0;
    font-weight: 700;
    text-transform: uppercase;
    font-size: 0.65rem;
    letter-spacing: 0.04em;
    padding: 0.25rem 0.4rem;
    border-bottom: 1px solid rgba(251,191,36,0.25);
  }
  .chain-th-ce     { text-align: left; color: #4ade80; }
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

  /* Chain row tinting — strikes BELOW spot are ITM-call (the call is
     in-the-money); strikes ABOVE spot are ITM-put. Subtle background
     bands so the operator sees the moneyness boundary at a glance.
     ATM row (closest to spot) gets a warm amber highlight + a "ATM"
     tag next to the strike value, and is the scroll target when the
     chain opens. */
  .chain-row-itm-call > td { background: rgba(56,189,248,0.05); }
  .chain-row-itm-put  > td { background: rgba(251,146,60,0.05); }
  .chain-row-atm > td {
    background: rgba(251,191,36,0.18);
    border-top:    1px solid rgba(251,191,36,0.55);
    border-bottom: 1px solid rgba(251,191,36,0.55);
  }
  .chain-atm-tag {
    display: inline-block;
    margin-left: 0.35rem;
    padding: 0 0.3rem;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #0c1830;
    background: #fbbf24;
    border-radius: 2px;
    vertical-align: 1px;
  }

  /* Chain header SPOT pill — sits next to the "Option chain" title
     when chainSpot resolves. Same amber palette as the ATM tag so
     the visual link "this number drives that highlighted row" reads
     instantly. */
  .chain-spot-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: monospace;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 1px 6px;
    border-radius: 2px;
    border: 1px solid rgba(251,191,36,0.55);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
  }
  .chain-btn {
    font-family: monospace;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 2px;
    border: 1px solid currentColor;
    background: transparent;
    cursor: pointer;
    letter-spacing: 0.04em;
    transition: background 0.12s;
  }
  /* Side-by-side BUY (+) / SELL (−) pair per CE/PE cell. */
  .chain-btn-pair {
    display: inline-flex;
    gap: 3px;
  }
  /* BUY (+) — green, SELL (−) — red. Same palette as the outer
     +/− toggle so the operator's eye reads the side without
     parsing the glyph. */
  .chain-btn-buy  { color: #4ade80; }
  .chain-btn-sell { color: #f87171; }
  .chain-btn-buy:hover  { background: rgba(74,222,128,0.10); }
  .chain-btn-sell:hover { background: rgba(248,113,113,0.10); }
  /* Info button — sky-blue, neutral. Opens the full OrderTicket
     pre-filled (advanced path, when the operator wants to edit
     qty / limit price / chase / mode before placing). */
  .chain-btn-info {
    color: #7dd3fc;
    font-style: italic;
    padding: 1px 5px;
  }
  .chain-btn-info:hover { background: rgba(125,211,252,0.10); }
  /* Futures-row info pill — same role as .chain-btn-info but
     scoped to the futures `.chain-fut-pair` so its borders /
     background match the surrounding pills. */
  .chain-fut-pill-info {
    color: #7dd3fc;
    border-color: rgba(125,211,252,0.45);
    font-style: italic;
  }
  .chain-fut-pill-info:hover {
    background: rgba(125,211,252,0.12);
    border-color: rgba(125,211,252,0.75);
  }

  /* ── Inline lots quick-picker ────────────────────────────────────
     Replaces the [+ − i] cell while a + or − is active. Layout:
       [B/S]  [Lots]  [✓]  [✕]
     Side tag colour-coded by long/short. Compact enough to fit in
     the same column footprint as the 3-button row.            */
  .chain-quick {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 1px 2px;
    border-radius: 3px;
    border: 1px solid rgba(126,151,184,0.35);
    background: rgba(13,21,38,0.75);
  }
  .chain-quick-long  { border-color: rgba(74,222,128,0.55); }
  .chain-quick-short { border-color: rgba(248,113,113,0.55); }
  .chain-quick-tag {
    font-family: monospace;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0 4px;
    border-radius: 2px;
  }
  .chain-quick-long  .chain-quick-tag { color: #4ade80; background: rgba(74,222,128,0.15); }
  .chain-quick-short .chain-quick-tag { color: #f87171; background: rgba(248,113,113,0.15); }
  .chain-quick-sym {
    font-family: monospace;
    font-size: 0.65rem;
    color: #c8d8f0;
    padding: 0 3px;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }
  /* +/− stepper around the lots count — same shape + size + colours
     as the OrderTicket Qty stepper (.ot-lots-step / .ot-lots-val /
     .ot-meta) so the two surfaces read as one consistent control.
     Operator request: "lot format in OChain and open/close should
     look similar". */
  .chain-quick-step {
    width: 1.4rem;
    height: 1.4rem;
    padding: 0;
    border-radius: 3px;
    border: 1px solid rgba(251,191,36,0.45);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
    font-family: monospace;
    font-size: 0.9rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .chain-quick-step:hover:not(:disabled) {
    background: rgba(251,191,36,0.22);
    border-color: rgba(251,191,36,0.75);
  }
  .chain-quick-step:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .chain-quick-lots-val {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.8rem;
    padding: 0 0.35rem;
    height: 1.4rem;
    flex: 0 0 auto;
    text-align: center;
    color: #fbbf24;
    font-family: monospace;
    font-weight: 700;
    font-size: 0.8rem;
    font-variant-numeric: tabular-nums;
  }
  /* `(× lot = qty)` tag — sky-blue muted at 0.65rem to match
     the OrderTicket .ot-meta size + colour. */
  .chain-quick-meta {
    color: #a3b9d0;
    font-family: monospace;
    font-size: 0.65rem;
    letter-spacing: 0.02em;
    white-space: nowrap;
    padding: 0 3px;
  }
  .chain-quick-ok,
  .chain-quick-cancel {
    height: 1.25rem;
    min-width: 1.25rem;
    padding: 0 4px;
    border-radius: 2px;
    border: 1px solid currentColor;
    background: transparent;
    cursor: pointer;
    font-family: monospace;
    font-size: 0.7rem;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .chain-quick-ok      { color: #4ade80; }
  .chain-quick-cancel  { color: #f87171; }
  .chain-quick-ok:hover     { background: rgba(74,222,128,0.10); }
  .chain-quick-cancel:hover { background: rgba(248,113,113,0.10); }
  .chain-quick-ok:disabled  { opacity: 0.55; cursor: progress; }
  /* Inline error / success messages — kept outside the picker so
     the picker itself stays the same width while the ✓ toast or
     ✕ message renders alongside (or replaces it, in the toast
     case). */
  .chain-quick-err {
    display: inline-block;
    margin-left: 4px;
    padding: 1px 5px;
    border-radius: 2px;
    background: rgba(248,113,113,0.12);
    color: #f87171;
    font-family: monospace;
    font-size: 0.6rem;
    letter-spacing: 0.02em;
  }
  .chain-quick-toast {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 2px;
    background: rgba(74,222,128,0.18);
    color: #4ade80;
    font-family: monospace;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    animation: chain-quick-fade 1.5s ease-out forwards;
  }
  @keyframes chain-quick-fade {
    0%   { opacity: 1; }
    70%  { opacity: 1; }
    100% { opacity: 0; }
  }
  /* Lots input — match Select trigger height + border so the
     control bar reads as one consistent row. */
  .chain-lots-input {
    width: 100%;
    min-height: 1.55rem;
    padding: 0 6px;
    border-radius: 3px;
    border: 1px solid rgba(126,151,184,0.35);
    background: rgba(13,21,38,0.6);
    color: #c8d8f0;
    font-family: monospace;
    font-size: 0.65rem;
    box-sizing: border-box;
  }
  .chain-lots-input:focus {
    outline: none;
    border-color: rgba(251,191,36,0.55);
    background: rgba(13,21,38,0.8);
  }
  /* Paired BUY/SELL futures pills sit as one inline group with a
     1px gap so they read as a single contract control. */
  .chain-fut-pair {
    display: inline-flex;
    gap: 1px;
  }
  .chain-fut-pill-buy  { color: #4ade80; border-color: rgba(74,222,128,0.45); }
  .chain-fut-pill-sell { color: #f87171; border-color: rgba(248,113,113,0.45); }
  .chain-fut-pill-buy:hover  { background: rgba(74,222,128,0.12); border-color: rgba(74,222,128,0.75); }
  .chain-fut-pill-sell:hover { background: rgba(248,113,113,0.12); border-color: rgba(248,113,113,0.75); }
  /* "chain" source pill on legs added via the chain picker — sky-blue
     to distinguish from manual / live / sim. */
  .leg-source-chain { color: #c084fc; }
</style>
