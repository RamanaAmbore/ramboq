<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGrid, ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
  import { fetchHoldings, fetchPositions, fetchFunds } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';
  import { dataCache } from '$lib/stores';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';

  ModuleRegistry.registerModules([AllCommunityModule]);

  // Read tab from URL ?tab= param; default to 'holdings'
  const validTabs = ['holdings', 'positions', 'funds'];
  let activeTab = $state(validTabs.includes(page.url.searchParams.get('tab')) ? page.url.searchParams.get('tab') : 'holdings');

  function switchTab(/** @type {string} */ id) {
    activeTab = id;
    const url = new URL(page.url);
    url.searchParams.set('tab', id);
    goto(url.pathname + url.search, { replaceState: true, noScroll: true });
  }
  let lastRefresh = $state('');
  let loading     = $state(false);
  let error       = $state('');

  // Static grid refs (summary + all + funds)
  let holdingsSummaryEl  = null;
  let holdingsAllEl      = null;
  let positionsSummaryEl = null;
  let positionsAllEl     = null;
  let fundsEl            = null;

  let holdingsSummaryGrid  = null;
  let holdingsAllGrid      = null;
  let positionsSummaryGrid = null;
  let positionsAllGrid     = null;
  let fundsGrid            = null;

  // Container divs for per-account grids (populated imperatively)
  let holdingsAccountsContainer = null;
  let positionsAccountsContainer = null;

  // Track per-account grid instances for cleanup
  let holdingsAccountGrids  = [];
  let positionsAccountGrids = [];

  const numFmt = ({ value }) =>
    value == null ? '' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const pctFmt = ({ value }) =>
    value == null ? '' : `${Number(value).toFixed(2)}%`;
  const pnlStyle = ({ value }) =>
    value < 0 ? { color: '#c0392b' } : { color: '#27ae60' };

  const defaultCol = { resizable: true, sortable: true, filter: true };

  const holdingsSummaryCols = [
    { field: 'account',               headerName: 'Account',    width: 110 },
    { field: 'cur_val',               headerName: 'Cur Val',    flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'inv_val',               headerName: 'Inv Val',    flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'pnl',                   headerName: 'P&L',        flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',      width: 90, valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',    flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',      width: 90, valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  const holdingsCols = [
    { field: 'account',               headerName: 'Account',    width: 110 },
    { field: 'tradingsymbol',         headerName: 'Symbol',     flex: 1 },
    { field: 'exchange',              headerName: 'Exch',       width: 80 },
    { field: 'quantity',              headerName: 'Qty',        width: 80,  type: 'numericColumn' },
    { field: 'average_price',         headerName: 'Avg Price',  width: 110, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'close_price',           headerName: 'Close',      width: 100, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'cur_val',               headerName: 'Cur Val',    width: 120, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'pnl',                   headerName: 'P&L',        width: 110, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',      width: 90,  valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',    width: 110, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',      width: 90,  valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  // Per-account holdings cols — without the account column
  const holdingsAcctCols = holdingsCols.filter(c => c.field !== 'account');

  const positionsSummaryCols = [
    { field: 'account', headerName: 'Account', width: 110 },
    { field: 'pnl',     headerName: 'P&L',     flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  const positionsCols = [
    { field: 'account',       headerName: 'Account',    width: 110 },
    { field: 'tradingsymbol', headerName: 'Symbol',     flex: 1 },
    { field: 'exchange',      headerName: 'Exch',       width: 80 },
    { field: 'product',       headerName: 'Product',    width: 90 },
    { field: 'quantity',      headerName: 'Qty',        width: 80,  type: 'numericColumn' },
    { field: 'average_price', headerName: 'Avg Price',  width: 110, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'close_price',   headerName: 'Close',      width: 100, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'pnl',           headerName: 'P&L',        width: 110, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'unrealised',    headerName: 'Unrealised', width: 110, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'realised',      headerName: 'Realised',   width: 110, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  const positionsAcctCols = positionsCols.filter(c => c.field !== 'account');

  const fundsCols = [
    { field: 'account',      headerName: 'Account',      width: 120 },
    { field: 'cash',         headerName: 'Cash',         flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'avail_margin', headerName: 'Avail Margin', flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'used_margin',  headerName: 'Used Margin',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'collateral',   headerName: 'Collateral',   flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  function makeGrid(el, colDefs, rowData = []) {
    return createGrid(el, {
      columnDefs: colDefs,
      rowData,
      defaultColDef: defaultCol,
      domLayout: 'autoHeight',
    });
  }

  /** Smoothly update grid — reuse existing rows, flash changed cells */
  function updateGrid(grid, newRows) {
    if (!grid) return;
    const existing = [];
    grid.forEachNode(n => existing.push(n.data));
    if (!existing.length) {
      grid.setGridOption('rowData', newRows);
      return;
    }
    // Build lookup by account (+ tradingsymbol if present) for delta
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

  /** Build per-account AG Grids inside a container div. */
  function buildAccountGrids(container, rows, colDefs) {
    // Destroy existing per-account grids
    const old = container === holdingsAccountsContainer ? holdingsAccountGrids : positionsAccountGrids;
    old.forEach(g => g?.destroy());

    container.innerHTML = '';
    const grids = [];

    const accounts = [...new Set(rows.map(r => r.account))];

    for (const acct of accounts) {
      const section = document.createElement('div');
      section.className = 'mb-4';

      const heading = document.createElement('h3');
      heading.className = 'section-heading';
      heading.textContent = acct;
      section.appendChild(heading);

      const gridDiv = document.createElement('div');
      gridDiv.className = 'ag-theme-quartz ag-theme-ramboq w-full';
      section.appendChild(gridDiv);

      container.appendChild(section);

      const grid = createGrid(gridDiv, {
        columnDefs: colDefs,
        rowData: rows.filter(r => r.account === acct),
        defaultColDef: defaultCol,
        domLayout: 'autoHeight',
      });
      grids.push(grid);
    }

    if (container === holdingsAccountsContainer) holdingsAccountGrids = grids;
    else positionsAccountGrids = grids;
  }

  function applyData(h, p, f) {
    updateGrid(holdingsSummaryGrid,  h.summary ?? []);
    updateGrid(holdingsAllGrid,      h.rows    ?? []);
    updateGrid(positionsSummaryGrid, p.summary ?? []);
    updateGrid(positionsAllGrid,     p.rows    ?? []);
    updateGrid(fundsGrid,            f.rows    ?? []);
    lastRefresh = h.refreshed_at ?? '';

    // Build per-account grids
    if (holdingsAccountsContainer && h.rows?.length) {
      buildAccountGrids(holdingsAccountsContainer, h.rows, holdingsAcctCols);
    }
    if (positionsAccountsContainer && p.rows?.length) {
      buildAccountGrids(positionsAccountsContainer, p.rows, positionsAcctCols);
    }
  }

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
    holdingsAllGrid      = makeGrid(holdingsAllEl,      holdingsCols);
    positionsSummaryGrid = makeGrid(positionsSummaryEl, positionsSummaryCols);
    positionsAllGrid     = makeGrid(positionsAllEl,     positionsCols);
    fundsGrid            = makeGrid(fundsEl,            fundsCols);

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
    [holdingsSummaryGrid, holdingsAllGrid, positionsSummaryGrid, positionsAllGrid, fundsGrid,
     ...holdingsAccountGrids, ...positionsAccountGrids]
      .forEach(g => g?.destroy());
  });
</script>

<div class="flex items-center justify-between mb-3">
  <div class="text-xs text-muted">
    {#if loading && !lastRefresh}
      <span class="animate-pulse">Loading…</span>
    {:else if lastRefresh}
      <span>{lastRefresh}</span>
    {/if}
  </div>
  <div class="flex items-center gap-2">
    {#if loading && lastRefresh}
      <span class="text-xs text-muted animate-pulse">Refreshing…</span>
    {/if}
    <button onclick={loadAll} disabled={loading} class="btn-secondary disabled:opacity-50">Refresh</button>
  </div>
</div>

<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
  {#if error}
    <div class="mb-4 p-3 rounded bg-red-50 text-red-700 text-sm border border-red-200">{error}</div>
  {/if}

  <!-- Tabs -->
  <div class="flex border-b border-gray-200 mb-4 gap-0.5">
    {#each [['holdings','Holdings'],['positions','Positions'],['funds','Funds']] as [id, label]}
      <button
        class="px-4 py-1.5 text-xs font-medium border-b-2 transition-colors
               {activeTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
        onclick={() => switchTab(id)}
      >{label}</button>
    {/each}
  </div>

  <section class:hidden={activeTab !== 'holdings'}>
    <h2 class="section-heading">Summary</h2>
    <div bind:this={holdingsSummaryEl} class="ag-theme-quartz ag-theme-ramboq mb-5 w-full"></div>

    <div bind:this={holdingsAccountsContainer} class="mb-5"></div>

    <h2 class="section-heading">All Holdings</h2>
    <div bind:this={holdingsAllEl} class="ag-theme-quartz ag-theme-ramboq w-full"></div>
  </section>

  <section class:hidden={activeTab !== 'positions'}>
    <h2 class="section-heading">Summary</h2>
    <div bind:this={positionsSummaryEl} class="ag-theme-quartz ag-theme-ramboq mb-5 w-full"></div>

    <div bind:this={positionsAccountsContainer} class="mb-5"></div>

    <h2 class="section-heading">All Positions</h2>
    <div bind:this={positionsAllEl} class="ag-theme-quartz ag-theme-ramboq w-full"></div>
  </section>

  <section class:hidden={activeTab !== 'funds'}>
    <h2 class="section-heading">Fund Balances</h2>
    <div bind:this={fundsEl} class="ag-theme-quartz ag-theme-ramboq w-full"></div>
  </section>
</div>

<style>
  .hidden { display: none; }
</style>
