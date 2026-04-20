<svelte:head>
  <title>Dashboard | RamboQuant Algo</title>
</svelte:head>

<script>
  import PerformancePage from '$lib/PerformancePage.svelte';
  import { clientTimestamp } from '$lib/stores';
</script>

<div class="page-header">
  <h1 class="algo-page-title">Dashboard</h1>
  <span class="algo-ts">{clientTimestamp()}</span>
</div>
<PerformancePage theme="ag-theme-algo" allowOrders={true} maskAccounts={false} />

<style>
  .algo-page-title {
    font-size: 0.75rem;
    font-weight: 700;
    color: #fbbf24;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: ui-monospace, monospace;
    /* border lives on the .page-header flex wrapper now so it stretches
       full-width under both the title and the right-aligned timestamp. */
  }
  :global(.page-header:has(.algo-page-title)) {
    border-bottom: 1px solid rgba(251,191,36,0.25);
    padding-bottom: 0.35rem;
    margin-bottom: 1rem;
  }
</style>
