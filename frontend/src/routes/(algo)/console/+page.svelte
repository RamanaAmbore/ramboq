<script>
  import { onMount, onDestroy } from 'svelte';
  import { authStore, clientTimestamp, visibleInterval } from '$lib/stores';
  import { goto } from '$app/navigation';
  import LogPanel from '$lib/LogPanel.svelte';

  let command      = $state('');
  let cmdHistory   = $state([]);  // [{cmd, result, time}]
  let logLines     = $state([]);
  let agentLog     = $state([]);
  let orderLog     = $state([]);
  let logTab       = $state('terminal');
  let running      = $state(false);
  let logTeardown;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  function parseOrder(cmd) {
    const parts = cmd.trim().split(/\s+/);
    if (parts.length < 4) return null;
    const txn = parts[0].toUpperCase();
    if (txn !== 'BUY' && txn !== 'SELL') return null;
    return {
      transaction_type: txn, account: parts[1], tradingsymbol: parts[2],
      quantity: parseInt(parts[3]) || 0, order_type: (parts[4] || 'MARKET').toUpperCase(),
      price: parseFloat(parts[5]) || 0, exchange: 'NFO', product: 'NRML',
      variety: 'regular', validity: 'DAY',
    };
  }

  function addResult(cmd, result) {
    const time = new Date().toLocaleTimeString('en-IN', { hour12: false });
    cmdHistory = [{ cmd, result, time }, ...cmdHistory].slice(0, 200);
  }

  async function runCommand() {
    if (!command.trim()) return;
    const cmd = command.trim();
    running = true;

    // Agent command
    if (cmd.toLowerCase().startsWith('agent ')) {
      try {
        const res = await fetch('/api/agents/interpret', {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ command: cmd }),
        });
        const d = await res.json().catch(() => ({}));
        addResult(cmd, d.output || d.detail || 'No output');
      } catch (e) { addResult(cmd, `ERROR: ${e.message}`); }
      finally { running = false; command = ''; }
      return;
    }

    // Order command
    const order = parseOrder(cmd);
    if (order) {
      try {
        const res = await fetch('/api/orders/place', {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(order),
        });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) addResult(cmd, `ORDER FAILED: ${d.detail || res.statusText}`);
        else addResult(cmd, `✓ Order placed: ${order.transaction_type} ${order.quantity} ${order.tradingsymbol} | ID: ${d.order_id}`);
      } catch (e) { addResult(cmd, `ORDER ERROR: ${e.message}`); }
      finally { running = false; command = ''; }
      return;
    }

    // Shell command
    try {
      const res = await fetch('/api/admin/exec', {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ command: cmd }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { addResult(cmd, d.detail || 'Error'); }
      else {
        let out = (d.stdout || '') + (d.stderr ? '\n[stderr]\n' + d.stderr : '');
        if (!out.trim()) out = `[exit ${d.returncode}]`;
        addResult(cmd, out);
      }
    } catch (e) { addResult(cmd, e.message); }
    finally { running = false; command = ''; }
  }

  async function loadSystemLog(n = 200) {
    try {
      const res = await fetch(`/api/admin/logs?n=${n}`, { headers: authHeaders() });
      const d = await res.json().catch(() => ({}));
      if (res.ok) logLines = d.lines || [];
    } catch (e) { /* ignore */ }
  }

  async function loadAgentLog() {
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      agentLog = await res.json().catch(() => []);
    } catch (e) { /* ignore */ }
  }

  async function loadOrderLog() {
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      orderLog = await res.json().catch(() => []);
    } catch (e) { /* ignore */ }
  }

  function loadCurrentLog() {
    if (logTab === 'system') loadSystemLog();
    else if (logTab === 'agent') loadAgentLog();
    else if (logTab === 'order') loadOrderLog();
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadCurrentLog();
    logTeardown = visibleInterval(loadCurrentLog, 30000);
  });

  onDestroy(() => { logTeardown?.(); });
</script>

<svelte:head><title>Terminal | RamboQuant Analytics</title></svelte:head>

<div class="flex flex-col h-[calc(100vh-8rem)]">
  <div class="page-header">
    <h1 class="page-title-chip">Terminal</h1>
    <span class="algo-ts">{clientTimestamp()}</span>
  </div>

  <!-- Command input -->
  <div class="relative mb-2">
    <textarea
      bind:value={command}
      class="field-input cmd-input font-mono text-xs w-full"
      style="height:8rem; padding-bottom:1.5rem"
      placeholder="Shell command, order (buy/sell), or agent command"
      onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runCommand(); } }}
    ></textarea>
    <div class="absolute bottom-3 right-2 flex gap-1 z-10">
      <!-- Run / Clear reuse the sim-btn palette (with the compact
           sim-btn-order modifier) so every algo-console action cluster
           — Orders, Simulator, Terminal — looks like one family. -->
      <button onclick={runCommand} disabled={running}
        class="sim-btn sim-btn-order sim-btn-primary disabled:opacity-40">{running ? '...' : 'Run'}</button>
      <button onclick={() => { command = ''; }}
        class="sim-btn sim-btn-order sim-btn-secondary">Clear</button>
    </div>
  </div>
  <div class="text-[0.5rem] text-muted mb-1">
    <code>buy|sell ACCT SYMBOL QTY [LIMIT PRICE]</code> · <code>agent list|status|activate|config</code> · shell
  </div>

  <!-- Log Tabs fill remaining space -->
  <div class="flex flex-col flex-1 min-h-0 mt-2">
    <LogPanel
      heightClass="flex-1 min-h-0"
      initialTab={logTab}
      {cmdHistory}
      orderLog={orderLog}
      {agentLog}
      systemLog={logLines}
      onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
    />
  </div>
</div>
