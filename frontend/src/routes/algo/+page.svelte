<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp, logTime } from '$lib/stores';
  import { fetchAgents, activateAgent, deactivateAgent, updateAgent, fetchRecentAgentEvents } from '$lib/api';

  let agents      = $state([]);
  let agentEvents = $state([]);
  let loading     = $state(true);
  let error       = $state('');
  let logTab      = $state('agent');  // agent | system
  let systemLog   = $state([]);
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

  const statusBorder = (/** @type {string} */ s) => ({
    active: 'border-green-500', inactive: 'border-gray-300',
    triggered: 'border-red-500', running: 'border-orange-400',
    cooldown: 'border-amber-400', error: 'border-red-600',
  }[s] || 'border-gray-300');

  const statusDot = (/** @type {string} */ s) => ({
    active: 'bg-green-500', inactive: 'bg-gray-400',
    triggered: 'bg-red-500', running: 'bg-orange-400',
    cooldown: 'bg-amber-400', error: 'bg-red-600',
  }[s] || 'bg-gray-400');

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
  <title>Algo Agent | RamboQuant Analytics</title>
</svelte:head>

<div class="text-[0.65rem] text-muted mb-2">{clientTimestamp()}</div>

{#if error}
  <div class="mb-3 p-2 rounded bg-red-50 text-red-700 text-xs border border-red-200">{error}</div>
{/if}

<!-- Agent Cards Grid -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
  {#each agents as agent}
    <div class="rounded-lg border-2 {statusBorder(agent.status)} bg-white p-3 {agent.status === 'triggered' ? 'animate-pulse' : ''}">
      <!-- Header -->
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full {statusDot(agent.status)}"></span>
          <span class="font-semibold text-xs text-primary">{agent.name}</span>
        </div>
        <button
          onclick={() => toggle(agent)}
          class="text-[0.6rem] px-2 py-0.5 rounded font-medium
            {agent.status !== 'inactive'
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-500'}"
        >{agent.status !== 'inactive' ? 'ON' : 'OFF'}</button>
      </div>

      <!-- Conditions -->
      <div class="text-[0.6rem] text-text/70 mb-1">
        <span class="text-muted">If:</span> {conditionSummary(agent.conditions)}
      </div>

      <!-- Channels + Actions -->
      <div class="text-[0.6rem] text-text/70 mb-1">
        <span class="text-muted">Alert:</span> {channelSummary(agent.events)}
        <span class="mx-1">|</span>
        <span class="text-muted">Do:</span> {actionSummary(agent.actions)}
      </div>

      <!-- Stats + Edit -->
      <div class="flex items-center justify-between text-[0.55rem] text-muted mt-2">
        <span>Last: {agent.last_triggered_at?.slice(0, 16) || '—'} | #{agent.trigger_count}</span>
        <button onclick={() => startEdit(agent)} class="text-primary hover:underline">Edit</button>
      </div>
    </div>
  {/each}
</div>

<!-- Agent Editor (inline) -->
{#if editing}
  <div class="bg-white rounded-lg border border-gray-200 p-4 mb-4">
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

<!-- Log Tabs -->
<div class="flex items-center gap-1 mb-2">
  {#each [['order','Order Log'],['terminal','Terminal'],['agent','Agent Log'],['system','System Log']] as [id, label]}
    <button
      onclick={() => { logTab = id; if (id === 'agent') loadAgentLog(); else if (id === 'system') loadSystemLog(); }}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >{label}</button>
  {/each}
</div>

<pre class="log-panel h-[50vh]">{#if logTab === 'agent'}{#if agentEvents.length}{@html agentEvents.map(e => {
  const t = logTime(e.timestamp);
  const cls = e.event_type === 'triggered' ? 'log-agent-triggered' : e.event_type === 'alert_sent' ? 'log-agent-alert' : e.event_type?.includes('success') ? 'log-agent-success' : e.event_type?.includes('fail') ? 'log-agent-failed' : 'log-agent-default';
  return `<span class="${cls}">[${t}] ${e.event_type||''} ${e.trigger_condition || ''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else if logTab === 'system'}{#if systemLog.length}{@html systemLog.map(line => {
  const cls = line.includes('ERROR') ? 'log-error' : line.includes('WARNING') ? 'log-warning' : 'log-info';
  return `<span class="${cls}">${line}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{:else if logTab === 'terminal'}<span class="log-debug">Use the Terminal page to run commands.</span>{:else}<span class="log-debug">No order events.</span>{/if}</pre>
