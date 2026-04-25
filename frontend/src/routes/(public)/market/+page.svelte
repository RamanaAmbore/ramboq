<script>
  import { onMount, onDestroy } from 'svelte';
  import { fetchMarket, fetchNews } from '$lib/api';
  import { createPerformanceSocket } from '$lib/ws';
  import { dataCache } from '$lib/stores';

  let content     = $state('');
  let lastRefresh = $state('');
  let loading     = $state(false);
  let error       = $state('');
  let unsub;

  // Market news — same /api/news feed the algo LogPanel consumes, but
  // styled in the public-site palette and labelled "Market News" (no
  // "log" / "feed" jargon). Refreshes every 10 minutes alongside the
  // market summary.
  /** @type {Array<{title:string, link:string, source:string, timestamp:string}>} */
  let news        = $state([]);
  let newsLoading = $state(false);
  let newsError   = $state('');
  let newsTimer;

  async function loadNews() {
    newsLoading = true;
    try {
      const r = await fetchNews();
      news = r?.items || [];
      newsError = '';
    } catch (e) {
      newsError = e?.message || 'Failed to load news';
    } finally {
      newsLoading = false;
    }
  }

  function newsTime(/** @type {string} */ ts) {
    if (!ts) return '';
    // The /api/news payload includes a presentational timestamp — pull
    // out HH:MM if it's an ISO string, else show whatever the API gave us.
    if (ts.length >= 19 && ts[10] === 'T') return ts.slice(11, 16);
    const m = ts.match(/\d\d:\d\d/);
    return m ? m[0] : ts;
  }

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
      } else if (/^\s*[-*•]\s+/.test(raw)) {
        if (!inList) { html += '<ul class="md-ul">'; inList = true; }
        html += `<li class="md-li">${line.replace(/^\s*[-*•]\s+/, '')}</li>`;
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
    // News refreshes independently — server caps the upstream feed at
    // ~10 min so polling faster wastes calls. First load is immediate;
    // subsequent reloads on a 10-min cadence keep the section live.
    loadNews();
    newsTimer = setInterval(loadNews, 10 * 60 * 1000);
  });

  onDestroy(() => {
    unsub?.();
    if (newsTimer) clearInterval(newsTimer);
  });
</script>
<svelte:head>
  <title>Market Report | RamboQuant Analytics</title>
  <meta name="description" content="AI-powered daily market report covering Indian equity, commodity, and global markets." />
</svelte:head>


<!-- Same header row shape as PerformancePage: timestamp on the left with
     the perf-ts class so every timestamp across the public site inherits
     identical sizing / colour / spacing. Right side shows a refresh
     status indicator when a silent background reload is in flight. -->
<div class="flex items-center justify-between mb-2">
  <div class="text-[0.65rem] text-muted perf-ts">
    {#if loading && !lastRefresh}
      <span class="animate-pulse">Loading…</span>
    {:else if lastRefresh}
      <span>{lastRefresh}</span>
    {/if}
  </div>
  {#if loading && lastRefresh}
    <span class="text-[0.65rem] text-muted animate-pulse">Refreshing…</span>
  {/if}
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

<!-- Market News — separate card under the AI summary. Reads from the
     same /api/news feed the algo console uses, but rendered in the
     public-site palette so it looks of-a-piece with the rest of the
     market page (cream background, navy text, champagne accent). -->
<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4 mt-4">
  <div class="flex items-center justify-between mb-3 border-b border-gray-200 pb-2">
    <h2 class="news-h">Market News</h2>
    {#if newsLoading && !news.length}
      <span class="news-meta">Loading…</span>
    {/if}
  </div>

  {#if newsError}
    <div class="p-2 rounded bg-red-50 text-red-700 text-xs mb-2 border border-red-200">
      {newsError}
    </div>
  {/if}

  {#if news.length}
    <ul class="news-list">
      {#each news as n}
        <li class="news-row">
          <span class="news-time">{newsTime(n.timestamp)}</span>
          <a class="news-title" href={n.link} target="_blank" rel="noopener">
            {n.title}
          </a>
          {#if n.source}
            <span class="news-src" title={n.source}>{n.source}</span>
          {/if}
        </li>
      {/each}
    </ul>
  {:else if !newsLoading}
    <p class="text-text/40 text-sm">No headlines available right now.</p>
  {/if}
</div>

<style>
  :global(.market-report .md-h3) {
    font-size: 1.05rem;
    font-weight: 700;
    color: #1a2744;
    margin: 1.25rem 0 0.5rem;
    border-left: 3px solid #d4920c;
    border-bottom: none;
    padding-left: 0.5rem;
  }
  :global(.market-report .md-h4) {
    font-size: 0.9rem;
    font-weight: 600;
    color: #1a2744;
    margin: 1rem 0 0.35rem;
  }
  :global(.market-report .md-p)  { font-size: 0.875rem; color: #1e3050; line-height: 1.65; margin: 0.25rem 0; }
  :global(.market-report .md-ul) { margin: 0.25rem 0 0.5rem 1.25rem; list-style: disc; }
  :global(.market-report .md-li) { font-size: 0.875rem; color: #1e3050; line-height: 1.6; margin: 0.15rem 0; }
  :global(.market-report .md-hr) { border: none; border-top: 1px solid #dde4f0; margin: 0.75rem 0; }
  :global(.market-report .md-gap){ height: 0.4rem; }
  :global(.market-report strong) { font-weight: 700; color: #1a2744; }
  :global(.market-report em)     { font-style: italic; color: #1e3050; }

  /* Market News — same palette as the rest of the public market page
     (cream + navy + champagne accent), so it reads as part of the
     report rather than the dark-theme algo log it's sourced from. */
  .news-h {
    font-size: 1rem;
    font-weight: 700;
    color: #1a2744;
    border-left: 3px solid #d4920c;
    padding-left: 0.5rem;
    line-height: 1.2;
    margin: 0;
  }
  .news-meta {
    font-size: 0.7rem;
    color: #6b7894;
    font-family: ui-monospace, monospace;
  }
  .news-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .news-row {
    display: grid;
    grid-template-columns: max-content 1fr max-content;
    align-items: baseline;
    gap: 0.6rem;
    padding: 0.45rem 0;
    border-bottom: 1px solid #f0f3f8;
    font-size: 0.85rem;
    color: #1e3050;
    line-height: 1.5;
  }
  .news-row:last-child { border-bottom: 0; }
  .news-time {
    font-family: ui-monospace, monospace;
    font-size: 0.7rem;
    color: #6b7894;
    min-width: 3rem;
  }
  .news-title {
    color: #1a2744;
    text-decoration: none;
    font-weight: 500;
  }
  .news-title:hover {
    color: #b27908;
    text-decoration: underline;
    text-decoration-thickness: 1px;
    text-underline-offset: 2px;
  }
  .news-src {
    font-size: 0.7rem;
    font-family: ui-monospace, monospace;
    color: #6b7894;
    background: #f4ead4;
    border: 1px solid #ead7a6;
    padding: 1px 6px;
    border-radius: 2px;
    white-space: nowrap;
    max-width: 14ch;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @media (max-width: 600px) {
    .news-row { grid-template-columns: max-content 1fr; }
    .news-src { display: none; }
  }
</style>
