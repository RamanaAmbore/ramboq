<svelte:head>
  <title>Performance | RamboQuant Analytics</title>
  <meta name="description" content="Real-time portfolio performance — holdings, positions, and fund balances." />
</svelte:head>

<script>
  import PerformancePage from '$lib/PerformancePage.svelte';
</script>

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
