<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  onMount(() => goto('/about', { replaceState: true }));
</script>
