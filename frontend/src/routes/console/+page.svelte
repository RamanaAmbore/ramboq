<script>
  import { onMount, onDestroy } from 'svelte';
  import { authStore } from '$lib/stores';
  import { goto } from '$app/navigation';

  let command      = $state('');
  let output       = $state('');
  let logLines     = $state([]);
  let agentLog     = $state([]);
  let logTab       = $state('system');  // system | agent
  let running      = $state(false);
  let loadingLog   = $state(false);
  let logError     = $state('');
  let logInterval;
  let logEl;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // Order shortcut: "buy ZG0790 NIFTY24APR25000CE 50 LIMIT 100"
  // Parses: buy/sell account symbol qty [order_type] [price]
  function parseOrder(cmd) {
    const parts = cmd.trim().split(/\s+/);
    if (parts.length < 4) return null;
    const txn = parts[0].toUpperCase();
    if (txn !== 'BUY' && txn !== 'SELL') return null;
    return {
      transaction_type: txn,
      account:          parts[1],
      tradingsymbol:    parts[2],
      quantity:         parseInt(parts[3]) || 0,
      order_type:       (parts[4] || 'MARKET').toUpperCase(),
      price:            parseFloat(parts[5]) || 0,
      exchange:         'NFO',
      product:          'NRML',
      variety:          'regular',
      validity:         'DAY',
    };
  }

  async function runCommand() {
    if (!command.trim()) return;
    running = true;
    output  = '';

    // Check if it's an agent command
    if (command.trim().toLowerCase().startsWith('agent ')) {
      try {
        const res = await fetch('/api/agents/interpret', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ command: command.trim() }),
        });
        const d = await res.json().catch(() => ({}));
        output = d.output || d.detail || 'No output';
      } catch (e) {
        output = `AGENT ERROR: ${e.message}`;
      } finally { running = false; }
      return;
    }

    // Check if it's an order command
    const order = parseOrder(command);
    if (order) {
      try {
        const res = await fetch('/api/orders/place', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(order),
        });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) {
          output = `ORDER FAILED: ${d.detail || res.statusText}`;
        } else {
          output = `ORDER PLACED: ${order.transaction_type} ${order.quantity} ${order.tradingsymbol} on ${order.account}\nOrder ID: ${d.order_id}`;
        }
      } catch (e) {
        output = `ORDER ERROR: ${e.message}`;
      } finally { running = false; }
      return;
    }

    // Regular shell command
    try {
      const res = await fetch('/api/admin/exec', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ command }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { output = d.detail || 'Error'; return; }
      output = (d.stdout || '') + (d.stderr ? '\n[stderr]\n' + d.stderr : '');
      if (!output.trim()) output = `[exit ${d.returncode}]`;
    } catch (e) {
      output = e.message;
    } finally { running = false; }
  }

  async function loadSystemLog(n = 200) {
    loadingLog = true; logError = '';
    try {
      const res = await fetch(`/api/admin/logs?n=${n}`, { headers: authHeaders() });
      const d   = await res.json().catch(() => ({}));
      if (!res.ok) { logError = d.detail || 'Failed'; return; }
      logLines = d.lines || [];
      scrollLog();
    } catch (e) {
      logError = e.message;
    } finally { loadingLog = false; }
  }

  async function loadAgentLog() {
    loadingLog = true;
    try {
      const res = await fetch('/api/agents/events/recent?n=100', { headers: authHeaders() });
      const d   = await res.json().catch(() => []);
      agentLog = Array.isArray(d) ? d : [];
      scrollLog();
    } catch (e) { /* ignore */ }
    finally { loadingLog = false; }
  }

  function scrollLog() {
    requestAnimationFrame(() => { if (logEl) logEl.scrollTop = logEl.scrollHeight; });
  }

  function loadCurrentLog() {
    if (logTab === 'system') loadSystemLog();
    else if (logTab === 'agent') loadAgentLog();
    // order tab shows agent events filtered — reuse agentLog
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin');
      return;
    }
    loadCurrentLog();
    logInterval = setInterval(loadCurrentLog, 30000);
  });

  onDestroy(() => {
    if (logInterval) clearInterval(logInterval);
  });
</script>

<div class="text-[0.6rem] text-muted mb-1">
  Order: <code class="bg-gray-100 px-1 rounded">buy|sell ACCOUNT SYMBOL QTY [LIMIT PRICE]</code>
</div>

<div class="flex flex-col h-[calc(100vh-8rem)]">
  <!-- Three equal panels: command, output, log -->
  <div class="grid grid-rows-3 flex-1 gap-2 min-h-0">
    <!-- Command input panel -->
    <div class="flex flex-col min-h-0">
      <div class="flex items-center justify-between mb-1">
        <span class="section-heading">Command</span>
        <button onclick={runCommand} disabled={running || !command.trim()} class="btn-primary disabled:opacity-50 text-[0.6rem] py-0.5 px-2">
          {running ? 'Running…' : 'Run'}
        </button>
      </div>
      <textarea
        bind:value={command}
        class="flex-1 p-2 bg-gray-900 text-green-400 text-[0.6rem] rounded font-mono leading-relaxed resize-none overflow-auto whitespace-pre-wrap border-none outline-none"
        placeholder="Enter command..."
        onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runCommand(); } }}
      ></textarea>
    </div>

    <!-- Output panel -->
    <div class="flex flex-col min-h-0">
      <span class="section-heading mb-1">Output</span>
      <pre class="flex-1 p-3 bg-gray-900 text-green-300 text-[0.6rem] rounded font-mono leading-relaxed overflow-auto whitespace-pre-wrap">{output || 'Run a command…'}</pre>
    </div>

    <!-- Log Tabs -->
    <div class="flex flex-col min-h-0">
      <div class="flex items-center justify-between mb-1">
        <div class="flex gap-1">
          {#each [['system','System Log'],['agent','Agent Log'],['order','Order Log']] as [id, label]}
            <button
              onclick={() => { logTab = id; loadCurrentLog(); }}
              class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
                {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
            >{label}</button>
          {/each}
        </div>
        <div class="flex gap-2 items-center">
          {#if loadingLog}<span class="text-xs text-muted animate-pulse">Loading…</span>{/if}
          <button onclick={loadCurrentLog} class="btn-secondary text-[0.6rem] py-0.5 px-2">Refresh</button>
        </div>
      </div>
      {#if logError}
        <div class="text-xs text-red-600 mb-1">{logError}</div>
      {/if}
      <pre
        bind:this={logEl}
        class="log-panel flex-1"
      >{#if logTab === 'system'}{#if logLines.length}{@html logLines.map(l => {
        const cls = l.includes('ERROR') ? 'log-error' : l.includes('WARNING') ? 'log-warning' : 'log-info';
        return `<span class="${cls}">${l}</span>`;
      }).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
        const t = e.timestamp?.slice(11,19) || '';
        const cls = e.event_type === 'triggered' ? 'log-agent-triggered' : e.event_type === 'alert_sent' ? 'log-agent-alert' : e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-default';
        return `<span class="${cls}">[${t}] ${(e.event_type||'').padEnd(16)} ${e.trigger_condition||''}</span>`;
      }).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else}<span class="log-debug">No order events.</span>{/if}</pre>
    </div>
  </div>
</div>
