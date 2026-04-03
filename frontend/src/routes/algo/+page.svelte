<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores';

  let status     = $state({ status: 'idle', pending_count: 0, closed_count: 0, failed_count: 0, total_slippage: 0, last_scan: '' });
  let positions  = $state([]);
  let orders     = $state([]);
  let events     = $state([]);
  let loading    = $state(false);
  let error      = $state('');
  let ws;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function fetchStatus() {
    try {
      const res = await fetch('/api/algo/status', { headers: authHeaders() });
      if (res.ok) status = await res.json();
    } catch (e) { /* ignore */ }
  }

  async function fetchPositions() {
    try {
      const res = await fetch('/api/algo/positions', { headers: authHeaders() });
      if (res.ok) positions = await res.json();
    } catch (e) { /* ignore */ }
  }

  async function fetchOrders() {
    try {
      const res = await fetch('/api/algo/orders', { headers: authHeaders() });
      if (res.ok) orders = await res.json();
    } catch (e) { /* ignore */ }
  }

  async function loadAll() {
    loading = true;
    await Promise.all([fetchStatus(), fetchPositions(), fetchOrders()]);
    loading = false;
  }

  async function startEngine() {
    error = '';
    try {
      const res = await fetch('/api/algo/start', { method: 'POST', headers: authHeaders() });
      const d = await res.json();
      if (!res.ok) error = d.detail || 'Failed';
      await loadAll();
    } catch (e) { error = e.message; }
  }

  async function stopEngine() {
    error = '';
    try {
      const res = await fetch('/api/algo/stop', { method: 'POST', headers: authHeaders() });
      const d = await res.json();
      if (!res.ok) error = d.detail || 'Failed';
      await loadAll();
    } catch (e) { error = e.message; }
  }

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/algo`);
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        events = [{ time: new Date().toLocaleTimeString(), ...evt }, ...events].slice(0, 200);
        // Refresh data on key events
        if (['order_filled', 'chase_failed', 'scan_complete', 'close_complete', 'engine_started', 'engine_stopped'].includes(evt.event)) {
          loadAll();
        }
      } catch { /* ignore */ }
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
  }

  let refreshInterval;

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadAll();
    connectWS();
    refreshInterval = setInterval(loadAll, 30000);
  });

  onDestroy(() => {
    if (ws) ws.close();
    if (refreshInterval) clearInterval(refreshInterval);
  });

  const statusColor = (s) => ({
    idle: 'text-muted', scanning: 'text-amber-600', closing: 'text-orange-600',
    done: 'text-green-600',
  }[s] || 'text-muted');

  const pnlColor = (v) => v < 0 ? 'text-red-600' : v > 0 ? 'text-green-600' : 'text-muted';
</script>

<!-- Status bar -->
<div class="flex items-center justify-between mb-3">
  <div class="flex items-center gap-3">
    <span class="text-xs font-semibold {statusColor(status.status)} uppercase">{status.status}</span>
    {#if status.last_scan}
      <span class="text-xs text-muted">Last scan: {status.last_scan}</span>
    {/if}
  </div>
  <div class="flex gap-2">
    <button onclick={loadAll} class="btn-secondary text-[0.65rem] py-0.5 px-2" disabled={loading}>Refresh</button>
    {#if status.status === 'idle' || status.status === 'done'}
      <button onclick={startEngine} class="btn-primary text-[0.65rem] py-0.5 px-2">Start Expiry Close</button>
    {:else}
      <button onclick={stopEngine} class="btn-secondary text-[0.65rem] py-0.5 px-2 text-red-600 border-red-300">Stop</button>
    {/if}
  </div>
</div>

{#if error}
  <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
{/if}

<!-- Stats -->
<div class="grid grid-cols-4 gap-3 mb-4">
  <div class="bg-white rounded-lg border border-gray-200 p-3 text-center">
    <div class="text-sm font-bold text-primary">{status.pending_count}</div>
    <div class="text-[0.6rem] text-muted uppercase">Pending</div>
  </div>
  <div class="bg-white rounded-lg border border-gray-200 p-3 text-center">
    <div class="text-sm font-bold text-green-600">{status.closed_count}</div>
    <div class="text-[0.6rem] text-muted uppercase">Closed</div>
  </div>
  <div class="bg-white rounded-lg border border-gray-200 p-3 text-center">
    <div class="text-sm font-bold text-red-600">{status.failed_count}</div>
    <div class="text-[0.6rem] text-muted uppercase">Failed</div>
  </div>
  <div class="bg-white rounded-lg border border-gray-200 p-3 text-center">
    <div class="text-sm font-bold {pnlColor(-status.total_slippage)}">₹{status.total_slippage.toLocaleString('en-IN', {maximumFractionDigits: 0})}</div>
    <div class="text-[0.6rem] text-muted uppercase">Slippage</div>
  </div>
</div>

<!-- Positions to close -->
{#if positions.length}
  <div class="mb-4">
    <h2 class="section-heading mb-2">Positions to Close</h2>
    <div class="bg-white rounded-lg border border-gray-200 overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-muted uppercase text-[0.6rem]">
          <tr>
            <th class="px-3 py-2 text-left">Account</th>
            <th class="px-3 py-2 text-left">Symbol</th>
            <th class="px-3 py-2 text-left">Exch</th>
            <th class="px-3 py-2 text-right">Strike</th>
            <th class="px-3 py-2 text-right">Underlying</th>
            <th class="px-3 py-2 text-right">Qty</th>
            <th class="px-3 py-2 text-left">Status</th>
            <th class="px-3 py-2 text-left">Reason</th>
          </tr>
        </thead>
        <tbody>
          {#each positions.filter(p => p.needs_close) as p}
            <tr class="border-t border-gray-100">
              <td class="px-3 py-1.5">{p.account}</td>
              <td class="px-3 py-1.5 font-medium">{p.symbol}</td>
              <td class="px-3 py-1.5">{p.exchange}</td>
              <td class="px-3 py-1.5 text-right">{p.strike}</td>
              <td class="px-3 py-1.5 text-right">{p.underlying_ltp.toLocaleString('en-IN', {maximumFractionDigits: 2})}</td>
              <td class="px-3 py-1.5 text-right {pnlColor(p.quantity)}">{p.quantity}</td>
              <td class="px-3 py-1.5"><span class="px-1.5 py-0.5 rounded text-[0.55rem] font-semibold uppercase
                {p.moneyness === 'ITM' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}">{p.moneyness}</span></td>
              <td class="px-3 py-1.5 text-muted">{p.close_reason}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}

<!-- Chase orders -->
{#if orders.length}
  <div class="mb-4">
    <h2 class="section-heading mb-2">Chase Orders</h2>
    <div class="bg-white rounded-lg border border-gray-200 overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-gray-50 text-muted uppercase text-[0.6rem]">
          <tr>
            <th class="px-3 py-2 text-left">Account</th>
            <th class="px-3 py-2 text-left">Symbol</th>
            <th class="px-3 py-2 text-left">Side</th>
            <th class="px-3 py-2 text-right">Qty</th>
            <th class="px-3 py-2 text-right">Init Price</th>
            <th class="px-3 py-2 text-right">Fill Price</th>
            <th class="px-3 py-2 text-right">Attempts</th>
            <th class="px-3 py-2 text-right">Slippage</th>
            <th class="px-3 py-2 text-left">Status</th>
            <th class="px-3 py-2 text-left">Engine</th>
          </tr>
        </thead>
        <tbody>
          {#each orders as o}
            <tr class="border-t border-gray-100">
              <td class="px-3 py-1.5">{o.account}</td>
              <td class="px-3 py-1.5 font-medium">{o.symbol}</td>
              <td class="px-3 py-1.5 {o.transaction_type === 'BUY' ? 'text-green-600' : 'text-red-600'}">{o.transaction_type}</td>
              <td class="px-3 py-1.5 text-right">{o.quantity}</td>
              <td class="px-3 py-1.5 text-right">{o.initial_price?.toFixed(2) ?? '—'}</td>
              <td class="px-3 py-1.5 text-right">{o.fill_price?.toFixed(2) ?? '—'}</td>
              <td class="px-3 py-1.5 text-right">{o.attempts}</td>
              <td class="px-3 py-1.5 text-right {pnlColor(-(o.slippage || 0))}">₹{(o.slippage || 0).toFixed(0)}</td>
              <td class="px-3 py-1.5"><span class="px-1.5 py-0.5 rounded text-[0.55rem] font-semibold uppercase
                {o.status === 'filled' ? 'bg-green-100 text-green-700' : o.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}">{o.status}</span></td>
              <td class="px-3 py-1.5 text-muted">{o.engine}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}

<!-- Live event log -->
<div>
  <h2 class="section-heading mb-2">Event Log</h2>
  <pre class="p-3 bg-gray-900 text-gray-200 text-[0.6rem] rounded font-mono leading-relaxed overflow-auto whitespace-pre-wrap max-h-[30vh]">{#if events.length}{events.map(e => `[${e.time}] ${e.event} ${JSON.stringify(e, null, 0).slice(0, 200)}`).join('\n')}{:else}Waiting for events…{/if}</pre>
</div>
