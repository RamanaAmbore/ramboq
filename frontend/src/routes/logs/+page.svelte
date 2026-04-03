<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores';

  let logLines   = $state([]);
  let loading    = $state(false);
  let error      = $state('');
  let autoRefresh = $state(true);
  let logEl;
  let interval;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function loadLog(n = 500) {
    loading = true; error = '';
    try {
      const res = await fetch(`/api/admin/logs?n=${n}`, { headers: authHeaders() });
      const d   = await res.json().catch(() => ({}));
      if (!res.ok) { error = d.detail || 'Failed'; return; }
      logLines = d.lines || [];
      requestAnimationFrame(() => {
        if (logEl) logEl.scrollTop = logEl.scrollHeight;
      });
    } catch (e) {
      error = e.message;
    } finally { loading = false; }
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadLog();
    interval = setInterval(() => { if (autoRefresh) loadLog(); }, 15000);
  });

  onDestroy(() => { if (interval) clearInterval(interval); });
</script>

<div class="flex flex-col h-[calc(100vh-8rem)]">
  <div class="flex items-center justify-between mb-2">
    <span class="section-heading">Application Log</span>
    <div class="flex gap-2 items-center">
      <label class="flex items-center gap-1 text-[0.6rem] text-muted cursor-pointer">
        <input type="checkbox" bind:checked={autoRefresh} class="w-3 h-3" /> Auto (15s)
      </label>
      {#if loading}<span class="text-xs text-muted animate-pulse">Loading…</span>{/if}
      <button onclick={() => loadLog(500)}  class="btn-secondary text-[0.6rem] py-0.5 px-2">Last 500</button>
      <button onclick={() => loadLog(2000)} class="btn-secondary text-[0.6rem] py-0.5 px-2">Last 2000</button>
    </div>
  </div>
  {#if error}
    <div class="text-xs text-red-600 mb-2">{error}</div>
  {/if}
  <pre
    bind:this={logEl}
    class="flex-1 p-3 bg-gray-900 text-gray-200 text-[0.6rem] rounded font-mono leading-relaxed overflow-auto whitespace-pre-wrap"
  >{logLines.join('\n') || 'No log entries.'}</pre>
</div>
