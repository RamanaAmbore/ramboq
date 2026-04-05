<script>
  import { onMount, onDestroy } from 'svelte';
  import { authStore, clientTimestamp } from '$lib/stores';
  import { goto } from '$app/navigation';

  let command      = $state('');
  let cmdHistory   = $state([]);  // [{cmd, result, time}]
  let logLines     = $state([]);
  let agentLog     = $state([]);
  let logTab       = $state('terminal');
  let running      = $state(false);
  let loadingLog   = $state(false);
  let logError     = $state('');
  let logInterval;
  let logEl;

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
    loadingLog = true; logError = '';
    try {
      const res = await fetch(`/api/admin/logs?n=${n}`, { headers: authHeaders() });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { logError = d.detail || 'Failed'; return; }
      logLines = d.lines || [];
      scrollLog();
    } catch (e) { logError = e.message; } finally { loadingLog = false; }
  }

  async function loadAgentLog() {
    loadingLog = true;
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      agentLog = await res.json().catch(() => []);
      scrollLog();
    } catch (e) { /* ignore */ } finally { loadingLog = false; }
  }

  function scrollLog() {
    requestAnimationFrame(() => { if (logEl) logEl.scrollTop = logEl.scrollHeight; });
  }

  function loadCurrentLog() {
    if (logTab === 'system') loadSystemLog();
    else if (logTab === 'agent') loadAgentLog();
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadCurrentLog();
    logInterval = setInterval(loadCurrentLog, 30000);
  });

  onDestroy(() => { if (logInterval) clearInterval(logInterval); });
</script>

<svelte:head><title>Terminal | RamboQuant Analytics</title></svelte:head>

<div class="flex flex-col h-[calc(100vh-8rem)]">
  <div class="text-[0.65rem] text-muted mb-2">{clientTimestamp()}</div>

  <!-- Command input -->
  <div class="flex gap-2 mb-1">
    <textarea
      bind:value={command}
      rows="4"
      class="field-input font-mono text-xs flex-1"
      placeholder="Shell command, order (buy/sell), or agent command"
      onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runCommand(); } }}
    ></textarea>
    <button onclick={runCommand} disabled={running || !command.trim()} class="btn-primary disabled:opacity-50 text-[0.6rem] py-1 px-3">
      {running ? '...' : 'Run'}
    </button>
  </div>
  <div class="text-[0.5rem] text-muted mb-1">
    <code>buy|sell ACCT SYMBOL QTY [LIMIT PRICE]</code> · <code>agent list|status|activate|config</code> · shell
  </div>

  <!-- Log Tabs fill remaining space -->
  <div class="flex flex-col flex-1 min-h-0">
    <div class="flex items-center justify-between mb-1 mt-2">
      <div class="flex gap-0.5">
        {#each [['terminal','Terminal'],['order','Order Log'],['agent','Agent Log'],['system','System Log']] as [id, label]}
          <button
            onclick={() => { logTab = id; if (id !== 'terminal') loadCurrentLog(); }}
            class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
              {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
          >{label}</button>
        {/each}
      </div>
      <div class="flex gap-2 items-center">
        {#if loadingLog}<span class="text-xs text-muted animate-pulse">Loading…</span>{/if}
        {#if logTab !== 'terminal'}
          <button onclick={loadCurrentLog} class="btn-secondary text-[0.6rem] py-0.5 px-2">Refresh</button>
        {/if}
      </div>
    </div>

    <!-- Log content -->
    <pre
      bind:this={logEl}
      class="log-panel flex-1 min-h-0"
    >{#if logTab === 'terminal'}{#if cmdHistory.length}{@html cmdHistory.map(h =>
      `<span class="log-info"><span class="text-green-400">$ ${h.cmd}</span></span>\n<span class="log-debug">${h.result}</span>`
    ).join('\n\n')}{:else}<span class="log-debug">Command results appear here.</span>{/if}{:else if logTab === 'order'}<span class="log-debug">Order events appear here.</span>{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
      const t = e.timestamp?.slice(11,19) || '';
      const cls = e.event_type === 'triggered' ? 'log-agent-triggered' : e.event_type === 'alert_sent' ? 'log-agent-alert' : e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-default';
      return `<span class="${cls}">[${t}] ${e.event_type||''} ${e.trigger_condition||''}</span>`;
    }).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else}{#if logLines.length}{@html logLines.map(l => {
      const cls = l.includes('ERROR') ? 'log-error' : l.includes('WARNING') ? 'log-warning' : 'log-info';
      return `<span class="${cls}">${l}</span>`;
    }).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>
  </div>
</div>
