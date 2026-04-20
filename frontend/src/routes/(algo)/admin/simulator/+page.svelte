<script>
  // Market Simulator control plane (/admin/simulator).
  // Pairs with backend/api/routes/simulator.py and backend/api/algo/sim/driver.py.
  // Gated by cap_in_<branch>.simulator in backend_config.yaml. Default: dev
  // on, prod off. The server returns 400 when the flag is off and this page
  // surfaces the error inline.

  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { authStore, clientTimestamp } from '$lib/stores';
  import {
    fetchSimScenarios, fetchSimStatus, startSim, stopSim, stepSim,
    runSimCycle, clearSimArtefacts, seedSimLive, fetchSimEvents,
    fetchSimTicks, fetchAgents, fetchAlgoOrdersRecent,
  } from '$lib/api';
  import LogPanel from '$lib/LogPanel.svelte';

  let scenarios = $state(/** @type {any[]} */ ([]));
  let status    = $state(/** @type {any} */ ({}));
  let events    = $state(/** @type {any[]} */ ([]));
  let agents    = $state(/** @type {any[]} */ ([]));
  let error     = $state('');
  let note      = $state('');
  let pickedSlug = $state('');
  let seedMode  = $state(/** @type {'scripted'|'live'|'live+scenario'} */ ('scripted'));
  let rateMs    = $state(2000);
  // Positions cadence override — blank means "use scenario / DB default".
  let positionsEveryN = $state(/** @type {number | ''} */ (''));
  // Simulated market state — overrides the scenario's YAML preset. Blank
  // = use whatever the scenario declares (defaulting to mid_session).
  let marketStatePreset = $state(/** @type {''|'pre_open'|'at_open'|'mid_session'|'pre_close'|'at_close'|'post_close'|'expiry_day'} */(''));
  // Pre-armed agent id (from `?agent_id=<id>` when the user clicked "Run in
  // Simulator" on the /algo page). Empty string = run all agents.
  let agentId   = $state('');
  let liveSnap  = $state(/** @type {any} */ (null));
  let refreshIv;

  // ── Log panel feeds ──────────────────────────────────────────────────
  // Mirror the feeds shown on /agents, but every list is SIMULATOR-scoped
  // on this page: the Agent tab shows sim_mode=True agent events, the
  // Order tab is derived from the same sim events, and the Simulator tab
  // streams live tick price changes from the driver's rolling buffer.
  let simLog    = $state(/** @type {any[]} */ ([]));
  let systemLog = $state(/** @type {string[]} */ ([]));
  let logTab    = $state('simulator');
  // orderLog = raw agent events (Terminal tab fallback).
  // orderRows = structured AlgoOrder rows (both sim + live) — what the
  // Order tab renders with full side / qty / symbol / price / account.
  const orderLog  = $derived(events);
  let   orderRows = $state(/** @type {any[]} */ ([]));

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function loadOrderRows() {
    try { orderRows = await fetchAlgoOrdersRecent(100, 'all') || []; }
    catch (_) { /* ignore */ }
  }

  async function loadSimLog() {
    try { simLog = await fetchSimTicks(100) || []; }
    catch (_) { /* ignore — cap flag off */ }
  }
  async function loadSystemLog() {
    try {
      const res = await fetch('/api/admin/logs?n=100', { headers: authHeaders() });
      if (res.ok) { const d = await res.json(); systemLog = d.lines || []; }
    } catch (_) { /* ignore */ }
  }
  function loadCurrentLog() {
    if (logTab === 'simulator') loadSimLog();
    else if (logTab === 'system') loadSystemLog();
    else if (logTab === 'order')  loadOrderRows();
    // agent tab piggybacks on `events` (refreshed by loadAll every 3s)
  }

  // Hot-path (every 3s): status + events. These actually change per tick.
  // Scenarios + agents are near-static — fetched once on mount and only
  // refreshed on explicit Reload (scenarios) or after an Agent ON/OFF
  // toggle from /agents (out of scope here). Cutting them from the hot
  // loop halves the request count per refresh.
  async function loadHot() {
    try {
      const [stat, ev] = await Promise.all([
        fetchSimStatus(), fetchSimEvents(100),
      ]);
      status = stat;
      events = ev;
    } catch (e) { error = e.message; }
  }

  async function loadStatic() {
    try {
      const [scList, ag] = await Promise.all([
        fetchSimScenarios(), fetchAgents(),
      ]);
      scenarios = scList;
      agents    = ag;
      if (!pickedSlug && scenarios.length) pickedSlug = scenarios[0].slug;
    } catch (e) { error = e.message; }
  }

  // Kept as a single entry point — doSeedLive / doClear / doRunCycle / doStart
  // all call loadAll() to immediately reflect the change in the UI without
  // waiting for the next poll tick.
  async function loadAll() {
    await Promise.all([loadHot(), loadStatic()]);
  }

  async function doStart() {
    error = ''; note = '';
    try {
      const opts = { seed_mode: seedMode };
      if (agentId) opts.agent_ids = [Number(agentId)];
      // Blank input = use scenario / DB default; a number = override.
      if (positionsEveryN !== '' && positionsEveryN != null) opts.positions_every_n_ticks = Number(positionsEveryN);
      if (marketStatePreset) opts.market_state_preset = marketStatePreset;
      status = await startSim(pickedSlug, rateMs, opts);
      const tag = agentId ? ` (agent #${agentId} only)` : '';
      const cadTag = ` · P:${status.positions_every_n_ticks}`;
      const msTag  = status.market_state_preset ? ` · market=${status.market_state_preset}` : '';
      note = `Started ${pickedSlug} · seed=${seedMode} · ${rateMs}ms${cadTag}${msTag}${tag}`;
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
  async function doSeedLive() {
    error = ''; note = '';
    try {
      const snap = await seedSimLive();
      liveSnap = snap;
      note = `Live book snapshot: ${snap.positions_count} positions · ${snap.margins_count} margins · accounts=[${snap.accounts.join(', ')}]`;
      if (seedMode === 'scripted') seedMode = 'live';
      loadAll();
    } catch (e) { error = e.message; }
  }
  async function doClear() {
    error = ''; note = '';
    try {
      const r = await clearSimArtefacts();
      note = `Cleared ${r.events_deleted} events + ${r.orders_deleted} simulator orders`;
      loadAll();
    } catch (e) { error = e.message; }
  }

  // Pick the display name for the armed agent (if any) so the banner is
  // meaningful instead of just a number.
  const armedAgent = $derived.by(() => {
    if (!agentId) return null;
    return agents.find(a => String(a.id) === String(agentId)) || null;
  });

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    // Read agent_id=<id> from URL — lets the /algo "Run in Simulator" button
    // pre-arm this page with a specific agent.
    const q = page.url.searchParams.get('agent_id');
    if (q) agentId = q;
    loadAll();
    loadSimLog();
    loadSystemLog();
    loadOrderRows();
    // Hot loop: status + events + algo orders + current-tab log every 3s.
    // Static data (scenarios, agents) fetched once above; not re-polled.
    refreshIv = setInterval(() => { loadHot(); loadOrderRows(); loadCurrentLog(); }, 3000);
  });
  onDestroy(() => { if (refreshIv) clearInterval(refreshIv); });
</script>

<svelte:head><title>Market Simulator | RamboQuant Analytics</title></svelte:head>

<div class="page-header">
  <h1 class="page-title-chip" title="Feeds fabricated positions into the live agent engine. Every alert, email, and paper-traded order is tagged SIMULATOR so it can't be confused with a real fire. Gated by cap_in_<branch>.simulator.">Simulator</h1>
  <span class="algo-ts">{clientTimestamp()}</span>
</div>

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

{#if armedAgent}
  <div class="mb-3 p-2 rounded bg-[#fbbf24]/15 text-[#fbbf24] text-[0.65rem] border border-[#fbbf24]/50">
    Isolated run armed — will dry-fire <b>#{armedAgent.id} {armedAgent.name}</b>
    (bypasses schedule / cooldown / baseline gates).
    <button type="button" onclick={() => { agentId = ''; }}
      class="ml-2 text-[0.6rem] underline">Clear</button>
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
      <span>seed: {status.seed_mode}</span>
      <span class="text-[#7e97b8]">|</span>
      <span>tick {status.tick_index}/{status.total_ticks}</span>
      <span class="text-[#7e97b8]">|</span>
      <span>rate: {status.rate_ms}ms</span>
      <span class="text-[#7e97b8]">|</span>
      <span title="Positions refresh every N ticks">
        cadence P:{status.positions_every_n_ticks}
      </span>
      <span class="text-[#7e97b8]">|</span>
      <span title="Simulated market state — segment flags + minutes-since-open drive time-aware agents">
        market: <span class="text-[#fde68a]">{status.market_state_preset ?? 'mid_session'}</span>
      </span>
      <span class="text-[#7e97b8]">|</span>
      <span>started: {status.started_at?.slice(11, 19) ?? '—'}</span>
      {#if status.only_agent_ids?.length}
        <span class="text-[#7e97b8]">|</span>
        <span class="text-[#fbbf24]">agents=[{status.only_agent_ids.join(',')}]</span>
      {/if}
    {/if}
  </div>
  {#if liveSnap}
    <div class="text-[0.6rem] text-[#c8d8f0]/70 mt-1">
      Live snapshot: {liveSnap.snapshot_at?.slice(11, 19)} ·
      {liveSnap.positions_count}P / {liveSnap.margins_count}M
      · accounts=[{liveSnap.accounts.join(', ')}]
    </div>
  {/if}
</div>

<!-- Controls card — no header label (the fields + buttons speak for themselves) -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <!-- Fields row — Scenario picker takes remaining width (so the dropdown
       can show long scenario names); other fields have fixed widths so
       nothing wobbles. Wraps cleanly on narrow / mobile widths. -->
  <div class="sim-fields-row">
    <div class="sim-field sim-field-scenario">
      <label for="sim-scenario" class="field-label">Scenario</label>
      <select id="sim-scenario" bind:value={pickedSlug} class="field-input">
        {#each scenarios as s}
          <option value={s.slug}>{s.name} ({s.mode}, {s.ticks} ticks)</option>
        {/each}
      </select>
    </div>
    <div class="sim-field sim-field-short">
      <label for="sim-seed" class="field-label">Seed</label>
      <select id="sim-seed" bind:value={seedMode} class="field-input">
        <option value="scripted">Scripted</option>
        <option value="live">Live book</option>
        <option value="live+scenario">Live + scenario</option>
      </select>
    </div>
    <div class="sim-field sim-field-tiny">
      <label for="sim-rate" class="field-label">Rate (ms)</label>
      <input id="sim-rate" type="number" min="200" step="100" bind:value={rateMs} class="field-input" />
    </div>
    <div class="sim-field sim-field-tiny">
      <label for="sim-pos-n" class="field-label" title="Positions refresh every N ticks (1 = every tick)">Pos / N</label>
      <input id="sim-pos-n" type="number" min="1" step="1" placeholder="1"
             bind:value={positionsEveryN} class="field-input" />
    </div>
    <div class="sim-field sim-field-short">
      <label for="sim-market" class="field-label" title="Simulated market clock — overrides the scenario's YAML value">Market</label>
      <select id="sim-market" bind:value={marketStatePreset} class="field-input">
        <option value="">(scenario)</option>
        <option value="pre_open">Pre-open</option>
        <option value="at_open">At open</option>
        <option value="mid_session">Mid-session</option>
        <option value="pre_close">Pre-close</option>
        <option value="at_close">At close</option>
        <option value="post_close">Post-close</option>
        <option value="expiry_day">Expiry day</option>
      </select>
    </div>
  </div>

  <!-- Buttons row — all uniform width so the block reads as one action
       bar. Wraps on narrow widths; on mobile each row fits 2-3 buttons. -->
  <div class="sim-buttons-row">
    <button type="button" onclick={doSeedLive}
      class="sim-btn sim-btn-load">Load live book</button>
    <button type="button" onclick={doStart}
      disabled={status.active}
      class="sim-btn sim-btn-primary disabled:opacity-40">Start</button>
    <button type="button" onclick={doStop}
      disabled={!status.active}
      class="sim-btn sim-btn-secondary disabled:opacity-40">Stop</button>
    <button type="button" onclick={doStep}
      class="sim-btn sim-btn-step">Step</button>
    <button type="button" onclick={doRunCycle}
      class="sim-btn sim-btn-cycle">Run cycle</button>
    <button type="button" onclick={doClear}
      class="sim-btn sim-btn-danger">Clear sim</button>
  </div>
  {#if pickedSlug}
    {@const picked = scenarios.find(s => s.slug === pickedSlug)}
    {#if picked}
      <div class="text-[0.6rem] text-[#c8d8f0]/60 italic mt-2">{picked.description}</div>
      {#if seedMode === 'scripted' && picked.has_initial === false}
        <div class="text-[0.6rem] text-amber-300 mt-2">
          Scenario <b>{picked.slug}</b> has no scripted initial state — price
          moves would have nothing to apply to. Press <b>Load live book</b>
          and switch Seed to <b>Live</b> (or <b>Live + scenario</b>), or pick
          a scenario with scripted data.
        </div>
      {/if}
    {/if}
  {/if}
  {#if seedMode !== 'scripted' && !liveSnap}
    <div class="text-[0.6rem] text-amber-300 mt-2">
      Seed mode <b>{seedMode}</b> requires a live-book snapshot — press
      <b>Load live book</b> before Start.
    </div>
  {/if}
</div>

<!-- The old "Recent SIMULATOR agent events" and "Recent SIMULATOR orders"
     tables used to live here. Both were duplicating data that the
     LogPanel below now surfaces cleanly:
       - Agent tab:   sim_mode=True agent events (with SIM badge)
       - Order tab:   AlgoOrder rows with side/qty/symbol/price + SIM/LIVE mode tag
     Keeping them both would just eat ~60vh of screen and force the
     operator to scan two places. Removed. -->

<style>
  /* Controls = two stacked rows. Fields first (wrap freely, Scenario
     expands to fill slack), then Buttons (uniform width, evenly spaced).
     Same layout on mobile; only difference is wrapping order. */
  .sim-fields-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.35rem 0.45rem;
    font-size: 0.62rem;
    margin-bottom: 0.5rem;
  }
  .sim-field { min-width: 0; }
  .sim-field-scenario { flex: 1 1 240px; }     /* takes slack on wide screens */
  .sim-field-short    { flex: 0 1 140px; }
  .sim-field-tiny     { flex: 0 1 100px; }

  .sim-buttons-row {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 0.35rem;
  }

  /* Compact button — uniform width so all six buttons read as one row.
     flex:1 1 110px lets them grow equally to fill the buttons row on wide
     screens and collapse to a readable minimum on mobile. */
  :global(.sim-btn) {
    flex: 1 1 110px;
    max-width: 160px;
    font-size: 0.6rem;
    line-height: 1;
    padding: 0.35rem 0.5rem;
    border-radius: 3px;
    font-weight: 600;
    font-family: ui-monospace, monospace;
    border: 1px solid transparent;
    cursor: pointer;
    white-space: nowrap;
    letter-spacing: 0.02em;
    text-align: center;
    transition: background-color 0.08s, border-color 0.08s, color 0.08s;
  }
  :global(.sim-btn:disabled) { cursor: not-allowed; }

  :global(.sim-btn-primary) {
    background: #d97706; color: #0a1020; border-color: #d97706;
  }
  :global(.sim-btn-primary:hover:not(:disabled)) { background: #fbbf24; border-color: #fbbf24; }
  :global(.sim-btn-secondary) {
    background: transparent; color: #c8d8f0; border-color: rgba(255,255,255,0.2);
  }
  :global(.sim-btn-secondary:hover:not(:disabled)) {
    background: rgba(251,191,36,0.1); border-color: rgba(251,191,36,0.5); color: #fbbf24;
  }
  :global(.sim-btn-load) {
    background: rgba(16,185,129,0.15); color: #6ee7b7; border-color: rgba(16,185,129,0.5);
  }
  :global(.sim-btn-load:hover) {
    background: rgba(16,185,129,0.25); border-color: #10b981;
  }
  :global(.sim-btn-step) {
    background: rgba(125,211,252,0.15); color: #7dd3fc; border-color: rgba(125,211,252,0.5);
  }
  :global(.sim-btn-step:hover) {
    background: rgba(125,211,252,0.25); border-color: #7dd3fc;
  }
  :global(.sim-btn-cycle) {
    background: rgba(251,191,36,0.15); color: #fbbf24; border-color: rgba(251,191,36,0.5);
  }
  :global(.sim-btn-cycle:hover) {
    background: rgba(251,191,36,0.25); border-color: #fbbf24;
  }
  :global(.sim-btn-danger) {
    background: rgba(239,68,68,0.1); color: #fca5a5; border-color: rgba(239,68,68,0.5);
  }
  :global(.sim-btn-danger:hover) {
    background: rgba(239,68,68,0.2); border-color: #ef4444;
  }

  /* Tighten the inputs to match button height so the row doesn't wobble. */
  :global(.sim-fields-row .field-input) {
    font-size: 0.62rem;
    padding: 0.25rem 0.4rem;
    height: auto;
    min-height: 1.55rem;
    width: 100%;
  }
  :global(.sim-fields-row .field-label) {
    font-size: 0.5rem;
    margin-bottom: 0.1rem;
  }
</style>

<!-- Shared log panel — same widget as /agents, defaulted to the Simulator
     tab so the first thing an operator sees on this page is the live tick
     price stream. Every tab's feed is SIMULATOR-scoped: agent = sim events,
     order = sim events filtered client-side, simulator = tick diffs,
     system = API log tail. -->
<LogPanel
  heightClass="h-[40vh]"
  initialTab={logTab}
  cmdHistory={[]}
  {orderLog}
  {orderRows}
  agentLog={events}
  {systemLog}
  {simLog}
  onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
/>
