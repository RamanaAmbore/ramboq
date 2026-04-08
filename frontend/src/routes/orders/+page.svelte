<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, logTime } from '$lib/stores';
  import { fetchOrders, placeOrder, cancelOrder, modifyOrder } from '$lib/api';
  import LogPanel from '$lib/LogPanel.svelte';
  import CommandBar from '$lib/CommandBar.svelte';
  import OrderDetail from '$lib/OrderDetail.svelte';
  import { loadInstruments } from '$lib/data/instruments';
  import { loadAccounts } from '$lib/data/accounts';
  import { orderGrammar, buildOrderPayload, setQuoteLoadedCallback, previewSymbol, getLtp } from '$lib/command/grammars/orders';
  import { createPerformanceSocket } from '$lib/ws';

  let orders        = $state([]);
  let loading       = $state(true);
  let error         = $state('');
  let success       = $state('');
  let filterStatus  = $state('all');
  let running       = $state(false);
  let logTab        = $state('order');
  let orderLog      = $state([]);
  let agentLog      = $state([]);
  let systemLog     = $state([]);
  let cmdHistory    = $state([]);
  let selectedOrder = $state(/** @type {any|null} */(null));
  let cmdBar;
  let unsub;
  let logInterval;

  // context for CommandBar — keeps openOrderIds fresh so cancel/modify suggest them
  const cmdContext = $derived({
    openOrders: orders
      .filter(o => o.status === 'OPEN' || o.status === 'TRIGGER PENDING'),
  });

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function loadOrders() {
    loading = true; error = '';
    try { const d = await fetchOrders(); orders = d.rows || []; }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }

  function addResult(/** @type {string} */ status, /** @type {string} */ message, /** @type {Record<string,string>} */ fields = {}) {
    const t = logTime(new Date());
    cmdHistory = [{ status, message, fields, time: t }, ...cmdHistory].slice(0, 100);
    logTab = 'order';
  }

  async function runParsed(parsed) {
    running = true;
    try {
      if (parsed.verb === 'buy' || parsed.verb === 'sell') {
        const payload = buildOrderPayload(parsed);
        const res = await placeOrder(payload);
        addResult('✓', `Order placed`, {
          verb: parsed.verb.toUpperCase(), account: parsed.args.account,
          symbol: payload.tradingsymbol, exchange: payload.exchange,
          qty: String(payload.quantity), type: payload.order_type,
          price: String(payload.price || ''), product: payload.product,
          id: res.order_id,
        });
      } else if (parsed.verb === 'cancel') {
        const id = parsed.args.order_id;
        const ord = orders.find(o => o.order_id === id);
        if (!ord) throw new Error(`order ${id} not found`);
        await cancelOrder(id, ord.account);
        addResult('✓', `Order cancelled`, { id, symbol: ord.tradingsymbol });
      } else if (parsed.verb === 'modify') {
        const id = parsed.args.order_id;
        const ord = orders.find(o => o.order_id === id);
        if (!ord) throw new Error(`order ${id} not found`);
        const p = { account: ord.account };
        if (parsed.kwargs.price != null) p.price = parsed.kwargs.price;
        if (parsed.kwargs.qty != null) p.quantity = parsed.kwargs.qty;
        await modifyOrder(id, p);
        const mods = {};
        if (parsed.kwargs.price != null) mods.price = String(parsed.kwargs.price);
        if (parsed.kwargs.qty != null) mods.qty = String(parsed.kwargs.qty);
        addResult('✓', `Order modified`, { id, ...mods });
      }
      await loadOrders();
      cmdBar?.clear();
    } catch (e) {
      addResult('✗', e.message, {});
    } finally {
      running = false;
    }
  }

  async function loadOrderLog() {
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      orderLog = await res.json().catch(() => []);
    } catch (e) { /* ignore */ }
  }
  async function loadAgentLog() {
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      agentLog = await res.json().catch(() => []);
    } catch (e) { /* ignore */ }
  }
  async function loadSystemLog() {
    try {
      const res = await fetch('/api/admin/logs?n=100', { headers: authHeaders() });
      const d = await res.json().catch(() => ({}));
      systemLog = d.lines || [];
    } catch (e) { /* ignore */ }
  }
  function loadCurrentLog() {
    if (logTab === 'order') loadOrderLog();
    else if (logTab === 'agent') loadAgentLog();
    else if (logTab === 'system') loadSystemLog();
  }

  function orderEnrichPairs(pairs) {
    return pairs.map(p => {
      if (p.role === 'symbol' && p.status === 'filled' && p.value) {
        const ltp = getLtp(p.value);
        if (ltp) return { ...p, value: `${p.value}:${ltp}` };
      }
      return p;
    });
  }
  const statusColor = (/** @type {string} */ s) => {
    const c = s?.toUpperCase();
    if (c === 'COMPLETE') return 'border-green-500 bg-green-50';
    if (c === 'REJECTED' || c === 'CANCELLED') return 'border-red-400 bg-red-50';
    if (c === 'OPEN' || c === 'TRIGGER PENDING') return 'border-amber-400 bg-amber-50';
    return 'border-gray-300 bg-white';
  };
  const txnColor = (/** @type {string} */ t) => t === 'BUY' ? 'text-green-700' : 'text-red-600';
  // Industry standard: distinct hues per account, readable on white bg
  const ACCT_COLORS = ['text-blue-700', 'text-orange-600', 'text-purple-700', 'text-teal-700'];
  const _acctList = /** @type {string[]} */ ([]);
  const acctColor = (/** @type {string} */ a) => {
    let idx = _acctList.indexOf(a);
    if (idx < 0) { _acctList.push(a); idx = _acctList.length - 1; }
    return ACCT_COLORS[idx % ACCT_COLORS.length];
  };

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadOrders(); loadCurrentLog();
    loadAccounts().catch(() => {});
    loadInstruments().catch(() => {});
    // When an async quote fetch completes, re-render the command bar so the
    // price ladder popup appears without the user having to type another char.
    setQuoteLoadedCallback(() => cmdBar?.refresh());
    unsub = createPerformanceSocket((msg) => {
      if (msg.event === 'order_update') {
        const fields = {
          status: msg.status, verb: msg.transaction_type,
          symbol: msg.tradingsymbol, qty: String(msg.quantity || ''),
          ...(msg.price ? { price: String(msg.price) } : {}),
          ...(msg.account ? { account: msg.account } : {}),
          id: msg.order_id,
        };
        const statusIcon = msg.status === 'COMPLETE' ? '✓' : msg.status === 'REJECTED' ? '✗' : '⟳';
        addResult(statusIcon, `Postback: ${msg.status}${msg.status_message ? ' — ' + msg.status_message : ''}`, fields);
        loadOrders();
      } else if (msg.event === 'performance_updated') {
        loadOrders();
      }
    });
    logInterval = setInterval(loadCurrentLog, 30000);
  });
  onDestroy(() => { unsub?.(); if (logInterval) clearInterval(logInterval); });
</script>

<svelte:head><title>Orders | RamboQuant Analytics</title></svelte:head>

<div class="flex flex-col h-[calc(100vh-8rem)]">
<div class="flex items-center justify-between mb-1">
  <h1 class="page-title-chip">Orders</h1>
  <span class="text-[0.6rem] text-muted">{clientTimestamp()}</span>
</div>

{#if error}<div class="mb-1 p-1.5 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>{/if}
{#if success}<div class="mb-1 p-1.5 rounded bg-green-50 text-green-700 text-xs border border-green-200">{success}</div>{/if}

<!-- Order Entry -->
<div class="mt-2 mb-1 relative">
  <CommandBar
    bind:this={cmdBar}
    grammar={orderGrammar}
    context={cmdContext}
    rows={2}
    placeholder={cmdContext.openOrders?.length
      ? "buy | sell | cancel | modify"
      : "buy | sell"}
    onsubmit={runParsed}
    previewFn={previewSymbol}
    enrichPairs={orderEnrichPairs}
    disabled={running}
  />
  <div class="absolute bottom-6 right-2 flex gap-1 z-10">
    <button onclick={() => cmdBar?.submit()} disabled={running}
      class="text-[0.6rem] py-0.5 px-2.5 rounded-sm border border-teal-300 bg-teal-50 text-teal-700 hover:bg-teal-100 font-medium disabled:opacity-50">Submit</button>
    <button onclick={() => cmdBar?.clear()}
      class="text-[0.6rem] py-0.5 px-2.5 rounded-sm border border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100 font-medium">Clear</button>
  </div>
</div>

<!-- Status Dashboard -->
<div class="grid grid-cols-5 gap-2">
  <button onclick={() => filterStatus = 'all'}
    class="rounded-lg border-2 bg-white border-gray-300 p-2 text-center {filterStatus === 'all' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-xs font-bold text-primary">{orders.length}</div>
    <div class="text-[0.55rem] text-muted uppercase">All</div>
  </button>
  <button onclick={() => filterStatus = 'open'}
    class="rounded-lg border-2 bg-amber-50 border-amber-400 p-2 text-center {filterStatus === 'open' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-xs font-bold text-amber-600">{orders.filter(o => o.status === 'OPEN' || o.status === 'TRIGGER PENDING').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Open</div>
  </button>
  <button onclick={() => filterStatus = 'complete'}
    class="rounded-lg border-2 bg-green-50 border-green-500 p-2 text-center {filterStatus === 'complete' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-xs font-bold text-green-600">{orders.filter(o => o.status === 'COMPLETE').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Filled</div>
  </button>
  <button onclick={() => filterStatus = 'rejected'}
    class="rounded-lg border-2 bg-red-50 border-red-400 p-2 text-center {filterStatus === 'rejected' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-xs font-bold text-red-600">{orders.filter(o => o.status === 'REJECTED').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Rejected</div>
  </button>
  <button onclick={() => filterStatus = 'cancelled'}
    class="rounded-lg border-2 bg-gray-50 border-gray-400 p-2 text-center {filterStatus === 'cancelled' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-xs font-bold text-gray-600">{orders.filter(o => o.status === 'CANCELLED').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Cancelled</div>
  </button>
</div>

<!-- Order Cards -->
{#if loading && !orders.length}
  <div class="text-center text-muted text-xs animate-pulse py-2">Loading orders…</div>
{:else if orders.length}
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-1 max-h-[8rem] overflow-y-auto">
    {#each orders.filter(o => filterStatus === 'all' ? true : filterStatus === 'open' ? (o.status === 'OPEN' || o.status === 'TRIGGER PENDING') : o.status === filterStatus.toUpperCase()) as o}
      <button type="button" onclick={() => selectedOrder = (selectedOrder?.order_id === o.order_id ? null : o)}
        class="text-left rounded-lg border-2 {statusColor(o.status)} p-2.5 hover:brightness-95 transition">
        <div class="flex items-center justify-between mb-0.5">
          <span class="font-semibold text-xs"><span class="{txnColor(o.transaction_type)}">{o.transaction_type}</span> <span class="{acctColor(o.account)}">{o.account}</span> <span class="{o.status === 'COMPLETE' ? 'text-green-700' : o.status === 'REJECTED' || o.status === 'CANCELLED' ? 'text-red-600' : 'text-amber-700'}">{o.tradingsymbol}</span></span>
          <span class="text-[0.55rem] px-1.5 py-0.5 rounded font-medium uppercase
            {o.status === 'COMPLETE' ? 'bg-green-100 text-green-700' : o.status === 'REJECTED' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}">{o.status}</span>
        </div>
        <div class="text-[0.55rem] text-gray-700 flex flex-wrap gap-x-2 uppercase">
          <span>QTY:<b>{o.filled_quantity}/{o.quantity}</b></span>
          <span>TYPE:<b>{o.order_type}</b></span>
          <span>PRICE:<b>{o.average_price || o.price || '—'}</b></span>
          <span>PRODUCT:<b>{o.product}</b></span>
          <span>EXCH:<b>{o.exchange}</b></span>
          {#if o.status_message}<span>MSG:<b>{o.status_message}</b></span>{/if}
        </div>
      </button>
    {/each}
  </div>
{:else}
  <div class="text-center text-muted text-xs py-1 mb-1">No orders today.</div>
{/if}

<OrderDetail order={selectedOrder}
  onclose={() => selectedOrder = null}
  onchanged={async () => { await loadOrders(); if (selectedOrder) selectedOrder = orders.find(o => o.order_id === selectedOrder.order_id) || null; }}
/>

<LogPanel
  heightClass="flex-1 min-h-0"
  initialTab={logTab}
  {cmdHistory}
  {orderLog}
  {agentLog}
  {systemLog}
  onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
/>
</div>
