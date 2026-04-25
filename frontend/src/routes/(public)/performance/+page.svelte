<svelte:head>
  <title>Performance | RamboQuant Analytics</title>
  <meta name="description" content="Real-time portfolio performance — holdings, positions, and fund balances." />
</svelte:head>

<script>
  import { onMount, onDestroy } from 'svelte';
  import PerformancePage from '$lib/PerformancePage.svelte';
  import { fetchNews } from '$lib/api';

  // Market News alongside the performance grids — same /api/news feed
  // the /market page uses, public-site palette. Auto-refreshes every 10
  // minutes (server caps the upstream feed at that cadence). Operators
  // monitoring positions get headline context without leaving the page.
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
      newsError = /** @type {any} */ (e)?.message || 'Failed to load news';
    } finally {
      newsLoading = false;
    }
  }

  function newsTime(/** @type {string} */ ts) {
    if (!ts) return '';
    if (ts.length >= 19 && ts[10] === 'T') return ts.slice(11, 16);
    const m = ts.match(/\d\d:\d\d/);
    return m ? m[0] : ts;
  }

  onMount(() => {
    loadNews();
    newsTimer = setInterval(loadNews, 10 * 60 * 1000);
  });
  onDestroy(() => { if (newsTimer) clearInterval(newsTimer); });
</script>

<!-- Negative side margins cancel half of .pub-content's 1rem side
     padding so the grids get the same 0.5rem side gutter the algo
     dashboard uses. Vertical rhythm is unchanged. -->
<div class="perf-narrow">
  <PerformancePage />
</div>

<!-- Market News — full-width card below the grids. Same shape as on
     /market: just the heading + headline rows, no metadata noise. -->
<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4 mt-4">
  <div class="flex items-center justify-between mb-3 border-b border-gray-200 pb-2">
    <h2 class="news-h">Market News</h2>
    {#if newsLoading && !news.length}
      <span class="news-meta">Loading…</span>
    {/if}
  </div>

  {#if newsError}
    <div class="p-2 rounded bg-red-50 text-red-700 text-xs mb-2 border border-red-200">{newsError}</div>
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
  .perf-narrow {
    margin-left:  -0.5rem;
    margin-right: -0.5rem;
  }

  /* Market News — same palette as /market so the card reads as a
     sibling. Both pages now share this look (headline list + champagne
     accent on the heading) without using the LogPanel chrome. */
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
