<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp } from '$lib/stores';
  import { fetchAgents, activateAgent, deactivateAgent, updateAgent, fetchRecentAgentEvents } from '$lib/api';
  import LogPanel from '$lib/LogPanel.svelte';

  let agents      = $state([]);
  let agentEvents = $state([]);
  let loading     = $state(true);
  let error       = $state('');
  let logTab      = $state('agent');
  let systemLog   = $state([]);
  let orderLog    = $state([]);
  let editing     = $state(null);     // slug of agent being edited
  let editForm    = $state(/** @type {{ name: string, description: string, conditions: string, events: string, actions: string, cooldown_minutes: number, scope: string, schedule: string }} */ ({ name: '', description: '', conditions: '{}', events: '[]', actions: '[]', cooldown_minutes: 30, scope: 'per_account', schedule: 'market_hours' }));
  let ws;
  let refreshInterval;

  function authHeaders() {
    const token = $authStore.token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function loadAgents() {
    try {
      const data = await fetchAgents();
      agents = data;
    } catch (e) { error = e.message; }
  }

  async function loadAgentLog() {
    try {
      const data = await fetchRecentAgentEvents(100);
      agentEvents = data;
    } catch (e) { /* ignore */ }
  }

  async function loadSystemLog() {
    try {
      const res = await fetch('/api/admin/logs?n=100', { headers: authHeaders() });
      if (res.ok) { const d = await res.json(); systemLog = d.lines || []; }
    } catch (e) { /* ignore */ }
  }

  async function loadOrderLog() {
    try {
      const data = await fetchRecentAgentEvents(100);
      orderLog = data;
    } catch (e) { /* ignore */ }
  }

  function loadCurrentLog() {
    if (logTab === 'agent') loadAgentLog();
    else if (logTab === 'system') loadSystemLog();
    else if (logTab === 'order') loadOrderLog();
  }

  async function loadAll() {
    loading = true;
    await Promise.all([loadAgents(), loadAgentLog(), loadSystemLog()]);
    loading = false;
  }

  async function toggle(/** @type {any} */ agent) {
    try {
      if (agent.status === 'inactive') await activateAgent(agent.slug);
      else await deactivateAgent(agent.slug);
      await loadAgents();
    } catch (e) { error = e.message; }
  }

  function startEdit(/** @type {any} */ agent) {
    editing = agent.slug;
    editForm = {
      name: agent.name,
      description: agent.description || '',
      conditions: JSON.stringify(agent.conditions, null, 2),
      events: JSON.stringify(agent.events, null, 2),
      actions: JSON.stringify(agent.actions, null, 2),
      cooldown_minutes: agent.cooldown_minutes,
      scope: agent.scope,
      schedule: agent.schedule || 'market_hours',
    };
  }

  async function saveEdit() {
    try {
      await updateAgent(editing, {
        name: editForm.name,
        description: editForm.description,
        conditions: JSON.parse(editForm.conditions),
        events: JSON.parse(editForm.events),
        actions: JSON.parse(editForm.actions),
        cooldown_minutes: editForm.cooldown_minutes,
        scope: editForm.scope,
        schedule: editForm.schedule,
      });
      editing = null;
      await loadAgents();
    } catch (e) { error = e.message; }
  }

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/algo`);
    ws.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        if (evt.event === 'agent_state') {
          const idx = agents.findIndex(a => a.slug === evt.slug);
          if (idx >= 0) agents[idx].status = evt.status;
          agents = [...agents];
        }
        if (['agent_alert', 'agent_state'].includes(evt.event)) {
          loadAgentLog();
        }
      } catch { /* ignore */ }
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
  }

  const statusDot = (/** @type {string} */ s) => ({
    active: 'bg-green-500', inactive: 'bg-slate-500',
    triggered: 'bg-red-500', running: 'bg-amber-400',
    cooldown: 'bg-amber-300', error: 'bg-red-600',
  }[s] || 'bg-slate-500');

  const eventColor = (/** @type {string} */ t) => ({
    triggered: 'text-orange-600', alert_sent: 'text-yellow-600',
    action_success: 'text-green-600', action_failed: 'text-red-600',
    activated: 'text-gray-500', deactivated: 'text-gray-500',
    config_changed: 'text-purple-600',
  }[t] || 'text-gray-500');

  const eventIcon = (/** @type {string} */ t) => ({
    triggered: '🟠', alert_sent: '🟡', action_success: '🟢',
    action_failed: '🔴', activated: '⚪', deactivated: '⚪', config_changed: '🟣',
  }[t] || '⚪');

  function conditionSummary(/** @type {any} */ cond) {
    if (!cond) return '—';
    if (cond.operator && cond.rules) {
      return cond.rules.map(r => conditionSummary(r)).join(` ${cond.operator.toUpperCase()} `);
    }
    const f = cond.field || '?';
    const v = typeof cond.value === 'number' && Math.abs(cond.value) >= 1000
      ? `₹${cond.value.toLocaleString('en-IN')}` : String(cond.value ?? '?');
    return `${f} ${cond.op || '?'} ${v}`;
  }

  function actionSummary(/** @type {any[]} */ actions) {
    if (!actions || !actions.length) return 'Alert only';
    return actions.map(a => a.type).join(', ');
  }

  function channelSummary(/** @type {any[]} */ events) {
    if (!events) return '—';
    return events.filter(e => e.enabled).map(e => e.channel).join(', ');
  }

  // ── Category grouping ────────────────────────────────────────────────────
  // Derive category from slug prefix so new agents bucket automatically
  // without needing a DB field. If the catalog grows unwieldy, promote
  // this to an Agent column later.
  function categoryFor(slug) {
    if (!slug) return 'Other';
    if (slug.startsWith('loss-') ||
        slug === 'position_loss' || slug === 'position_loss_pct' ||
        slug.startsWith('negative_')) return 'Loss & Risk';
    if (slug.endsWith('_summary') || slug.includes('summary')) return 'Summaries';
    if (slug.includes('expiry') || slug.includes('close') || slug.includes('order')) return 'Automation';
    return 'Other';
  }

  const CATEGORY_ORDER = ['Loss & Risk', 'Summaries', 'Automation', 'Other'];

  function groupedAgents() {
    const out = {};
    for (const a of agents) {
      const cat = categoryFor(a.slug);
      (out[cat] = out[cat] || []).push(a);
    }
    for (const cat of Object.keys(out)) {
      out[cat].sort((a, b) => a.name.localeCompare(b.name));
    }
    return CATEGORY_ORDER
      .filter(c => out[c]?.length)
      .map(c => ({ name: c, agents: out[c] }));
  }

  let expandedSlug = $state(/** @type {string|null} */(null));

  function isV2Conditions(cond) {
    if (!cond || typeof cond !== 'object') return false;
    if ('all' in cond || 'any' in cond || 'not' in cond) return true;
    return 'metric' in cond && 'scope' in cond;
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    loadAll();
    connectWS();
    refreshInterval = setInterval(loadAll, 30000);
  });

  onDestroy(() => {
    if (ws) ws.close();
    if (refreshInterval) clearInterval(refreshInterval);
  });
</script>

<svelte:head>
  <title>Agents | RamboQuant Analytics</title>
</svelte:head>

<div class="algo-ts">{clientTimestamp()}</div>
<h1 class="page-title-chip mb-2">Agents</h1>

{#if error}
  <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
{/if}

<!-- Grouped agent list — compact rows, click to expand -->
{#each groupedAgents() as group}
  <h2 class="text-[0.6rem] font-bold uppercase tracking-wider text-[#fbbf24] mt-3 mb-1.5 border-b border-[#fbbf24]/25 pb-0.5">
    {group.name}
    <span class="opacity-60 font-normal ml-1">({group.agents.length})</span>
  </h2>
  <div class="space-y-1 mb-3">
    {#each group.agents as agent}
      {@const isOpen = expandedSlug === agent.slug}
      <div class="algo-status-card {agent.status === 'triggered' ? 'animate-pulse' : ''}"
           data-status={agent.status}
           style="padding: 0">
        <!-- Compact row (always visible). Div + role="button" so the inner
             ON/OFF can stay a real <button> — nested buttons aren't valid. -->
        <div role="button" tabindex="0"
          onclick={() => expandedSlug = isOpen ? null : agent.slug}
          onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); expandedSlug = isOpen ? null : agent.slug; } }}
          class="w-full flex items-center gap-2 px-2 py-1 text-left cursor-pointer select-none">
          <span class="w-2 h-2 rounded-full {statusDot(agent.status)} flex-shrink-0"></span>
          <span class="text-xs text-[#fbbf24] flex-1 truncate">{agent.name}</span>
          {#if isV2Conditions(agent.conditions)}
            <span class="text-[0.5rem] px-1 py-0 rounded bg-[#7dd3fc]/15 text-[#7dd3fc] border border-[#7dd3fc]/30 uppercase tracking-wider flex-shrink-0">v2</span>
          {/if}
          <button type="button"
            onclick={(e) => { e.stopPropagation(); toggle(agent); }}
            class="text-[0.55rem] px-1.5 py-0 rounded font-medium border flex-shrink-0
              {agent.status !== 'inactive'
                ? 'bg-green-500/15 text-green-400 border-green-500/40'
                : 'bg-slate-700/40 text-slate-400 border-slate-500/30'}">
            {agent.status !== 'inactive' ? 'ON' : 'OFF'}
          </button>
          <span class="text-[#7e97b8] text-[0.65rem] flex-shrink-0">{isOpen ? '▾' : '▸'}</span>
        </div>

        {#if isOpen}
          <!-- Expanded details -->
          <div class="px-2 pb-2 border-t border-white/5">
            {#if agent.description}
              <div class="text-[0.6rem] text-[#c8d8f0]/60 italic mt-1.5 mb-1">{agent.description}</div>
            {/if}
            <div class="text-[0.6rem] text-[#c8d8f0]/75 mb-1">
              <span class="text-[#7e97b8]">If:</span>
              <span class="font-mono">{conditionSummary(agent.conditions)}</span>
            </div>
            <div class="text-[0.6rem] text-[#c8d8f0]/75 mb-1">
              <span class="text-[#7e97b8]">Alert via:</span> {channelSummary(agent.events)}
              <span class="mx-1 text-[#7e97b8]">|</span>
              <span class="text-[#7e97b8]">Do:</span> {actionSummary(agent.actions)}
            </div>
            <div class="flex items-center justify-between text-[0.55rem] text-[#7e97b8] mt-2">
              <span>
                Last fire: {agent.last_triggered_at?.slice(0, 16) || '—'}
                <span class="mx-1">|</span>
                Count: {agent.trigger_count}
                <span class="mx-1">|</span>
                Cooldown: {agent.cooldown_minutes}m
                <span class="mx-1">|</span>
                Scope: {agent.scope}
              </span>
              <button onclick={(e) => { e.stopPropagation(); startEdit(agent); }}
                class="text-[#fbbf24] hover:underline">Edit</button>
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/each}

<!-- Agent Editor (inline) -->
{#if editing}
  <div class="algo-status-card p-4 mb-4" data-status="inactive">
    <div class="flex items-center justify-between mb-3">
      <h3 class="section-heading">Edit: {editing}</h3>
      <button onclick={() => editing = null} class="text-xs text-muted hover:text-text">Cancel</button>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <label class="field-label">Name</label>
        <input bind:value={editForm.name} class="field-input" />
      </div>
      <div>
        <label class="field-label">Description</label>
        <input bind:value={editForm.description} class="field-input" />
      </div>
      <div>
        <label class="field-label">Scope</label>
        <select bind:value={editForm.scope} class="field-input">
          <option value="per_account">Per Account</option>
          <option value="total">Total Only</option>
        </select>
      </div>
      <div>
        <label class="field-label">Schedule</label>
        <select bind:value={editForm.schedule} class="field-input">
          <option value="market_hours">Market Hours</option>
          <option value="always">Always</option>
        </select>
      </div>
      <div>
        <label class="field-label">Cooldown (minutes)</label>
        <input type="number" bind:value={editForm.cooldown_minutes} class="field-input" />
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
      <div>
        <label class="field-label">Conditions (JSON)</label>
        <textarea bind:value={editForm.conditions} class="field-input font-mono text-[0.6rem]" rows="5"></textarea>
      </div>
      <div>
        <label class="field-label">Events (JSON)</label>
        <textarea bind:value={editForm.events} class="field-input font-mono text-[0.6rem]" rows="5"></textarea>
      </div>
      <div>
        <label class="field-label">Actions (JSON)</label>
        <textarea bind:value={editForm.actions} class="field-input font-mono text-[0.6rem]" rows="5"></textarea>
      </div>
    </div>
    <div class="flex gap-2 mt-3">
      <button onclick={saveEdit} class="btn-primary text-[0.65rem] py-1 px-4">Save</button>
      <button onclick={() => editing = null} class="btn-secondary text-[0.65rem] py-1 px-4">Cancel</button>
    </div>
  </div>
{/if}

<LogPanel
  heightClass="h-[50vh]"
  initialTab={logTab}
  cmdHistory={[]}
  {orderLog}
  agentLog={agentEvents}
  {systemLog}
  onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
/>
