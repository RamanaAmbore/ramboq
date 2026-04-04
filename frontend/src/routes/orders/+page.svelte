<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp } from '$lib/stores';
  import { fetchOrders, fetchAccounts, placeOrder, cancelOrder } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';

  let orders        = $state([]);
  let accounts      = $state([]);
  let loading       = $state(true);
  let error         = $state('');
  let filterStatus  = $state('all');
  let success     = $state('');
  let command     = $state('');
  let cmdOutput   = $state('');
  let running     = $state(false);
  let logTab      = $state('order');  // order | agent | system
  let orderLog    = $state([]);
  let agentLog    = $state([]);
  let systemLog   = $state([]);
  let logEl;
  let unsub;
  let logInterval;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function loadOrders() {
    loading = true; error = '';
    try {
      const data = await fetchOrders();
      orders = data.rows || [];
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }

  async function loadAccounts() {
    try { const data = await fetchAccounts(); accounts = data.accounts || []; }
    catch (e) { /* ignore */ }
  }

  async function doCancel(/** @type {string} */ orderId, /** @type {string} */ account) {
    try {
      await cancelOrder(orderId, account);
      success = `Order ${orderId} cancelled`;
      await loadOrders();
    } catch (e) { error = e.message; }
  }

  // Command line order: buy ACCOUNT SYMBOL QTY [LIMIT PRICE]
  async function runCommand() {
    if (!command.trim()) return;
    running = true; cmdOutput = '';
    const parts = command.trim().split(/\s+/);
    const txn = parts[0]?.toUpperCase();
    if ((txn === 'BUY' || txn === 'SELL') && parts.length >= 4) {
      try {
        const payload = {
          account: parts[1], tradingsymbol: parts[2], quantity: parseInt(parts[3]) || 0,
          transaction_type: txn, exchange: 'NFO', product: 'NRML',
          order_type: (parts[4] || 'MARKET').toUpperCase(),
          price: parseFloat(parts[5]) || 0, validity: 'DAY', variety: 'regular',
        };
        const res = await placeOrder(payload);
        cmdOutput = `✓ Order placed: ${txn} ${parts[3]} ${parts[2]} | ID: ${res.order_id}`;
        await loadOrders();
      } catch (e) { cmdOutput = `✗ ${e.message}`; }
    } else {
      cmdOutput = 'Syntax: buy|sell ACCOUNT SYMBOL QTY [MARKET|LIMIT] [PRICE]';
    }
    running = false;
  }

  // Log loading
  async function loadOrderLog() {
    // Order events from agent events or system log
    try {
      const res = await fetch('/api/agents/events/recent?n=50', { headers: authHeaders() });
      const data = await res.json().catch(() => []);
      orderLog = (Array.isArray(data) ? data : []).filter(e =>
        e.event_type?.includes('order') || e.event_type?.includes('action'));
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
    else loadSystemLog();
  }

  const statusColor = (/** @type {string} */ s) => {
    const c = s?.toUpperCase();
    if (c === 'COMPLETE') return 'border-green-500 bg-green-50';
    if (c === 'REJECTED' || c === 'CANCELLED') return 'border-red-400 bg-red-50';
    if (c === 'OPEN' || c === 'TRIGGER PENDING') return 'border-amber-400 bg-amber-50';
    return 'border-gray-300 bg-white';
  };

  const txnColor = (/** @type {string} */ t) =>
    t === 'BUY' ? 'text-green-600' : 'text-red-600';

  const eventIcon = (/** @type {string} */ t) => ({
    triggered:'🟠', alert_sent:'🟡', action_success:'🟢', action_failed:'🔴',
    order_placed:'📝', order_filled:'✅', order_cancelled:'❌',
  }[t] || '⚪');

  const logLineColor = (/** @type {string} */ line) => {
    if (line.includes('ERROR')) return 'bg-red-900/30 text-red-300';
    if (line.includes('WARNING')) return 'bg-amber-900/20 text-amber-300';
    return 'text-gray-300';
  };

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadOrders(); loadAccounts(); loadCurrentLog();
    unsub = createPerformanceSocket(() => loadOrders());
    logInterval = setInterval(loadCurrentLog, 30000);
  });

  onDestroy(() => { unsub?.(); if (logInterval) clearInterval(logInterval); });
</script>

<svelte:head><title>Orders | RamboQuant Analytics</title></svelte:head>

<div class="text-xs text-muted mb-2">
  {clientTimestamp()}
</div>

{#if error}
  <div class="mb-2 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
{/if}
{#if success}
  <div class="mb-2 p-2 rounded bg-green-50 text-green-700 text-xs border border-green-200">{success}</div>
{/if}

<!-- Command line -->
<div class="flex gap-2 mb-3">
  <input
    bind:value={command}
    class="field-input font-mono text-xs flex-1"
    placeholder="buy ACCOUNT SYMBOL QTY [LIMIT PRICE]"
    onkeydown={(e) => e.key === 'Enter' && runCommand()}
  />
  <button onclick={runCommand} disabled={running} class="btn-primary text-[0.65rem] py-1 px-3 disabled:opacity-50">
    {running ? '...' : 'Place'}
  </button>
  <button onclick={loadOrders} disabled={loading} class="btn-secondary text-[0.65rem] py-1 px-3 disabled:opacity-50">
    Refresh
  </button>
</div>
{#if cmdOutput}
  <div class="mb-3 p-2 rounded text-xs font-mono {cmdOutput.startsWith('✓') ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}">{cmdOutput}</div>
{/if}

<!-- Status Dashboard -->
<div class="grid grid-cols-5 gap-2 mb-3">
  <button onclick={() => filterStatus = 'all'}
    class="rounded-lg border-2 bg-white border-gray-300 p-2 text-center {filterStatus === 'all' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-sm font-bold text-primary">{orders.length}</div>
    <div class="text-[0.55rem] text-muted uppercase">All</div>
  </button>
  <button onclick={() => filterStatus = 'open'}
    class="rounded-lg border-2 bg-amber-50 border-amber-400 p-2 text-center {filterStatus === 'open' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-sm font-bold {orders.filter(o => o.status === 'OPEN' || o.status === 'TRIGGER PENDING').length > 0 ? 'text-amber-600' : 'text-muted'}">{orders.filter(o => o.status === 'OPEN' || o.status === 'TRIGGER PENDING').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Open</div>
  </button>
  <button onclick={() => filterStatus = 'complete'}
    class="rounded-lg border-2 bg-green-50 border-green-500 p-2 text-center {filterStatus === 'complete' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-sm font-bold {orders.filter(o => o.status === 'COMPLETE').length > 0 ? 'text-green-600' : 'text-muted'}">{orders.filter(o => o.status === 'COMPLETE').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Filled</div>
  </button>
  <button onclick={() => filterStatus = 'rejected'}
    class="rounded-lg border-2 bg-red-50 border-red-400 p-2 text-center {filterStatus === 'rejected' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-sm font-bold {orders.filter(o => o.status === 'REJECTED').length > 0 ? 'text-red-600' : 'text-muted'}">{orders.filter(o => o.status === 'REJECTED').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Rejected</div>
  </button>
  <button onclick={() => filterStatus = 'cancelled'}
    class="rounded-lg border-2 bg-gray-50 border-gray-400 p-2 text-center {filterStatus === 'cancelled' ? 'ring-2 ring-primary/30' : ''}">
    <div class="text-sm font-bold {orders.filter(o => o.status === 'CANCELLED').length > 0 ? 'text-gray-600' : 'text-muted'}">{orders.filter(o => o.status === 'CANCELLED').length}</div>
    <div class="text-[0.55rem] text-muted uppercase">Cancelled</div>
  </button>
</div>

<!-- Order Cards Grid -->
{#if loading && !orders.length}
  <div class="text-center text-muted text-xs animate-pulse py-8">Loading orders…</div>
{:else if !orders.length}
  <div class="text-center text-muted text-xs py-4">No orders today.</div>
{:else}
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-4">
    {#each orders.filter(o => filterStatus === 'all' ? true : filterStatus === 'open' ? (o.status === 'OPEN' || o.status === 'TRIGGER PENDING') : o.status === filterStatus.toUpperCase()) as o}
      <div class="rounded-lg border-2 {statusColor(o.status)} p-2.5">
        <div class="flex items-center justify-between mb-1">
          <span class="font-semibold text-xs {txnColor(o.transaction_type)}">{o.transaction_type} {o.quantity}</span>
          <span class="text-[0.55rem] px-1.5 py-0.5 rounded font-medium uppercase
            {o.status === 'COMPLETE' ? 'bg-green-100 text-green-700' :
             o.status === 'REJECTED' ? 'bg-red-100 text-red-700' :
             'bg-amber-100 text-amber-700'}">{o.status}</span>
        </div>
        <div class="text-xs font-medium text-primary mb-0.5">{o.tradingsymbol}</div>
        <div class="grid grid-cols-2 gap-x-2 text-[0.55rem] text-text/70">
          <div>Acct: {o.account}</div>
          <div>Exch: {o.exchange}</div>
          <div>Type: {o.order_type}</div>
          <div>Price: {o.average_price || o.price || '—'}</div>
          <div>Filled: {o.filled_quantity}/{o.quantity}</div>
          <div>Product: {o.product}</div>
        </div>
        {#if o.status === 'OPEN' || o.status === 'TRIGGER PENDING'}
          <button onclick={() => doCancel(o.order_id, o.account)}
            class="mt-1.5 text-[0.55rem] text-red-600 hover:underline">Cancel</button>
        {/if}
        {#if o.status_message}
          <div class="text-[0.5rem] text-red-500 mt-1">{o.status_message}</div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<!-- Log Tabs -->
<div class="flex items-center gap-1 mb-2">
  {#each [['order','Order Log'],['agent','Agent Log'],['system','System Log']] as [id, label]}
    <button
      onclick={() => { logTab = id; loadCurrentLog(); }}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >{label}</button>
  {/each}
</div>

<pre bind:this={logEl} class="log-panel max-h-[30vh]">{#if logTab === 'order'}{#if orderLog.length}{@html orderLog.map(e => {
  const t = e.timestamp?.slice(11,19) || '';
  const cls = e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : e.event_type === 'triggered' ? 'log-agent-triggered' : 'log-agent-default';
  return `<span class="${cls}">[${t}] ${e.event_type?.padEnd(16)||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No order events.</span>{/if}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
  const t = e.timestamp?.slice(11,19) || '';
  const cls = e.event_type === 'triggered' ? 'log-agent-triggered' : e.event_type === 'alert_sent' ? 'log-agent-alert' : e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-default';
  return `<span class="${cls}">[${t}] ${e.event_type?.padEnd(16)||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else}{#if systemLog.length}{@html systemLog.map(line => {
  const cls = line.includes('ERROR') ? 'log-error' : line.includes('WARNING') ? 'log-warning' : 'log-info';
  return `<span class="${cls}">${line}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>

<style>
  .hidden { display: none; }
</style>
