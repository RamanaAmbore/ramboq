<svelte:head>
  <title>Dashboard | RamboQuant Algo</title>
</svelte:head>

<script>
  import PerformancePage from '$lib/PerformancePage.svelte';
</script>

<!-- No page-header / timestamp — the refresh timestamp lives inside the
     PerformancePage tabs row now, and the algo navbar already shows
     the page title implicitly through the active nav link. -->
<PerformancePage theme="ag-theme-algo" allowOrders={true} maskAccounts={false} compactHeader={true} />
