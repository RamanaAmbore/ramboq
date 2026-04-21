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
  let accounts        = $state([]);
  let rawHoldings     = $state([]);
  let rawPositions    = $state([]);
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
    { field: 'pnl',                   headerName: 'P&L',      width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',    width: 70,  valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',  width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',    width: 70,  valueFormatter: pctFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'quantity',              headerName: 'Qty',      width: 60,  type: 'numericColumn' },
    { field: 'average_price',         headerName: 'Avg Price', width: 90, valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'close_price',           headerName: 'LTP',      width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'cur_val',               headerName: 'Cur Val',  width: 100, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  const positionsSummaryCols = [
    { field: 'account', headerName: 'Account', width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'pnl',     headerName: 'P&L',     flex: 1, valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
  ];

  const positionsCols = [
    { field: 'account',       headerName: 'Account',   width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'tradingsymbol', headerName: 'Symbol',    width: 150, pinned: 'left', cellClass: symFill, headerClass: symFill },
    { field: 'pnl',           headerName: 'P&L',       width: 90,  valueFormatter: numFmt, cellClass: pnlCls, type: 'numericColumn' },
    { field: 'quantity',      headerName: 'Qty',       width: 60,  type: 'numericColumn', cellClass: qtyCls },
    { field: 'average_price', headerName: 'Avg Price', width: 90,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
    { field: 'close_price',   headerName: 'LTP',       width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellClass: avgVsLtpCls },
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
    const hRows = selectedAccount === 'all' ? rawHoldings : rawHoldings.filter(r => r.account === selectedAccount);
    const pRows = selectedAccount === 'all' ? rawPositions : rawPositions.filter(r => r.account === selectedAccount);
    const hTotals = makeHoldingsTotals(hRows);
    const pTotals = makePositionsTotals(pRows);
    updateGrid(holdingsSummaryGrid, rawHoldingsSummary);
    updateGrid(positionsSummaryGrid, rawPositionsSummary);
    updateGrid(holdingsAllGrid, hRows);
    holdingsAllGrid.setGridOption('pinnedBottomRowData', hTotals ? [hTotals] : []);
    updateGrid(positionsAllGrid, pRows);
    positionsAllGrid.setGridOption('pinnedBottomRowData', pTotals ? [pTotals] : []);
  }

  function applyData(h, p, f) {
    rawHoldings         = h.rows ?? [];
    rawPositions        = p.rows ?? [];
    rawHoldingsSummary  = h.summary ?? [];
    rawPositionsSummary = p.summary ?? [];
    const allAccts = [...new Set([...rawHoldings.map(r => r.account), ...rawPositions.map(r => r.account)])];
    accounts = allAccts;
    updateGrid(fundsGrid, f.rows ?? []);
    lastRefresh = h.refreshed_at ?? '';
    applyAccountFilter();
  }

  $effect(() => {
    selectedAccount; // track
    applyAccountFilter();
  });

  async function loadAll() {
    loading = true; error = '';
    try {
      const [h, p, f] = await Promise.all([fetchHoldings(), fetchPositions(), fetchFunds()]);
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
    <button onclick={loadAll} disabled={loading} class="btn-secondary text-[0.65rem] py-0.5 px-2 disabled:opacity-50">
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
  {#if compactHeader}
    <span class="perf-ts tabs-row-ts">
      {#if loading && !lastRefresh}
        <span class="animate-pulse">Loading…</span>
      {:else if lastRefresh}
        {lastRefresh}
      {/if}
    </span>
  {/if}
</div>

<h2 class="section-heading">Fund Balances</h2>
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

  /* Tabs + account selector on the same row. Tabs left, dropdown right
     after the Holdings tab with a small gap so they don't crowd. */
  .tabs-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
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
  }
  /* Refresh timestamp pinned to the far right of the tabs row. */
  .tabs-row-ts {
    margin-left: auto;
    white-space: nowrap;
  }

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
