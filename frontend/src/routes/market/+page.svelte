<script>
  import { onMount, onDestroy } from 'svelte';
  import { fetchMarket } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';
  import { dataCache } from '$lib/stores';

  let content     = $state('');
  let lastRefresh = $state('');
  let loading     = $state(false);
  let error       = $state('');
  let unsub;

  function renderMarkdown(/** @type {string} */ md) {
    const lines = md.split('\n');
    let html = '';
    let inList = false;
    for (const raw of lines) {
      const line = raw
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>');
      if (/^###\s/.test(raw)) {
        if (inList) { html += '</ul>'; inList = false; }
        html += `<h3 class="md-h3">${line.replace(/^###\s/, '')}</h3>`;
      } else if (/^####\s/.test(raw)) {
        if (inList) { html += '</ul>'; inList = false; }
        html += `<h4 class="md-h4">${line.replace(/^####\s/, '')}</h4>`;
      } else if (/^[-*]\s/.test(raw)) {
        if (!inList) { html += '<ul class="md-ul">'; inList = true; }
        html += `<li class="md-li">${line.replace(/^[-*]\s/, '')}</li>`;
      } else if (/^---/.test(raw)) {
        if (inList) { html += '</ul>'; inList = false; }
        html += '<hr class="md-hr">';
      } else if (line.trim() === '') {
        if (inList) { html += '</ul>'; inList = false; }
        html += '<div class="md-gap"></div>';
      } else {
        if (inList) { html += '</ul>'; inList = false; }
        html += `<p class="md-p">${line}</p>`;
      }
    }
    if (inList) html += '</ul>';
    return html;
  }

  async function load() {
    loading = true; error = '';
    try {
      const data  = await fetchMarket();
      content     = data.content ?? '';
      lastRefresh = data.refreshed_at ?? '';
      dataCache.market = data;
    } catch (e) {
      error = e.message || 'Failed to load market update';
    } finally { loading = false; }
  }

  onMount(async () => {
    // Show cached data immediately — no empty flash on back-navigation
    if (dataCache.market) {
      content     = dataCache.market.content ?? '';
      lastRefresh = dataCache.market.refreshed_at ?? '';
    }
    await load();
    unsub = createPerformanceSocket(() => load());
  });

  onDestroy(() => unsub?.());
</script>
<svelte:head>
  <title>Market Report | RamboQuant Analytics</title>
  <meta name="description" content="AI-powered daily market report covering Indian equity, commodity, and global markets." />
</svelte:head>


<div class="flex items-center justify-between mb-3">
  <div class="text-[0.65rem] text-muted">
    {#if loading && !lastRefresh}
      <span class="animate-pulse">Loading…</span>
    {:else if lastRefresh}
      <span>{lastRefresh}</span>
    {/if}
  </div>
  <div class="flex items-center gap-2">
    {#if loading && lastRefresh}
      <span class="text-xs text-muted animate-pulse">Refreshing…</span>
    {/if}
    <button onclick={load} disabled={loading} class="btn-secondary">Refresh</button>
  </div>
</div>

<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
  {#if error}
    <div class="p-3 rounded bg-red-50 text-red-700 text-sm mb-4 border border-red-200">{error}</div>
  {/if}

  {#if !content && loading}
    <div class="text-center text-text/40 text-sm animate-pulse py-8">
      Loading market report…
    </div>
  {:else if content}
    <div class="market-report w-full">
      {@html renderMarkdown(content)}
    </div>
  {:else if !loading}
    <p class="text-text/40 text-sm">No market update available.</p>
  {/if}
</div>

<style>
  :global(.market-report .md-h3) {
    font-size: 1.05rem;
    font-weight: 700;
    color: #2f4f4f;
    margin: 1.25rem 0 0.5rem;
    padding-bottom: 0.15rem;
    border-bottom: 1px solid #2f4f4f;
  }
  :global(.market-report .md-h4) {
    font-size: 0.9rem;
    font-weight: 600;
    color: #315062;
    margin: 1rem 0 0.35rem;
  }
  :global(.market-report .md-p)  { font-size: 0.875rem; color: #315062; line-height: 1.65; margin: 0.25rem 0; }
  :global(.market-report .md-ul) { margin: 0.25rem 0 0.5rem 1.25rem; list-style: disc; }
  :global(.market-report .md-li) { font-size: 0.875rem; color: #315062; line-height: 1.6; margin: 0.15rem 0; }
  :global(.market-report .md-hr) { border: none; border-top: 1px solid #e5e7eb; margin: 0.75rem 0; }
  :global(.market-report .md-gap){ height: 0.4rem; }
  :global(.market-report strong) { font-weight: 700; color: #2f4f4f; }
  :global(.market-report em)     { font-style: italic; color: #315062; }
</style>
