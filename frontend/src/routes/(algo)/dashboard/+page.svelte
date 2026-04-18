<svelte:head>
  <title>Dashboard | RamboQuant Algo</title>
</svelte:head>

<script>
  import PerformancePage from '$lib/PerformancePage.svelte';
</script>

<h1 class="algo-page-title">Dashboard</h1>
<PerformancePage theme="ag-theme-algo" allowOrders={true} />

<style>
  .algo-page-title {
    font-size: 0.75rem;
    font-weight: 700;
    color: #d97706;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-family: ui-monospace, monospace;
    border-bottom: 1px solid rgba(217,119,6,0.25);
    padding-bottom: 0.35rem;
    margin-bottom: 1rem;
  }
</style>
