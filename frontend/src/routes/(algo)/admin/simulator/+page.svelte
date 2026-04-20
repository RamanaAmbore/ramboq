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
    fetchSimOrders, fetchSimTicks, fetchAgents,
  } from '$lib/api';
  import LogPanel from '$lib/LogPanel.svelte';

  let scenarios = $state(/** @type {any[]} */ ([]));
  let status    = $state(/** @type {any} */ ({}));
  let events    = $state(/** @type {any[]} */ ([]));
  let orders    = $state(/** @type {any[]} */ ([]));
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
  // "order" log on this page is filtered sim agent-events — same pattern
  // LogPanel uses on /agents where orderLog is agent events (filtered
  // for order-related event types inside LogPanel itself).
  const orderLog = $derived(events);

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
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
    // agent / order tabs piggyback on `events` (refreshed by loadAll every 3s)
  }

  async function loadAll() {
    try {
      const [scList, stat, ev, od, ag] = await Promise.all([
        fetchSimScenarios(), fetchSimStatus(), fetchSimEvents(100),
        fetchSimOrders(100), fetchAgents(),
      ]);
      scenarios = scList;
      status    = stat;
      events    = ev;
      orders    = od;
      agents    = ag;
      if (!pickedSlug && scenarios.length) pickedSlug = scenarios[0].slug;
    } catch (e) { error = e.message; }
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
    refreshIv = setInterval(() => { loadAll(); loadCurrentLog(); }, 3000);
  });
  onDestroy(() => { if (refreshIv) clearInterval(refreshIv); });
</script>

<svelte:head><title>Market Simulator | RamboQuant Analytics</title></svelte:head>

<div class="algo-ts">{clientTimestamp()}</div>
<h1 class="page-title-chip mb-2">Market Simulator</h1>

<p class="text-[0.65rem] text-[#c8d8f0]/70 mb-3 max-w-3xl">
  Feeds fabricated per-symbol holdings + positions into the live agent engine
  so you can exercise alerts + actions end-to-end without touching the real
  broker. Every artefact produced here is tagged
  <span class="font-mono text-[#fb7185]">SIMULATOR</span> —
  Telegram preamble, email subject, email banner, agent-event row, paper-traded
  order. Gated by <span class="font-mono">cap_in_&lt;branch&gt;.simulator</span>
  in backend_config.yaml — dev default on, prod default off.
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
      <span>started: {status.started_at?.slice(0, 19) ?? '—'}</span>
      {#if status.only_agent_ids?.length}
        <span class="text-[#7e97b8]">|</span>
        <span class="text-[#fbbf24]">agents=[{status.only_agent_ids.join(',')}]</span>
      {/if}
    {/if}
  </div>
  {#if liveSnap}
    <div class="text-[0.6rem] text-[#c8d8f0]/70 mt-1">
      Live snapshot: {liveSnap.snapshot_at?.slice(0, 19)} ·
      {liveSnap.positions_count}P / {liveSnap.margins_count}M
      · accounts=[{liveSnap.accounts.join(', ')}]
    </div>
  {/if}
</div>

<!-- Controls -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">Controls</div>
  <div class="sim-controls-row">
    <div>
      <label for="sim-scenario" class="field-label">Scenario</label>
      <select id="sim-scenario" bind:value={pickedSlug} class="field-input">
        {#each scenarios as s}
          <option value={s.slug}>{s.name} ({s.mode}, {s.ticks} ticks)</option>
        {/each}
      </select>
    </div>
    <div>
      <label for="sim-seed" class="field-label">Seed</label>
      <select id="sim-seed" bind:value={seedMode} class="field-input">
        <option value="scripted">Scripted</option>
        <option value="live">Live book</option>
        <option value="live+scenario">Live + scenario</option>
      </select>
    </div>
    <div>
      <label for="sim-rate" class="field-label">Rate (ms)</label>
      <input id="sim-rate" type="number" min="200" step="100" bind:value={rateMs} class="field-input" />
    </div>
    <div>
      <label for="sim-pos-n" class="field-label" title="Positions refresh every N ticks (1 = every tick)">Pos / N</label>
      <input id="sim-pos-n" type="number" min="1" step="1" placeholder="1"
             bind:value={positionsEveryN} class="field-input" />
    </div>
    <div>
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
    <button type="button" onclick={doSeedLive}
      class="sim-btn sim-btn-load whitespace-nowrap">Load live book</button>
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
      class="sim-btn sim-btn-danger">Clear sim
    </button>
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

<!-- Recent SIMULATOR agent events -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">
    Recent SIMULATOR agent events <span class="opacity-60 font-normal ml-1">({events.length})</span>
  </div>
  {#if !events.length}
    <div class="text-[0.6rem] text-[#c8d8f0]/60 italic">No simulator events yet. Start a scenario or step to fire agents.</div>
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
                <span class="px-1 rounded bg-[#fb7185]/15 text-[#fb7185] border border-[#fb7185]/30 mr-1">SIM</span>
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

<!-- Recent SIMULATOR orders -->
<div class="algo-status-card p-3 mb-3" data-status="inactive">
  <div class="text-[0.55rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2">
    Recent SIMULATOR orders <span class="opacity-60 font-normal ml-1">({orders.length})</span>
  </div>
  {#if !orders.length}
    <div class="text-[0.6rem] text-[#c8d8f0]/60 italic">No simulator orders yet.</div>
  {:else}
    <div class="overflow-x-auto max-h-[30vh]">
      <table class="w-full text-[0.6rem] font-mono">
        <thead class="text-[#fbbf24] sticky top-0 bg-[#0c1220]">
          <tr class="text-left">
            <th class="py-1 pr-3">When</th>
            <th class="py-1 pr-3">Account</th>
            <th class="py-1 pr-3">Symbol</th>
            <th class="py-1 pr-3">Side</th>
            <th class="py-1 pr-3 text-right">Qty</th>
            <th class="py-1 pr-3 text-right">LIMIT ₹</th>
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
                <span class="px-1 rounded bg-[#fb7185]/15 text-[#fb7185] border border-[#fb7185]/30 mr-1">SIM</span>
                {o.symbol}
              </td>
              <td class="py-1 pr-3">{o.transaction_type}</td>
              <td class="py-1 pr-3 text-right">{o.quantity}</td>
              <td class="py-1 pr-3 text-right text-[#fbbf24]">
                {o.initial_price != null ? '₹' + Number(o.initial_price).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—'}
              </td>
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

<style>
  /* Controls row — single-line when wide, wraps when narrow. Field groups
     and buttons share the same baseline so nothing jumps by 1px. */
  .sim-controls-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.35rem 0.45rem;
    font-size: 0.62rem;
  }
  .sim-controls-row > div {
    min-width: 0;
  }
  /* First (scenario) picker takes whatever slack remains on the row. */
  .sim-controls-row > div:first-child {
    flex: 1 1 220px;
  }

  /* Compact button — smaller vertical footprint, consistent height with
     the inputs next to it. Colour-neutral base; per-variant class paints. */
  :global(.sim-btn) {
    font-size: 0.6rem;
    line-height: 1;
    padding: 0.28rem 0.6rem;
    border-radius: 3px;
    font-weight: 600;
    font-family: ui-monospace, monospace;
    border: 1px solid transparent;
    cursor: pointer;
    white-space: nowrap;
    letter-spacing: 0.02em;
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
  :global(.sim-controls-row .field-input) {
    font-size: 0.62rem;
    padding: 0.25rem 0.4rem;
    height: auto;
    min-height: 1.55rem;
  }
  :global(.sim-controls-row .field-label) {
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
  agentLog={events}
  {systemLog}
  {simLog}
  onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
/>
