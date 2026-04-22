<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGrid, ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
  import { fetchHoldings, fetchPositions, fetchFunds } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';
  import { dataCache, authStore } from '$lib/stores';
  import OrderPopup from '$lib/OrderPopup.svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';

  ModuleRegistry.registerModules([AllCommunityModule]);

  const {
    theme         = 'ag-theme-ramboq',
    allowOrders   = false,
    maskAccounts  = true,
    // When true, drop the top timestamp+Refresh row and move the refresh
    // timestamp into the tabs row as the last element. Used by the
    // admin /dashboard page; default keeps the public /performance
    // layout unchanged.
    compactHeader = false,
  } = $props();
  const isDark = $derived(theme === 'ag-theme-algo');

  // Read tab from URL ?tab= param; default to 'positions'
  const validTabs = ['positions', 'holdings'];
  let activeTab = $state(validTabs.includes(page.url.searchParams.get('tab')) ? page.url.searchParams.get('tab') : 'positions');

  let orderRow = $state(/** @type {any|null} */(null));
  let orderSource = $state('holdings');

  function openOrderPopup(row, source) {
    if (!allowOrders || $authStore.user?.role !== 'admin') return;
    orderRow = row;
    orderSource = source;
  }

  function switchTab(/** @type {string} */ id) {
    activeTab = id;
    const url = new URL(page.url);
    url.searchParams.set('tab', id);
    goto(url.pathname + url.search, { replaceState: true, noScroll: true });
  }

  let lastRefresh = $state('');
  let loading     = $state(false);
  let error       = $state('');

  let selectedAccount = $state('all');
  let selectedSymbol  = $state('all');
  let accounts        = $state([]);
  // Symbol lists kept separate by tab — Positions tab shows only
  // position symbols, Holdings tab shows only holding symbols. The
  // visible `symbols` list below is derived from whichever tab is
  // active.
  let positionSymbols = $state(/** @type {string[]} */([]));
  let holdingSymbols  = $state(/** @type {string[]} */([]));
  // The dropdown renders whichever list matches the active tab.
  const symbols = $derived(activeTab === 'holdings' ? holdingSymbols : positionSymbols);
  let rawHoldings     = $state([]);
  let rawPositions    = $state([]);
  let rawFunds        = $state([]);
  let rawHoldingsSummary  = $state([]);
  let rawPositionsSummary = $state([]);

  // Static grid refs
  let fundsEl            = null;
  let holdingsSummaryEl  = null;
  let holdingsAllEl      = null;
  let positionsSummaryEl = null;
  let positionsAllEl     = null;

  let fundsGrid            = null;
  let holdingsSummaryGrid  = null;
  let holdingsAllGrid      = null;
  let positionsSummaryGrid = null;
  let positionsAllGrid     = null;

  const numFmt  = ({ value }) =>
    value == null ? '' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const pctFmt  = ({ value }) =>
    value == null ? '' : `${Number(value).toFixed(2)}%`;
  const maskAcct = ({ value }) =>
    maskAccounts && value ? String(value).replace(/\d/g, '#') : value;
  // Theme-aware P&L colors — actual colors live in app.css keyed to the grid theme.
  // Include 'ag-right-aligned-cell' because user-provided cellClass overrides the
  // class AG Grid adds via type: 'numericColumn'.
  const pnlCls = ({ value }) =>
    ['ag-right-aligned-cell', value < 0 ? 'pnl-loss' : value > 0 ? 'pnl-gain' : 'pnl-zero'];
  // Qty cell: classify by direction, not P&L. A short can be profitable,
  // a long can be losing — what the eye needs here is "which side of the
  // book am I on". Colours live in app.css (qty-short / qty-long).
  const qtyCls = ({ value }) =>
    ['ag-right-aligned-cell', value < 0 ? 'qty-short' : value > 0 ? 'qty-long' : 'qty-flat'];
  const avgVsLtpCls = (params) => {
    const avg = params.data?.average_price;
    const ltp = params.data?.close_price;
    if (avg == null || ltp == null) return 'ag-right-aligned-cell';
    return ['ag-right-aligned-cell', avg > ltp ? 'pnl-loss' : avg < ltp ? 'pnl-gain' : 'pnl-zero'];
  };

  const defaultCol = { resizable: true, sortable: true, filter: true, suppressHeaderMenuButton: true, flex: 1, minWidth: 65 };

  const getRowClass = (params) => {
    const d = params.data || {};
    if (d.tradingsymbol === 'TOTAL' || d.account === 'TOTAL') return 'totals-row';
    // Tag position rows so the operator can tell longs from shorts at a
    // glance. Only applied when `quantity` is present (positions grid);
    // holdings rows never carry a sign.
    const q = d.quantity;
    if (typeof q === 'number' && q < 0) return 'pos-short';
    if (typeof q === 'number' && q > 0) return 'pos-long';
    return '';
  };

  const acctFill = 'ag-col-fill';
  const symFill  = 'ag-col-fill';

  const holdingsSummaryCols = [
    { field: 'account',               headerName: 'Account',  width: 75, minWidth: 75, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'cur_val',               headerName: 'Cur Val',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'inv_val',               headerName: 'Inv Val',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'pnl',                   headerName: 'P&L',      flex: 1, valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',    width: 70, valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',  flex: 1, valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',    width: 70, valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
  ];

  const holdingsCols = [
    { field: 'account',               headerName: 'Account',  width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'tradingsymbol',         headerName: 'Symbol',   width: 120, pinned: 'left', cellClass: symFill, headerClass: symFill },
    { field: 'close_price',           headerName: 'LTP',      width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'average_price',         headerName: 'Avg Price', width: 90, valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'pnl',                   headerName: 'P&L',      width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',    width: 70,  valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',  width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',    width: 70,  valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'quantity',              headerName: 'Qty',      width: 60,  type: 'numericColumn' },
    { field: 'cur_val',               headerName: 'Cur Val',  width: 100, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  const positionsSummaryCols = [
    { field: 'account', headerName: 'Account', width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'pnl',     headerName: 'P&L',     flex: 1, valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
  ];

  const positionsCols = [
    { field: 'account',       headerName: 'Account',   width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'tradingsymbol', headerName: 'Symbol',    width: 150, pinned: 'left', cellClass: symFill, headerClass: symFill },
    { field: 'close_price',   headerName: 'LTP',       width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'average_price', headerName: 'Avg Price', width: 90,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'pnl',           headerName: 'P&L',       width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'quantity',      headerName: 'Qty',       width: 60,  type: 'numericColumn', cellClass: qtyCls },
  ];

  const fundsCols = [
    { field: 'account',      headerName: 'Account',      width: 120, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'cash',         headerName: 'Cash',         flex: 1, valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'avail_margin', headerName: 'Avail Margin', flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'used_margin',  headerName: 'Used Margin',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'collateral',   headerName: 'Collateral',   flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  function makeGrid(el, colDefs, rowData = [], onRowClick = null) {
    return createGrid(el, {
      columnDefs: colDefs,
      rowData,
      defaultColDef: defaultCol,
      columnTypes: {
        numericColumn: {
          cellClass: 'ag-right-aligned-cell',
          headerClass: 'ag-right-aligned-header',
        },
      },
      overlayNoRowsTemplate: '<span style="font-size:0.65rem;color:#999">—</span>',
      domLayout: 'autoHeight',
      getRowClass,
      pinnedBottomRowData: [],
      ...(onRowClick ? { onRowClicked: (e) => onRowClick(e.data) } : {}),
    });
  }

  function updateGrid(grid, newRows) {
    if (!grid) return;
    const existing = [];
    grid.forEachNode(n => existing.push(n.data));
    if (!existing.length) {
      grid.setGridOption('rowData', newRows);
      return;
    }
    const key = (r) => r.tradingsymbol ? `${r.account}|${r.tradingsymbol}` : r.account;
    const oldMap = new Map(existing.map(r => [key(r), r]));
    const update = [], add = [];
    for (const r of newRows) {
      const k = key(r);
      if (oldMap.has(k)) {
        Object.assign(oldMap.get(k), r);
        update.push(oldMap.get(k));
        oldMap.delete(k);
      } else {
        add.push(r);
      }
    }
    const remove = [...oldMap.values()];
    grid.applyTransaction({ update, add, remove });
  }

  function makeHoldingsTotals(rows) {
    if (!rows?.length) return null;
    const sum = (f) => rows.reduce((s, r) => s + (Number(r[f]) || 0), 0);
    const total_pnl        = sum('pnl');
    const total_cur_val    = sum('cur_val');
    const total_day_change = sum('day_change_val');
    const total_inv_val    = total_cur_val - total_pnl;
    const total_prev_val   = total_cur_val - total_day_change;
    return {
      account: '',
      tradingsymbol: 'TOTAL',
      pnl:                   total_pnl,
      pnl_percentage:        total_inv_val  ? (total_pnl        / total_inv_val  * 100) : 0,
      day_change_val:        total_day_change,
      day_change_percentage: total_prev_val ? (total_day_change / total_prev_val * 100) : 0,
      quantity:              sum('quantity'),
      average_price: null,
      close_price:   null,
      cur_val:               total_cur_val,
    };
  }

  function makePositionsTotals(rows) {
    if (!rows?.length) return null;
    const sum = (f) => rows.reduce((s, r) => s + (Number(r[f]) || 0), 0);
    return {
      account: '',
      tradingsymbol: 'TOTAL',
      pnl:        sum('pnl'),
      unrealised: sum('unrealised'),
      realised:   sum('realised'),
      quantity:   sum('quantity'),
      average_price: null,
      close_price:   null,
    };
  }

  function applyAccountFilter() {
    if (!holdingsAllGrid) return;
    // ACCOUNT filter scopes every grid (detail + summary + funds). With a
    // specific account picked we drop other accounts AND the TOTAL row.
    // SYMBOL filter scopes ONLY the last (detail) aggrid — summary and
    // funds are per-account aggregates that don't reduce cleanly to a
    // single symbol, so they stay on the account-level view.
    const keepAcct = (r) => selectedAccount === 'all'
      ? true
      : (r.account === selectedAccount);
    const keepSym  = (r) => selectedSymbol === 'all'
      ? true
      : (r.tradingsymbol === selectedSymbol);
    const hRows     = rawHoldings.filter(r => keepAcct(r) && keepSym(r));
    const pRows     = rawPositions.filter(r => keepAcct(r) && keepSym(r));
    const hSummary  = rawHoldingsSummary.filter(keepAcct);
    const pSummary  = rawPositionsSummary.filter(keepAcct);
    const fRows     = rawFunds.filter(keepAcct);
    const hTotals   = makeHoldingsTotals(hRows);
    const pTotals   = makePositionsTotals(pRows);
    updateGrid(holdingsSummaryGrid, hSummary);
    updateGrid(positionsSummaryGrid, pSummary);
    updateGrid(holdingsAllGrid, hRows);
    holdingsAllGrid.setGridOption('pinnedBottomRowData', hTotals ? [hTotals] : []);
    updateGrid(positionsAllGrid, pRows);
    positionsAllGrid.setGridOption('pinnedBottomRowData', pTotals ? [pTotals] : []);
    updateGrid(fundsGrid, fRows);
    // Hide redundant columns. Account column hides across every grid
    // when a specific account is picked. Symbol column hides on the two
    // detail tables when a specific symbol is picked (summary + funds
    // don't have a symbol column to hide).
    const showAcct = selectedAccount === 'all';
    const showSym  = selectedSymbol  === 'all';
    for (const g of [holdingsAllGrid, positionsAllGrid, fundsGrid, holdingsSummaryGrid, positionsSummaryGrid]) {
      try { g?.setColumnsVisible?.(['account'], showAcct); } catch (_) { /* older AG API */ }
    }
    for (const g of [holdingsAllGrid, positionsAllGrid]) {
      try { g?.setColumnsVisible?.(['tradingsymbol'], showSym); } catch (_) { /* older AG API */ }
    }
  }

  function applyData(h, p, f) {
    rawHoldings         = h.rows ?? [];
    rawPositions        = p.rows ?? [];
    rawHoldingsSummary  = h.summary ?? [];
    rawPositionsSummary = p.summary ?? [];
    rawFunds            = f.rows ?? [];
    const allAccts = [...new Set([...rawHoldings.map(r => r.account), ...rawPositions.map(r => r.account)])];
    accounts = allAccts;
    // Two separate symbol lists — the dropdown narrows to just what the
    // active tab needs, so Positions never shows holding-only symbols
    // (and vice versa).
    positionSymbols = [...new Set(rawPositions.map(r => r.tradingsymbol))]
      .filter(Boolean).sort();
    holdingSymbols  = [...new Set(rawHoldings.map(r => r.tradingsymbol))]
      .filter(Boolean).sort();
    // If the previously-selected symbol no longer appears in the
    // currently-visible list (tab-scoped), snap back to "all".
    const visible = (activeTab === 'holdings' ? holdingSymbols : positionSymbols);
    if (selectedSymbol !== 'all' && !visible.includes(selectedSymbol)) {
      selectedSymbol = 'all';
    }
    lastRefresh = h.refreshed_at ?? '';
    applyAccountFilter();
  }

  // Switching tabs changes which symbol list the dropdown shows. If the
  // current selection isn't in the new list, reset to "all" so the
  // detail grid doesn't render empty.
  $effect(() => {
    const visible = (activeTab === 'holdings' ? holdingSymbols : positionSymbols);
    if (selectedSymbol !== 'all' && !visible.includes(selectedSymbol)) {
      selectedSymbol = 'all';
    }
  });

  $effect(() => {
    // Track account + symbol filters. activeTab is also touched so the
    // filter is re-applied when switching tabs (defensive — the grids
    // already hold the right rows since applyAccountFilter runs on
    // every data refresh, but re-running on tab-switch guards against
    // any edge case where the tab-scoped symbol list changes and the
    // selectedSymbol reset happens mid-flight).
    selectedAccount; selectedSymbol; activeTab;
    applyAccountFilter();
  });

  async function loadAll({ fresh = false } = {}) {
    loading = true; error = '';
    try {
      const [h, p, f] = await Promise.all([
        fetchHoldings({ fresh }),
        fetchPositions({ fresh }),
        fetchFunds({ fresh }),
      ]);
      dataCache.holdings  = h;
      dataCache.positions = p;
      dataCache.funds     = f;
      applyData(h, p, f);
    } catch (e) {
      error = e.message || 'Failed to load data';
    } finally { loading = false; }
  }

  let unsub;

  onMount(async () => {
    holdingsSummaryGrid  = makeGrid(holdingsSummaryEl,  holdingsSummaryCols);
    holdingsAllGrid      = makeGrid(holdingsAllEl,      holdingsCols, [], (r) => openOrderPopup(r, 'holdings'));
    positionsSummaryGrid = makeGrid(positionsSummaryEl, positionsSummaryCols);
    positionsAllGrid     = makeGrid(positionsAllEl,     positionsCols, [], (r) => openOrderPopup(r, 'positions'));
    fundsGrid            = makeGrid(fundsEl,             fundsCols);

    if (dataCache.holdings && dataCache.positions && dataCache.funds) {
      applyData(dataCache.holdings, dataCache.positions, dataCache.funds);
    }

    await loadAll();

    unsub = createPerformanceSocket((msg) => {
      lastRefresh = msg.refreshed_at ?? lastRefresh;
      loadAll();
    });
  });

  onDestroy(() => {
    unsub?.();
    [fundsGrid, holdingsSummaryGrid, holdingsAllGrid,
     positionsSummaryGrid, positionsAllGrid]
      .forEach(g => g?.destroy());
  });
</script>

<div class:perf-dark={isDark}>

{#if error}
  <div class="mb-3 p-3 rounded bg-red-50 text-red-700 text-sm border border-red-200">{error}</div>
{/if}

{#if !compactHeader}
  <!-- Default layout: timestamp + Refresh button on their own line, tabs
       below. The public /performance page uses this. -->
  <div class="flex items-center justify-between mb-2">
    <div class="text-[0.65rem] text-muted perf-ts">
      {#if loading && !lastRefresh}
        <span class="animate-pulse">Loading…</span>
      {:else if lastRefresh}
        <span>{lastRefresh}</span>
      {/if}
    </div>
    <button onclick={() => loadAll({ fresh: true })} disabled={loading} class="btn-secondary text-[0.65rem] py-0.5 px-2 disabled:opacity-50">
      {loading ? 'Refreshing…' : 'Refresh'}
    </button>
  </div>
{/if}

<!-- Tabs + account selector. With `compactHeader`, the refresh timestamp
     joins this row as the last element (no Refresh button — the
     performance WebSocket already handles auto-refresh). -->
<div class="tabs-row mb-3">
  <div class="flex gap-0.5">
    {#each [['positions','Positions'],['holdings','Holdings']] as [id, label]}
      <button
        class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
               {activeTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
        onclick={() => switchTab(id)}
      >{label}</button>
    {/each}
  </div>
  {#if accounts.length > 0}
    <select bind:value={selectedAccount} class="acct-select">
      <option value="all">All Accounts</option>
      {#each accounts as acct}
        <option value={acct}>{maskAccounts ? acct.replace(/\d/g, '#') : acct}</option>
      {/each}
    </select>
  {/if}
  {#if symbols.length > 0}
    <select bind:value={selectedSymbol} class="acct-select">
      <option value="all">All Symbols</option>
      {#each symbols as sym}
        <option value={sym}>{sym}</option>
      {/each}
    </select>
  {/if}
</div>

<!-- Fund Balances heading — on compactHeader layouts (the admin
     dashboard) the Refresh button sits on this row instead of crowding
     the tabs / filter row above. Public /performance keeps its
     top-of-page Refresh button. -->
<div class="funds-heading-row">
  <h2 class="section-heading funds-heading-title">Fund Balances</h2>
  {#if compactHeader}
    <button onclick={() => loadAll({ fresh: true })} disabled={loading}
      class="btn-secondary text-[0.65rem] py-0.5 px-2 disabled:opacity-50 funds-heading-refresh">
      {loading ? 'Refreshing…' : 'Refresh'}
    </button>
  {/if}
</div>
<div bind:this={fundsEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

<section class:hidden={activeTab !== 'positions'}>
  <h2 class="section-heading">Summary</h2>
  <div bind:this={positionsSummaryEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

  <h2 class="section-heading">Positions</h2>
  <div bind:this={positionsAllEl} class="ag-theme-quartz {theme} w-full"></div>
</section>

<section class:hidden={activeTab !== 'holdings'}>
  <h2 class="section-heading">Summary</h2>
  <div bind:this={holdingsSummaryEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

  <h2 class="section-heading">Holdings</h2>
  <div bind:this={holdingsAllEl} class="ag-theme-quartz {theme} w-full"></div>
</section>

{#if orderRow}
  <OrderPopup
    row={orderRow}
    source={orderSource}
    onclose={() => orderRow = null}
    onordered={loadAll}
  />
{/if}

</div><!-- /perf-dark -->

<style>
  .hidden { display: none; }

  /* Tabs + Account + Symbol on one row — keep them all visible on
     narrow widths by setting `flex-wrap: nowrap` and tightening font
     + padding on mobile. Deliberately NOT wrapping because the whole
     point of putting filters on the tabs row is "always at a glance". */
  .tabs-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: nowrap;
  }
  .acct-select {
    font-size: 0.65rem;
    padding: 0.2rem 0.4rem;
    border: 1px solid #c0ccdc;
    border-radius: 0.25rem;
    background: white;
    color: #1e3050;
    outline: none;
    cursor: pointer;
    margin-left: 0;
    min-width: 0;
    max-width: 8.5rem;
    text-overflow: ellipsis;
  }
  /* Push the Account + Symbol dropdowns against the right edge of
     the tabs row. The first dropdown takes margin-left: auto so the
     browser eats the remaining space between the Holdings tab and
     the dropdowns. */
  .tabs-row > select:first-of-type { margin-left: auto; }

  /* Mobile — only the dropdowns tighten; tab font-size stays at the
     default so Positions / Holdings look identical to desktop. */
  @media (max-width: 639px) {
    .tabs-row { gap: 0.3rem; }
    .acct-select {
      font-size: 0.58rem;
      padding: 0.15rem 0.3rem;
      max-width: 7.5rem;
    }
  }
  /* Refresh timestamp pinned to the far right of the tabs row. */
  .tabs-row-ts {
    margin-left: auto;
    white-space: nowrap;
  }
  /* Compact-header Refresh button sits after the account picker. */
  .tabs-row-refresh { margin-left: auto; }

  /* Fund Balances heading — heading left, Refresh button (compactHeader
     only) pinned to the right. Keeps the tabs / filter row focused on
     Account + Symbol selection. */
  .funds-heading-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.25rem;
  }
  .funds-heading-refresh { margin-left: auto; }

  /* ── Dark (algo) overrides ─────────────────────────────────────────────── */
  .perf-dark :global(.section-heading) { color: #fbbf24; }

  .perf-dark .acct-select {
    background: #0d1829;
    border-color: #2a4060;
    color: #c8d8f0;
  }

  /* Tabs */
  .perf-dark :global(button[class*="border-primary"])    { border-color: #d97706 !important; color: #fbbf24 !important; }
  .perf-dark :global(button[class*="text-muted"])        { color: rgba(180,200,230,0.6) !important; }
  .perf-dark :global(button[class*="text-muted"]:hover)  { color: rgba(210,225,250,0.9) !important; }

  /* Refresh button */
  .perf-dark :global(.btn-secondary) {
    color: #c8d8f0;
    border-color: #2a4060;
    background: transparent;
  }
  .perf-dark :global(.btn-secondary:hover:not(:disabled)) { background: rgba(255,255,255,0.06); }

  /* Dashboard timestamp — yellow to match log and algo-ts timestamps */
  .perf-dark :global(.perf-ts) { color: #fde047 !important; }
</style>
