<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGrid, ModuleRegistry, AllCommunityModule } from 'ag-grid-community';
  import { fetchOrders, fetchAccounts, placeOrder, cancelOrder } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';

  ModuleRegistry.registerModules([AllCommunityModule]);

  // ── State ──────────────────────────────────────────────────────────────────
  let accounts    = [];
  let lastRefresh = '';
  let loading     = false;
  let error       = '';
  let successMsg  = '';

  // Order form
  let showForm  = false;
  let placing   = false;
  let formError = '';
  let form = {
    account:          '',
    exchange:         'NSE',
    tradingsymbol:    '',
    transaction_type: 'BUY',
    order_type:       'MARKET',
    product:          'CNC',
    quantity:         1,
    price:            '',
    trigger_price:    '',
    validity:         'DAY',
    variety:          'regular',
  };

  // AG Grid
  let ordersEl   = null;
  let ordersGrid = null;

  // ── Column defs ────────────────────────────────────────────────────────────
  const statusCellStyle = ({ value }) => {
    if (!value) return {};
    const v = value.toUpperCase();
    if (v === 'COMPLETE')                        return { color: '#27ae60', fontWeight: '600' };
    if (v === 'REJECTED' || v === 'CANCELLED')   return { color: '#c0392b' };
    if (v === 'OPEN' || v === 'TRIGGER PENDING') return { color: '#2a5298', fontWeight: '600' };
    return {};
  };

  const txnCellStyle = ({ value }) =>
    value === 'BUY'
      ? { color: '#27ae60', fontWeight: '600' }
      : { color: '#c0392b', fontWeight: '600' };

  const numFmt = ({ value }) =>
    value == null || value === 0
      ? '—'
      : Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 });

  // Cancel button rendered inside the grid for OPEN orders
  const cancelRenderer = (/** @type {{ data: { status: string, order_id: string, account: string, variety: string } }} */ params) => {
    const status = (params.data?.status ?? '').toUpperCase();
    if (status !== 'OPEN' && status !== 'TRIGGER PENDING') return '';
    const btn = document.createElement('button');
    btn.textContent = 'Cancel';
    btn.className   = 'px-2 py-0.5 text-xs rounded border border-red-400 text-red-600 hover:bg-red-50';
    btn.addEventListener('click', () => {
      handleCancel(params.data.order_id, params.data.account, params.data.variety);
    });
    return btn;
  };

  const orderCols = [
    { field: 'account',          headerName: 'Account',   width: 110 },
    { field: 'order_timestamp',  headerName: 'Time',      width: 155 },
    { field: 'tradingsymbol',    headerName: 'Symbol',    flex: 1 },
    { field: 'exchange',         headerName: 'Exch',      width: 70 },
    { field: 'transaction_type', headerName: 'B/S',       width: 60,  cellStyle: txnCellStyle },
    { field: 'quantity',         headerName: 'Qty',       width: 70,  type: 'numericColumn' },
    { field: 'pending_quantity', headerName: 'Pending',   width: 80,  type: 'numericColumn' },
    { field: 'order_type',       headerName: 'Type',      width: 85 },
    { field: 'product',          headerName: 'Product',   width: 80 },
    { field: 'price',            headerName: 'Price',     width: 95,  valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'average_price',    headerName: 'Avg',       width: 95,  valueFormatter: numFmt, type: 'numericColumn' },
    { field: 'status',           headerName: 'Status',    width: 140, cellStyle: statusCellStyle },
    { field: 'status_message',   headerName: 'Message',   flex: 1 },
    { headerName: '',            width: 80,  cellRenderer: cancelRenderer, sortable: false, filter: false },
  ];

  // ── Actions ────────────────────────────────────────────────────────────────
  async function loadOrders() {
    loading = true;
    error   = '';
    try {
      const data = await fetchOrders();
      ordersGrid?.setGridOption('rowData', data.rows ?? []);
      lastRefresh = data.refreshed_at ?? '';
    } catch (e) {
      error = /** @type {Error} */ (e).message;
    } finally {
      loading = false;
    }
  }

  async function handleCancel(/** @type {string} */ orderId, /** @type {string} */ account, /** @type {string} */ variety) {
    if (!confirm(`Cancel order ${orderId}?`)) return;
    successMsg = '';
    error      = '';
    try {
      await cancelOrder(orderId, account, variety);
      successMsg = `Order ${orderId} cancelled`;
      await loadOrders();
    } catch (e) {
      error = /** @type {Error} */ (e).message;
    }
  }

  async function submitOrder() {
    placing    = true;
    formError  = '';
    successMsg = '';
    try {
      const payload = {
        ...form,
        quantity:      Number(form.quantity),
        price:         form.price         ? Number(form.price)         : null,
        trigger_price: form.trigger_price ? Number(form.trigger_price) : null,
      };
      const res = await placeOrder(payload);
      successMsg = `Order ${res.order_id} placed for ${res.account}`;
      showForm   = false;
      resetForm();
      await loadOrders();
    } catch (e) {
      formError = /** @type {Error} */ (e).message;
    } finally {
      placing = false;
    }
  }

  function resetForm() {
    form = {
      account:          accounts[0]?.account_id ?? '',
      exchange:         'NSE',
      tradingsymbol:    '',
      transaction_type: 'BUY',
      order_type:       'MARKET',
      product:          'CNC',
      quantity:         1,
      price:            '',
      trigger_price:    '',
      validity:         'DAY',
      variety:          'regular',
    };
  }

  $: needsPrice   = form.order_type === 'LIMIT' || form.order_type === 'SL';
  $: needsTrigger = form.order_type === 'SL'    || form.order_type === 'SL-M';

  // ── Lifecycle ──────────────────────────────────────────────────────────────
  let unsub;

  onMount(async () => {
    ordersGrid = createGrid(ordersEl, {
      columnDefs: orderCols,
      rowData: [],
      defaultColDef: { resizable: true, sortable: true, filter: true },
      domLayout: 'autoHeight',
    });

    const [, accts] = await Promise.all([loadOrders(), fetchAccounts()]);
    accounts       = accts.accounts ?? [];
    form.account   = accounts[0]?.account_id ?? '';

    unsub = createPerformanceSocket(() => loadOrders());
  });

  onDestroy(() => {
    unsub?.();
    ordersGrid?.destroy();
  });
</script>

<!-- ── Header ──────────────────────────────────────────────────────────────── -->
<div class="flex items-center justify-between mb-4">
  <div>
    <h1 class="page-heading mb-0">Orders</h1>
    {#if lastRefresh}
      <p class="text-xs text-muted mt-0.5">{lastRefresh}</p>
    {/if}
  </div>
  <div class="flex items-center gap-2">
    {#if loading}
      <span class="text-xs text-muted animate-pulse">Refreshing…</span>
    {/if}
    <button on:click={loadOrders} disabled={loading} class="btn-secondary disabled:opacity-50">
      Refresh
    </button>
    <button
      on:click={() => { showForm = !showForm; formError = ''; successMsg = ''; }}
      class="btn-primary"
    >
      {showForm ? 'Close' : '+ New Order'}
    </button>
  </div>
</div>

{#if successMsg}
  <div class="mb-4 p-3 rounded bg-green-50 text-green-700 text-sm border border-green-200">
    {successMsg}
  </div>
{/if}

{#if error}
  <div class="mb-4 p-3 rounded bg-red-50 text-red-700 text-sm border border-red-200">{error}</div>
{/if}

<!-- ── Order form ─────────────────────────────────────────────────────────── -->
{#if showForm}
  <div class="mb-6 p-5 bg-white rounded-lg border border-gray-200 shadow-sm">
    <h2 class="text-sm font-semibold text-gray-700 mb-4">Place Order</h2>

    {#if formError}
      <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-sm border border-red-200">{formError}</div>
    {/if}

    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">

      <div>
        <label class="field-label" for="f-account">Account</label>
        <select id="f-account" bind:value={form.account} class="field-input">
          {#each accounts as a}
            <option value={a.account_id}>{a.display}</option>
          {/each}
        </select>
      </div>

      <div>
        <label class="field-label" for="f-txn">Buy / Sell</label>
        <select id="f-txn" bind:value={form.transaction_type}
          class="field-input font-semibold {form.transaction_type === 'BUY' ? 'text-green-700' : 'text-red-700'}">
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </div>

      <div>
        <label class="field-label" for="f-exch">Exchange</label>
        <select id="f-exch" bind:value={form.exchange} class="field-input">
          {#each ['NSE','BSE','NFO','MCX','CDS','BFO'] as ex}
            <option>{ex}</option>
          {/each}
        </select>
      </div>

      <div class="col-span-2 sm:col-span-1">
        <label class="field-label" for="f-sym">Symbol</label>
        <input
          id="f-sym"
          bind:value={form.tradingsymbol}
          placeholder="e.g. RELIANCE"
          class="field-input"
          on:input={(e) => form.tradingsymbol = /** @type {HTMLInputElement} */(e.target).value.toUpperCase()}
        />
      </div>

      <div>
        <label class="field-label" for="f-otype">Order Type</label>
        <select id="f-otype" bind:value={form.order_type} class="field-input">
          {#each ['MARKET','LIMIT','SL','SL-M'] as ot}
            <option>{ot}</option>
          {/each}
        </select>
      </div>

      <div>
        <label class="field-label" for="f-product">Product</label>
        <select id="f-product" bind:value={form.product} class="field-input">
          {#each ['CNC','MIS','NRML'] as p}
            <option>{p}</option>
          {/each}
        </select>
      </div>

      <div>
        <label class="field-label" for="f-qty">Quantity</label>
        <input id="f-qty" type="number" min="1" bind:value={form.quantity} class="field-input" />
      </div>

      {#if needsPrice}
        <div>
          <label class="field-label" for="f-price">Price</label>
          <input id="f-price" type="number" step="0.05" bind:value={form.price} class="field-input" placeholder="0.00" />
        </div>
      {/if}

      {#if needsTrigger}
        <div>
          <label class="field-label" for="f-trigger">Trigger Price</label>
          <input id="f-trigger" type="number" step="0.05" bind:value={form.trigger_price} class="field-input" placeholder="0.00" />
        </div>
      {/if}

      <div>
        <label class="field-label" for="f-validity">Validity</label>
        <select id="f-validity" bind:value={form.validity} class="field-input">
          <option>DAY</option>
          <option>IOC</option>
        </select>
      </div>

    </div>

    <div class="mt-5 flex gap-3">
      <button
        on:click={submitOrder}
        disabled={placing || !form.tradingsymbol || !form.account}
        class="px-5 py-2 text-sm font-semibold rounded transition-colors disabled:opacity-50
               {form.transaction_type === 'BUY'
                 ? 'bg-green-600 hover:bg-green-700 text-white'
                 : 'bg-red-600   hover:bg-red-700   text-white'}"
      >
        {placing ? 'Placing…' : `${form.transaction_type} ${form.tradingsymbol || '—'}`}
      </button>
      <button
        on:click={() => { showForm = false; resetForm(); formError = ''; }}
        class="px-4 py-2 text-sm rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
      >
        Cancel
      </button>
    </div>
  </div>
{/if}

<!-- ── Order book ─────────────────────────────────────────────────────────── -->
<div bind:this={ordersEl} class="ag-theme-quartz ag-theme-ramboq w-full"></div>

<style>
  :global(.field-label) {
    display: block;
    font-size: 0.7rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.25rem;
  }
  :global(.field-input) {
    width: 100%;
    padding: 0.375rem 0.5rem;
    font-size: 0.875rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    background: white;
    outline: none;
  }
  :global(.field-input:focus) {
    border-color: #2a5298;
    box-shadow: 0 0 0 2px rgba(42,82,152,0.15);
  }
</style>
