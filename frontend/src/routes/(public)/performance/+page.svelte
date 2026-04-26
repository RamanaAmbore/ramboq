<script>
  import { onMount, onDestroy } from 'svelte';
  import PerformancePage from '$lib/PerformancePage.svelte';
  import { fetchNews, fetchMarket } from '$lib/api';

  // Tabbed Market Summary + Market News card under the performance
  // grids. Same /api/market and /api/news feeds the /market page uses,
  // public-site palette throughout. Operators monitoring positions get
  // headline context AND the AI summary without leaving the page.

  /** @type {'summary' | 'news'} */
  let tab = $state('summary');

  // ── Market Summary (AI-generated markdown) ─────────────────────
  let summaryContent = $state('');
  let summaryRefresh = $state('');
  let summaryLoading = $state(false);
  let summaryError   = $state('');

  /** Tiny markdown renderer — same shape as /market page's. Kept
   *  inline so /performance doesn't depend on the /market component. */
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

  async function loadSummary() {
    summaryLoading = true; summaryError = '';
    try {
      const data = await fetchMarket();
      summaryContent = data.content ?? '';
      summaryRefresh = data.refreshed_at ?? '';
    } catch (e) {
      summaryError = /** @type {any} */ (e)?.message || 'Failed to load market summary';
    } finally {
      summaryLoading = false;
    }
  }

  // ── Market News ─────────────────────────────────────────────────
  /** @type {Array<{title:string, link:string, source:string, timestamp:string}>} */
  let news         = $state([]);
  let newsRefresh  = $state('');
  let newsLoading  = $state(false);
  let newsError    = $state('');
  let newsTimer;

  async function loadNews() {
    newsLoading = true;
    try {
      const r = await fetchNews();
      news        = r?.items || [];
      newsRefresh = r?.refreshed_at || '';
      newsError   = '';
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

  // First-load: kick off both immediately so flipping tabs after the
  // page settles is a paint, not a fetch. News refreshes on a 10-min
  // cadence; summary doesn't auto-refresh (the /market page handles
  // server-pushed refreshes via the WebSocket — operators on
  // /performance see a static snapshot until they revisit).
  onMount(() => {
    loadSummary();
    loadNews();
    newsTimer = setInterval(loadNews, 10 * 60 * 1000);
  });
  onDestroy(() => { if (newsTimer) clearInterval(newsTimer); });
</script>

<svelte:head>
  <title>Performance | RamboQuant Analytics</title>
  <meta name="description" content="Real-time portfolio performance — holdings, positions, and fund balances." />
</svelte:head>

<!-- Negative side margins cancel half of .pub-content's 1rem side
     padding so the grids get the same 0.5rem side gutter the algo
     dashboard uses. Vertical rhythm is unchanged. -->
<div class="perf-narrow">
  <PerformancePage />
</div>

<!-- Tabs sit OUTSIDE the white card on the page background, so the
     tab strip reads like the rest of the public surface (cream
     ground + champagne accents) rather than as a sub-control of the
     card below. Selected tab carries a champagne underline; the
     white panel below holds only the content. -->
<div class="market-tabs-row">
  <div class="market-tabs">
    <button type="button"
            class="market-tab"
            class:market-tab-active={tab === 'summary'}
            onclick={() => tab = 'summary'}>
      Daily Market Report
    </button>
    <button type="button"
            class="market-tab"
            class:market-tab-active={tab === 'news'}
            onclick={() => tab = 'news'}>
      News feed
    </button>
  </div>
  <div class="market-tabs-meta">
    {#if tab === 'summary'}
      {#if summaryLoading && !summaryRefresh}
        Loading…
      {:else if summaryLoading}
        Refreshing…
      {/if}
    {:else if newsLoading && !news.length}
      Loading…
    {:else if newsLoading}
      Refreshing…
    {/if}
  </div>
</div>

<div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
  <!-- Refreshed-at line — matches PerformancePage timestamp styling
       (text-[0.65rem] text-muted perf-ts) for visual consistency
       across the public site. nowrap keeps the dual-timezone string
       on a single line. -->
  {#if tab === 'summary' && summaryRefresh}
    <div class="text-[0.65rem] text-muted perf-ts market-refresh-line">Refreshed at {summaryRefresh}</div>
  {:else if tab === 'news' && newsRefresh}
    <div class="text-[0.65rem] text-muted perf-ts market-refresh-line">Refreshed at {newsRefresh}</div>
  {/if}

  {#if tab === 'summary'}
    {#if summaryError}
      <div class="p-2 rounded bg-red-50 text-red-700 text-xs mb-2 border border-red-200">
        {summaryError}
      </div>
    {/if}
    {#if !summaryContent && summaryLoading}
      <div class="text-center text-text/40 text-sm animate-pulse py-8">
        Loading market summary…
      </div>
    {:else if summaryContent}
      <div class="market-report w-full">
        {@html renderMarkdown(summaryContent)}
      </div>
    {:else if !summaryLoading}
      <p class="text-text/40 text-sm">No market summary available right now.</p>
    {/if}
  {:else}
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
  {/if}
</div>

<style>
  .perf-narrow {
    margin-left:  -0.5rem;
    margin-right: -0.5rem;
  }

  /* Tab row — sits OUTSIDE the white panel, on the page's cream
     background. Active tab gets a champagne BOTTOM border (mirrors a
     desktop-app document-tab affordance more naturally than the
     earlier left-border indicator). The row's own bottom border
     stitches the active tab to the panel below — the active tab's
     bottom border meets the row's, the inactive tabs sit just above
     it. Margin-top gives the tabs breathing room from the
     PerformancePage grids above. */
  .market-tabs-row {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 0.6rem;
    margin-top: 1rem;
    border-bottom: 1px solid #e7e0cf;
    padding: 0 0.25rem;
    flex-wrap: wrap;
  }
  .market-tabs {
    display: flex;
    gap: 0.25rem;
  }
  .market-tab {
    font-size: 0.85rem;
    font-weight: 500;
    color: #6b7894;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 0.45rem 0.9rem;
    margin-bottom: -1px;          /* overlap row's bottom border */
    cursor: pointer;
    transition: color 0.12s, border-color 0.12s, background-color 0.12s;
  }
  .market-tab:hover {
    color: #1a2744;
    border-bottom-color: rgba(212,146,12,0.5);
  }
  .market-tab-active {
    color: #1a2744;
    font-weight: 700;
    border-bottom-color: #d4920c;
  }
  /* Bridge between the tab row and the white panel — kill the panel's
     top-left/right rounding so the active tab visually merges with
     the panel beneath it. */
  .market-tabs-row + .bg-white {
    border-top-left-radius: 0;
    border-top-right-radius: 0;
    border-top: 0;
  }
  .market-tabs-meta {
    font-size: 0.7rem;
    color: #6b7894;
    font-family: ui-monospace, monospace;
  }
  /* Refreshed-at line — base size + colour come from the Tailwind
     triplet `text-[0.65rem] text-muted perf-ts`; local rules add
     nowrap so the long dual-timezone string stays on a single line. */
  .market-refresh-line {
    margin-bottom: 0.5rem;
    margin-top: -0.15rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Market summary — match /market page's markdown styling. */
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

  /* News list — same shape as /market. */
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
