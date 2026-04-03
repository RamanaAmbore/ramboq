<script>
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores';
  import { goto } from '$app/navigation';

  let command    = $state('');
  let output     = $state('');
  let logLines   = $state([]);
  let running    = $state(false);
  let loadingLog = $state(false);
  let logError   = $state('');

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function runCommand() {
    if (!command.trim()) return;
    running = true;
    output  = '';
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

  async function loadLog(n = 200) {
    loadingLog = true; logError = '';
    try {
      const res = await fetch(`/api/admin/logs?n=${n}`, { headers: authHeaders() });
      const d   = await res.json().catch(() => ({}));
      if (!res.ok) { logError = d.detail || 'Failed'; return; }
      logLines = d.lines || [];
    } catch (e) {
      logError = e.message;
    } finally { loadingLog = false; }
  }

  onMount(() => {
    if (!$authStore.token || $authStore.user?.role !== 'admin') {
      goto('/signin');
      return;
    }
    loadLog();
  });
</script>

<div class="w-full space-y-5">
  <h1 class="page-heading">Admin Console</h1>

  <!-- Command panel -->
  <div class="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
    <div class="section-heading mb-2">Command</div>
    <div class="flex gap-2">
      <input
        bind:value={command}
        class="field-input font-mono text-xs flex-1"
        placeholder="e.g.  ps aux | grep uvicorn"
        onkeydown={(e) => e.key === 'Enter' && runCommand()}
      />
      <button onclick={runCommand} disabled={running || !command.trim()} class="btn-primary disabled:opacity-50 shrink-0">
        {running ? 'Running…' : 'Run'}
      </button>
    </div>
    {#if output !== undefined && output !== ''}
      <pre class="mt-3 p-3 bg-gray-900 text-green-300 text-xs rounded font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-64">{output}</pre>
    {/if}
  </div>

  <!-- Log viewer -->
  <div class="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
    <div class="flex items-center justify-between mb-2">
      <div class="section-heading">Application Log</div>
      <div class="flex gap-2">
        {#if loadingLog}<span class="text-xs text-muted animate-pulse">Loading…</span>{/if}
        <button onclick={() => loadLog(200)}  class="btn-secondary">Refresh</button>
        <button onclick={() => loadLog(1000)} class="btn-secondary">Last 1000</button>
      </div>
    </div>
    {#if logError}
      <div class="text-xs text-red-600">{logError}</div>
    {:else}
      <pre class="p-3 bg-gray-900 text-gray-200 text-xs rounded font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-[60vh]">{logLines.join('\n') || 'No log entries.'}</pre>
    {/if}
  </div>
</div>
