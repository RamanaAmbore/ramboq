<script>
  // Market simulation control plane (/admin/test).
  // Pairs with backend/api/routes/test.py and backend/api/algo/sim/driver.py.
  // Only works on non-main branches where cap_in_dev.sim_mode is True; the
  // server returns 400 otherwise and this page surfaces the error inline.

  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp } from '$lib/stores';
  import {
    fetchSimScenarios, fetchSimStatus, startSim, stopSim, stepSim,
    runSimCycle, clearSimArtefacts, fetchSimEvents, fetchSimOrders,
  } from '$lib/api';

  let scenarios = $state(/** @type {any[]} */ ([]));
  let status    = $state(/** @type {any} */ ({}));
  let events    = $state(/** @type {any[]} */ ([]));
  let orders    = $state(/** @type {any[]} */ ([]));
  let error     = $state('');
  let note      = $state('');
  let pickedSlug = $state('');
  let rateMs    = $state(2000);
  let refreshIv;

  async function loadAll() {
    try {
      const [scList, stat, ev, od] = await Promise.all([
        fetchSimScenarios(), fetchSimStatus(), fetchSimEvents(100), fetchSimOrders(100),
      ]);
      scenarios = scList;
      status    = stat;
      events    = ev;
      orders    = od;
      if (!pickedSlug && scenarios.length) pickedSlug = scenarios[0].slug;
    } catch (e) { error = e.message; }
  }

  async function doStart() {
    error = ''; note = '';
    try {
      status = await startSim(pickedSlug, rateMs);
      note = `Started scenario ${pickedSlug} @ ${rateMs}ms`;
    } catch (e) { error = e.message; }
  }
  async function doStop() {
    error = ''; note = '';
    try { status = await stopSim(); note = 'Stopped.'; }
    catch (e) { error = e.message; }
  }
  async function doStep() {
    error = ''; note = '';
    try { status = await stepSim(); note = `Applied tick ${status.tick_index}`; }
    catch (e) { error = e.message; }
  }
  async function doRunCycle() {
    error = ''; note = '';
    try { await runSimCycle(); note = 'Agent engine run on current sim state.'; loadAll(); }
    catch (e) { error = e.message; }
  }
  async function doClear() {
    error = ''; note = '';
    try {
      const r = await clearSimArtefacts();
      note = `Cleared ${r.events_deleted} events + ${r.orders_deleted} test orders`;
      loadAll();
    } catch (e) { error = e.message; }
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadAll();
    refreshIv = setInterval(loadAll, 3000);
  });
  onDestroy(() => { if (refreshIv) clearInterval(refreshIv); });
</script>

<svelte:head><title>Market Simulator | RamboQuant Analytics</title></svelte:head>

<div class="algo-ts">{clientTimestamp()}</div>
<h1 class="page-title-chip mb-2">Market Simulator</h1>

<p class="text-[0.65rem] text-[#c8d8f0]/70 mb-3 max-w-3xl">
  Feeds fabricated holdings / positions / margins into the live agent engine
  so you can exercise alerts + actions end-to-end without touching the real
  broker. Every artefact produced here is tagged <span class="font-mono text-[#fb7185]">TEST</span> —
  Telegram preamble, email subject, email banner, agent-event row, paper-traded
  order. Prod is hard-blocked; dev also requires
  <span class="font-mono">cap_in_dev.sim_mode: True</span>.
</p>

{#if error}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">
    {error}
  </div>
{/if}
{#if note}
  <div class="mb-3 p-2 rounded bg-emerald-500/10 text-emerald-300 text-[0.65rem] border border-emerald-500/30">
    {note}
  </div>
{/if}

<!-- Status bar -->
<div class="algo-status-card p-3 mb-3" data-status={status.active ? 'triggered' : 'inactive'}>
  <div class="flex items-center flex-wrap gap-2 text-[0.7rem]">
    <span class="w-2 h-2 rounded-full {status.active ? 'bg-red-500 animate-pulse' : 'bg-slate-500'}"></span>
    <span class="text-[#fbbf24] font-semibold">{status.active ? 'RUNNING' : 'idle'}</span>
    {#if status.scenario}
      <span class="font-mono text-[#7dd3fc]">scenario: {status.scenario}</span>
      <span class="text-[#7e97b8]">|</span>
      <span>tick {status.tick_index}/{status.total_ticks}</span>
      <span class="text-[#7e97b8]">|</span>
      <span>rate: {status.rate_ms}ms</span>
      <span class="text-[#7e97b8]">|</span>
      <span>started: {status.started_at?.slice(0, 19) ?? '—'}</span>
    {/if}
  </div>
</div>

<!-- Controls -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">Controls</div>
  <div class="grid grid-cols-1 md:grid-cols-[1fr_120px_auto_auto_auto_auto_auto] gap-2 items-end text-[0.65rem]">
    <div>
      <label for="sim-scenario" class="field-label">Scenario</label>
      <select id="sim-scenario" bind:value={pickedSlug} class="field-input">
        {#each scenarios as s}
          <option value={s.slug}>{s.name} ({s.ticks} ticks)</option>
        {/each}
      </select>
    </div>
    <div>
      <label for="sim-rate" class="field-label">Rate (ms)</label>
      <input id="sim-rate" type="number" min="200" step="100" bind:value={rateMs} class="field-input" />
    </div>
    <button type="button" onclick={doStart}
      disabled={status.active}
      class="btn-primary text-[0.65rem] py-1 px-3 disabled:opacity-40">Start</button>
    <button type="button" onclick={doStop}
      disabled={!status.active}
      class="btn-secondary text-[0.65rem] py-1 px-3 disabled:opacity-40">Stop</button>
    <button type="button" onclick={doStep}
      class="text-[0.65rem] py-1 px-3 rounded border border-[#7dd3fc]/50 bg-[#7dd3fc]/15 text-[#7dd3fc] hover:bg-[#7dd3fc]/25 font-semibold">
      Step
    </button>
    <button type="button" onclick={doRunCycle}
      class="text-[0.65rem] py-1 px-3 rounded border border-[#fbbf24]/50 bg-[#fbbf24]/15 text-[#fbbf24] hover:bg-[#fbbf24]/25 font-semibold">
      Run cycle
    </button>
    <button type="button" onclick={doClear}
      class="text-[0.65rem] py-1 px-3 rounded border border-red-500/50 bg-red-500/10 text-red-300 hover:bg-red-500/20 font-semibold">
      Clear TEST
    </button>
  </div>
  {#if pickedSlug}
    {@const picked = scenarios.find(s => s.slug === pickedSlug)}
    {#if picked}
      <div class="text-[0.6rem] text-[#c8d8f0]/60 italic mt-2">{picked.description}</div>
    {/if}
  {/if}
</div>

<!-- Recent TEST agent events -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">
    Recent TEST agent events <span class="opacity-60 font-normal ml-1">({events.length})</span>
  </div>
  {#if !events.length}
    <div class="text-[0.6rem] text-[#c8d8f0]/60 italic">No test events yet. Start a scenario or step to fire agents.</div>
  {:else}
    <div class="overflow-x-auto max-h-[30vh]">
      <table class="w-full text-[0.6rem] font-mono">
        <thead class="text-[#fbbf24] sticky top-0 bg-[#0c1220]">
          <tr class="text-left">
            <th class="py-1 pr-3">When</th>
            <th class="py-1 pr-3">Agent</th>
            <th class="py-1 pr-3">Type</th>
            <th class="py-1 pr-3">Condition / detail</th>
          </tr>
        </thead>
        <tbody>
          {#each events as e}
            <tr class="border-t border-white/5 align-top">
              <td class="py-1 pr-3 whitespace-nowrap">{e.timestamp?.slice(0, 19)}</td>
              <td class="py-1 pr-3">#{e.agent_id}</td>
              <td class="py-1 pr-3">
                <span class="px-1 rounded bg-[#fb7185]/15 text-[#fb7185] border border-[#fb7185]/30 mr-1">TEST</span>
                {e.event_type}
              </td>
              <td class="py-1 pr-3 text-[#c8d8f0]/85">{e.trigger_condition || e.detail || '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<!-- Recent TEST orders -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">
    Recent TEST orders <span class="opacity-60 font-normal ml-1">({orders.length})</span>
  </div>
  {#if !orders.length}
    <div class="text-[0.6rem] text-[#c8d8f0]/60 italic">No test orders yet.</div>
  {:else}
    <div class="overflow-x-auto max-h-[30vh]">
      <table class="w-full text-[0.6rem] font-mono">
        <thead class="text-[#fbbf24] sticky top-0 bg-[#0c1220]">
          <tr class="text-left">
            <th class="py-1 pr-3">When</th>
            <th class="py-1 pr-3">Account</th>
            <th class="py-1 pr-3">Symbol</th>
            <th class="py-1 pr-3">Side</th>
            <th class="py-1 pr-3">Qty</th>
            <th class="py-1 pr-3">Engine</th>
            <th class="py-1 pr-3">Status</th>
            <th class="py-1 pr-3">Detail</th>
          </tr>
        </thead>
        <tbody>
          {#each orders as o}
            <tr class="border-t border-white/5 align-top">
              <td class="py-1 pr-3 whitespace-nowrap">{o.created_at?.slice(0, 19)}</td>
              <td class="py-1 pr-3">{o.account}</td>
              <td class="py-1 pr-3">
                <span class="px-1 rounded bg-[#fb7185]/15 text-[#fb7185] border border-[#fb7185]/30 mr-1">TEST</span>
                {o.symbol}
              </td>
              <td class="py-1 pr-3">{o.transaction_type}</td>
              <td class="py-1 pr-3">{o.quantity}</td>
              <td class="py-1 pr-3">{o.engine}</td>
              <td class="py-1 pr-3">{o.status}</td>
              <td class="py-1 pr-3 text-[#c8d8f0]/85">{o.detail || '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
