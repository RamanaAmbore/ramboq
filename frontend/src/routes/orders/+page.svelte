<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, logTime, parseLogLineTime } from '$lib/stores';
  import { fetchOrders, fetchAccounts, placeOrder, cancelOrder } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';

  let orders        = $state([]);
  let loading       = $state(true);
  let error         = $state('');
  let success       = $state('');
  let filterStatus  = $state('all');
  let command       = $state('');
  let cmdOutput     = $state('');
  let running       = $state(false);
  let logTab        = $state('order');
  let orderLog      = $state([]);
  let agentLog      = $state([]);
  let systemLog     = $state([]);
  let cmdHistory    = $state([]);
  let unsub;
  let logInterval;

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

  async function doCancel(/** @type {string} */ oid, /** @type {string} */ acct) {
    try { await cancelOrder(oid, acct); success = `Order ${oid} cancelled`; await loadOrders(); }
    catch (e) { error = e.message; }
  }

  function addResult(/** @type {string} */ cmd, /** @type {string} */ result) {
    const t = new Date().toLocaleTimeString('en-IN', { hour12: false });
    cmdHistory = [{ cmd, result, time: t }, ...cmdHistory].slice(0, 100);
  }

  async function runCommand() {
    if (!command.trim()) return;
    const cmd = command.trim();
    running = true;
    const parts = cmd.split(/\s+/);
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
        addResult(cmd, `✓ ${txn} ${parts[3]} ${parts[2]} | ID: ${res.order_id}`);
        await loadOrders();
      } catch (e) { addResult(cmd, `✗ ${e.message}`); }
    } else {
      addResult(cmd, 'Syntax: buy|sell ACCOUNT SYMBOL QTY [LIMIT PRICE]');
    }
    running = false; command = '';
  }

  async function loadOrderLog() {
    try {
      const res = await fetch('/api/agents/events/recent?n=50', { headers: authHeaders() });
      const data = await res.json().catch(() => []);
      const ORDER_TYPES = new Set(['order_placed','order_cancelled','order_rejected','order_filled']);
      orderLog = (Array.isArray(data) ? data : []).filter(e =>
        ORDER_TYPES.has(e.event_type) ||
        (e.event_type?.startsWith('action_') && /place_order|chase_close/i.test(e.trigger_condition || '')));
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

  const statusColor = (/** @type {string} */ s) => {
    const c = s?.toUpperCase();
    if (c === 'COMPLETE') return 'border-green-500 bg-green-50';
    if (c === 'REJECTED' || c === 'CANCELLED') return 'border-red-400 bg-red-50';
    if (c === 'OPEN' || c === 'TRIGGER PENDING') return 'border-amber-400 bg-amber-50';
    return 'border-gray-300 bg-white';
  };
  const txnColor = (/** @type {string} */ t) => t === 'BUY' ? 'text-green-600' : 'text-red-600';

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadOrders(); loadCurrentLog();
    unsub = createPerformanceSocket(() => loadOrders());
    logInterval = setInterval(loadCurrentLog, 30000);
  });
  onDestroy(() => { unsub?.(); if (logInterval) clearInterval(logInterval); });
</script>

<svelte:head><title>Orders | RamboQuant Analytics</title></svelte:head>

<div class="flex flex-col h-[calc(100vh-8rem)]">
<div class="text-[0.65rem] text-muted mb-1">{clientTimestamp()}</div>
<h1 class="page-title-chip mb-2">Orders</h1>

{#if error}<div class="mb-2 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>{/if}
{#if success}<div class="mb-2 p-2 rounded bg-green-50 text-green-700 text-xs border border-green-200">{success}</div>{/if}

<!-- Order Entry -->
<div class="mb-3">
  <div class="flex gap-2 mb-1">
    <textarea bind:value={command} rows="4" class="field-input cmd-input font-mono text-xs flex-1"
      placeholder="buy ACCOUNT SYMBOL QTY [LIMIT PRICE]"
      onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runCommand(); } }}></textarea>
    <button onclick={runCommand} disabled={running} class="btn-primary text-[0.65rem] py-1 px-3 disabled:opacity-50">
      {running ? '...' : 'Place'}
    </button>
    <button onclick={loadOrders} disabled={loading} class="btn-secondary text-[0.65rem] py-1 px-3 disabled:opacity-50">Refresh</button>
  </div>
  <div class="text-[0.5rem] text-muted">buy|sell ACCOUNT SYMBOL QTY [MARKET|LIMIT] [PRICE]</div>
</div>

<!-- Status Dashboard -->
<div class="grid grid-cols-5 gap-2 mb-3">
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
  <div class="text-center text-muted text-xs animate-pulse py-4">Loading orders…</div>
{:else if orders.length}
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-3 max-h-[25vh] overflow-y-auto">
    {#each orders.filter(o => filterStatus === 'all' ? true : filterStatus === 'open' ? (o.status === 'OPEN' || o.status === 'TRIGGER PENDING') : o.status === filterStatus.toUpperCase()) as o}
      <div class="rounded-lg border-2 {statusColor(o.status)} p-2.5">
        <div class="flex items-center justify-between mb-1">
          <span class="font-semibold text-xs {txnColor(o.transaction_type)}">{o.transaction_type} {o.quantity}</span>
          <span class="text-[0.55rem] px-1.5 py-0.5 rounded font-medium uppercase
            {o.status === 'COMPLETE' ? 'bg-green-100 text-green-700' : o.status === 'REJECTED' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}">{o.status}</span>
        </div>
        <div class="text-xs font-medium text-primary mb-0.5">{o.tradingsymbol}</div>
        <div class="grid grid-cols-2 gap-x-2 text-[0.55rem] text-text/70">
          <div>Acct: {o.account}</div><div>Exch: {o.exchange}</div>
          <div>Type: {o.order_type}</div><div>Price: {o.average_price || o.price || '—'}</div>
          <div>Filled: {o.filled_quantity}/{o.quantity}</div><div>Product: {o.product}</div>
        </div>
        {#if o.status === 'OPEN' || o.status === 'TRIGGER PENDING'}
          <button onclick={() => doCancel(o.order_id, o.account)} class="mt-1 text-[0.55rem] text-red-600 hover:underline">Cancel</button>
        {/if}
      </div>
    {/each}
  </div>
{:else}
  <div class="text-center text-muted text-xs py-2 mb-3">No orders today.</div>
{/if}

<!-- Log Tabs -->
<div class="flex gap-0.5 mb-2">
  {#each [['order','Order Log'],['terminal','Terminal'],['agent','Agent Log'],['system','System Log']] as [id, label]}
    <button onclick={() => { logTab = id; loadCurrentLog(); }}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >{label}</button>
  {/each}
</div>

<pre class="log-panel flex-1 min-h-0">{#if logTab === 'terminal'}{#if cmdHistory.length}{@html cmdHistory.map(h =>
  `<span class="log-info"><span class="text-green-400">$ ${h.cmd}</span></span>\n<span class="log-debug">${h.result}</span>`
).join('\n\n')}{:else}<span class="log-debug">Place an order above…</span>{/if}{:else if logTab === 'order'}{#if orderLog.length}{@html orderLog.map(e => {
  const t = logTime(e.timestamp);
  const cls = e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-triggered';
  return `<span class="${cls}"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No order events.</span>{/if}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
  const t = logTime(e.timestamp);
  const cls = e.event_type === 'triggered' ? 'log-agent-triggered' : e.event_type === 'alert_sent' ? 'log-agent-alert' : e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-default';
  return `<span class="${cls}"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else}{#if systemLog.length}{@html systemLog.map(l => {
  const t = parseLogLineTime(l);
  const rest = t ? l.replace(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*-?\s*/, '') : l;
  const cls = l.includes('ERROR') ? 'log-error' : l.includes('WARNING') ? 'log-warning' : 'log-info';
  return `<span class="${cls}">${t ? `<span class="log-ts">[${t}]</span> ` : ''}${rest}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>
</div>
