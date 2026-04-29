<script>
  import PerformancePage from '$lib/PerformancePage.svelte';

  // /performance is now the position + holdings page only. The
  // Market Summary + News-feed tabbed card that used to sit
  // beneath the grids was removed — operators wanted the page to
  // stay focused on the book. The same content lives on /market
  // (Daily Market Report) and the LogPanel News tab on the algo
  // side, so nothing is gone, just decoupled.
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

<style>
  .perf-narrow {
    margin-left:  -0.5rem;
    margin-right: -0.5rem;
  }
</style>
