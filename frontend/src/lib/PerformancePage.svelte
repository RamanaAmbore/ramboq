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

  const { theme = 'ag-theme-ramboq' } = $props();
  const isDark = $derived(theme === 'ag-theme-algo');

  // Read tab from URL ?tab= param; default to 'positions'
  const validTabs = ['positions', 'holdings'];
  let activeTab = $state(validTabs.includes(page.url.searchParams.get('tab')) ? page.url.searchParams.get('tab') : 'positions');

  let orderRow = $state(/** @type {any|null} */(null));
  let orderSource = $state('holdings');

  function openOrderPopup(row, source) {
    if ($authStore.user?.role !== 'admin') return;
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

  let holdingsAccountsContainer = null;
  let positionsAccountsContainer = null;

  let holdingsAccountGrids  = [];
  let positionsAccountGrids = [];

  const numFmt  = ({ value }) =>
    value == null ? '' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const pctFmt  = ({ value }) =>
    value == null ? '' : `${Number(value).toFixed(2)}%`;
  const maskAcct = ({ value }) =>
    value ? String(value).replace(/\d/g, '#') : value;
  const loss  = () => ({ color: '#c0392b', backgroundColor: 'rgba(192,57,43,0.06)'  });
  const gain  = () => ({ color: '#27ae60', backgroundColor: 'rgba(39,174,96,0.06)'  });
  const zero  = () => ({ color: '#999' });

  const pnlStyle     = ({ value }) => value < 0 ? loss() : value > 0 ? gain() : zero();
  const qtyStyle     = ({ value }) => value < 0 ? loss() : value > 0 ? gain() : zero();
  const avgVsLtpStyle = (params) => {
    const avg = params.data?.average_price;
    const ltp = params.data?.close_price;
    if (avg == null || ltp == null) return {};
    return avg > ltp ? loss() : avg < ltp ? gain() : zero();
  };

  const defaultCol = { resizable: true, sortable: true, filter: true, suppressHeaderMenuButton: true, flex: 1, minWidth: 65 };

  const getRowClass = (params) => params.data?.tradingsymbol === 'TOTAL' ? 'totals-row' : '';

  const acctFill = 'ag-col-fill';
  const symFill  = 'ag-col-fill';

  const holdingsSummaryCols = [
    { field: 'account',               headerName: 'Account',  width: 75, minWidth: 75, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'cur_val',               headerName: 'Cur Val',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'inv_val',               headerName: 'Inv Val',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'pnl',                   headerName: 'P&L',      flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',    width: 70, valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',  flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',    width: 70, valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  const holdingsCols = [
    { field: 'account',               headerName: 'Account',  width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'tradingsymbol',         headerName: 'Symbol',   width: 120, pinned: 'left', cellClass: symFill, headerClass: symFill },
    { field: 'pnl',                   headerName: 'P&L',      width: 90,  valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'pnl_percentage',        headerName: 'P&L %',    width: 70,  valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_val',        headerName: 'Day P&L',  width: 90,  valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'day_change_percentage', headerName: 'Day %',    width: 70,  valueFormatter: pctFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'quantity',              headerName: 'Qty',      width: 60,  type: 'numericColumn' },
    { field: 'average_price',         headerName: 'Avg Price', width: 90, valueFormatter: numFmt, type: 'numericColumn', cellStyle: avgVsLtpStyle },
    { field: 'close_price',           headerName: 'LTP',      width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellStyle: avgVsLtpStyle },
    { field: 'cur_val',               headerName: 'Cur Val',  width: 100, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  const holdingsAcctCols = holdingsCols.filter(c => c.field !== 'account');

  const positionsSummaryCols = [
    { field: 'account', headerName: 'Account', width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'pnl',     headerName: 'P&L',     flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
  ];

  const positionsCols = [
    { field: 'account',       headerName: 'Account',   width: 90, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'tradingsymbol', headerName: 'Symbol',    width: 150, pinned: 'left', cellClass: symFill, headerClass: symFill },
    { field: 'pnl',           headerName: 'P&L',       width: 90,  valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'unrealised',    headerName: 'Unrealised', width: 90, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'realised',      headerName: 'Realised',  width: 90,  valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'quantity',      headerName: 'Qty',       width: 60,  type: 'numericColumn', cellStyle: qtyStyle },
    { field: 'average_price', headerName: 'Avg Price', width: 90,  valueFormatter: numFmt, type: 'numericColumn', cellStyle: avgVsLtpStyle },
    { field: 'close_price',   headerName: 'LTP',       width: 80,  valueFormatter: numFmt, type: 'numericColumn', cellStyle: avgVsLtpStyle },
  ];

  const positionsAcctCols = positionsCols.filter(c => c.field !== 'account');

  const fundsCols = [
    { field: 'account',      headerName: 'Account',      width: 120, cellClass: acctFill, headerClass: acctFill, valueFormatter: maskAcct },
    { field: 'cash',         headerName: 'Cash',         flex: 1, valueFormatter: numFmt, cellStyle: pnlStyle, type: 'numericColumn' },
    { field: 'avail_margin', headerName: 'Avail Margin', flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'used_margin',  headerName: 'Used Margin',  flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'collateral',   headerName: 'Collateral',   flex: 1, valueFormatter: numFmt, type: 'numericColumn' },
  ];

  function makeGrid(el, colDefs, rowData = [], onRowClick = null) {
    return createGrid(el, {
      columnDefs: colDefs,
      rowData,
      defaultColDef: defaultCol,
      overlayNoRowsTemplate: '<span style="font-size:0.65rem;color:#999">—</span>',
      domLayout: 'autoHeight',
      getRowClass,
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

  function buildAccountGrids(container, rows, colDefs, source = 'holdings') {
    const old = container === holdingsAccountsContainer ? holdingsAccountGrids : positionsAccountGrids;
    old.forEach(g => g?.destroy());

    container.innerHTML = '';
    const grids = [];

    const accounts = [...new Set(rows.map(r => r.account))];

    for (const acct of accounts) {
      const acctRows = rows.filter(r => r.account === acct);

      const totalsRow = source === 'holdings'
        ? makeHoldingsTotals(acctRows)
        : makePositionsTotals(acctRows);

      const section = document.createElement('div');
      section.className = 'mb-4';

      const heading = document.createElement('h3');
      heading.className = 'section-heading';
      heading.textContent = acct.replace(/\d/g, '#');
      section.appendChild(heading);

      const gridDiv = document.createElement('div');
      gridDiv.className = `ag-theme-quartz ${theme} w-full`;
      section.appendChild(gridDiv);

      container.appendChild(section);

      const grid = createGrid(gridDiv, {
        columnDefs: colDefs,
        rowData: [...acctRows, totalsRow],
        defaultColDef: defaultCol,
        domLayout: 'autoHeight',
        getRowClass,
        onRowClicked: (e) => openOrderPopup(e.data, source),
      });
      grids.push(grid);
    }

    if (container === holdingsAccountsContainer) holdingsAccountGrids = grids;
    else positionsAccountGrids = grids;
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

  function applyData(h, p, f) {
    const holdingsTotals  = makeHoldingsTotals(h.rows);
    const positionsTotals = makePositionsTotals(p.rows);

    updateGrid(holdingsSummaryGrid,  h.summary ?? []);
    updateGrid(holdingsAllGrid,      h.rows ? [...h.rows, holdingsTotals] : []);
    updateGrid(positionsSummaryGrid, p.summary ?? []);
    updateGrid(positionsAllGrid,     p.rows ? [...p.rows, positionsTotals] : []);
    updateGrid(fundsGrid,             f.rows    ?? []);
    lastRefresh = h.refreshed_at ?? '';

    if (holdingsAccountsContainer && h.rows?.length) {
      buildAccountGrids(holdingsAccountsContainer, h.rows, holdingsAcctCols, 'holdings');
    }
    if (positionsAccountsContainer && p.rows?.length) {
      buildAccountGrids(positionsAccountsContainer, p.rows, positionsAcctCols, 'positions');
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
     positionsSummaryGrid, positionsAllGrid,
     ...holdingsAccountGrids, ...positionsAccountGrids]
      .forEach(g => g?.destroy());
  });
</script>

<div class:perf-dark={isDark}>

{#if error}
  <div class="mb-3 p-3 rounded bg-red-50 text-red-700 text-sm border border-red-200">{error}</div>
{/if}

<div class="flex items-center justify-between mb-2">
  <div class="text-[0.65rem] text-muted">
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

<h2 class="section-heading">Fund Balances</h2>
<div bind:this={fundsEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

<div class="flex gap-0.5 mb-3">
  {#each [['positions','Positions'],['holdings','Holdings']] as [id, label]}
    <button
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
             {activeTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
      onclick={() => switchTab(id)}
    >{label}</button>
  {/each}
</div>

<section class:hidden={activeTab !== 'positions'}>
  <h2 class="section-heading">Summary</h2>
  <div bind:this={positionsSummaryEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

  <div bind:this={positionsAccountsContainer} class="mb-4"></div>

  <h2 class="section-heading">All Positions</h2>
  <div bind:this={positionsAllEl} class="ag-theme-quartz {theme} w-full"></div>
</section>

<section class:hidden={activeTab !== 'holdings'}>
  <h2 class="section-heading">Summary</h2>
  <div bind:this={holdingsSummaryEl} class="ag-theme-quartz {theme} mb-4 w-full"></div>

  <div bind:this={holdingsAccountsContainer} class="mb-4"></div>

  <h2 class="section-heading">All Holdings</h2>
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
  /* ── Dark (algo) overrides ─────────────────────────────────────────────── */
  .perf-dark :global(.section-heading) { color: #d97706; }

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

  /* Timestamp */
  .perf-dark :global(.text-muted) { color: rgba(180,200,230,0.55) !important; }
</style>
