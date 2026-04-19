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
    validationErrors = [];
    validationGrammar = '';
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
    // Give Svelte a tick to render, then jump the browser to the editor so the
    // operator actually sees which agent opened (it was previously hidden
    // below a long list).
    setTimeout(() => {
      document.getElementById('agent-editor')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 40);
  }

  let validationErrors = $state(/** @type {string[]} */([]));
  let validationGrammar = $state('');

  // ── Live tree view of the agent under edit/create ────────────────────
  // Parsed state is derived from the three JSON textareas so every keystroke
  // reflects into the graphical tree without an explicit refresh.
  const parsedConditions = $derived.by(() => {
    try { return { ok: true, value: JSON.parse(editForm.conditions || '{}') }; }
    catch (e) { return { ok: false, error: e.message }; }
  });
  const parsedEvents = $derived.by(() => {
    try { return { ok: true, value: JSON.parse(editForm.events || '[]') }; }
    catch (e) { return { ok: false, error: e.message }; }
  });
  const parsedActions = $derived.by(() => {
    try { return { ok: true, value: JSON.parse(editForm.actions || '[]') }; }
    catch (e) { return { ok: false, error: e.message }; }
  });

  function leafLabel(node) {
    if (!node) return '';
    // v2 leaf: metric @ scope op value
    if (node.metric && node.scope) {
      const v = typeof node.value === 'number' && Math.abs(node.value) >= 1000
        ? `₹${node.value.toLocaleString('en-IN')}` : JSON.stringify(node.value);
      return `${node.metric}@${node.scope} ${node.op || '?'} ${v}`;
    }
    // v1 leaf: field op value
    if (node.field !== undefined) {
      const v = typeof node.value === 'number' && Math.abs(node.value) >= 1000
        ? `₹${node.value.toLocaleString('en-IN')}` : JSON.stringify(node.value);
      return `${node.field} ${node.op || '?'} ${v}`;
    }
    return JSON.stringify(node);
  }

  function treeNodeKind(node) {
    if (!node || typeof node !== 'object') return 'leaf';
    if (Array.isArray(node.all)) return 'all';
    if (Array.isArray(node.any)) return 'any';
    if (node.not !== undefined) return 'not';
    if (Array.isArray(node.rules) && node.operator) return node.operator; // v1 composite
    return 'leaf';
  }

  async function runValidation() {
    validationErrors = []; validationGrammar = '';
    let parsed;
    try { parsed = JSON.parse(editForm.conditions); }
    catch (e) { validationErrors = [`conditions JSON invalid: ${e.message}`]; return false; }
    try {
      const { validateAgentCondition } = await import('$lib/api');
      const res = await validateAgentCondition(parsed);
      validationGrammar = res.grammar || '';
      validationErrors = res.errors || [];
      return res.ok;
    } catch (e) {
      validationErrors = [e.message || 'Validation failed'];
      return false;
    }
  }

  async function saveEdit() {
    // Server-side validation must pass for v2 trees before we touch the
    // agent row — v1 trees are accepted as-is.
    const ok = await runValidation();
    if (!ok) return;
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
      validationErrors = []; validationGrammar = '';
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

<!-- Recursive tree renderer for the live preview (v1 + v2 condition trees) -->
{#snippet renderCondNode(node)}
  {#if !node || typeof node !== 'object'}
    <div class="tree-leaf">{JSON.stringify(node)}</div>
  {:else if Array.isArray(node.all) || (Array.isArray(node.rules) && node.operator === 'and')}
    {@const kids = node.all ?? node.rules ?? []}
    <div class="tree-node tree-node-all">
      <div class="tree-op">ALL</div>
      <div class="tree-children">
        {#each kids as child}{@render renderCondNode(child)}{/each}
      </div>
    </div>
  {:else if Array.isArray(node.any) || (Array.isArray(node.rules) && node.operator === 'or')}
    {@const kids = node.any ?? node.rules ?? []}
    <div class="tree-node tree-node-any">
      <div class="tree-op">ANY</div>
      <div class="tree-children">
        {#each kids as child}{@render renderCondNode(child)}{/each}
      </div>
    </div>
  {:else if node.not !== undefined}
    <div class="tree-node tree-node-not">
      <div class="tree-op">NOT</div>
      <div class="tree-children">{@render renderCondNode(node.not)}</div>
    </div>
  {:else}
    <div class="tree-leaf">{leafLabel(node)}</div>
  {/if}
{/snippet}

<!-- Agent Editor (inline) -->
{#if editing}
  <div id="agent-editor" class="algo-status-card p-4 mb-4" data-status="inactive">
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-baseline gap-2">
        <h3 class="section-heading">Editing agent</h3>
        <span class="text-[0.65rem] font-mono px-2 py-0.5 rounded bg-[#fbbf24]/15 text-[#fbbf24] border border-[#fbbf24]/40">{editing}</span>
      </div>
      <button onclick={() => editing = null} class="text-xs text-muted hover:text-text">Cancel</button>
    </div>

    <!-- Live preview lives at the TOP of the editor so it is always visible,
         even on narrow screens where the textareas would otherwise push it
         below the fold. Driven by $derived parsed state — every keystroke
         in the form flows through to this tree. -->
    <div class="agent-preview agent-preview-top mb-4">
      <div class="preview-heading">Live preview</div>

      <div class="grid grid-cols-1 md:grid-cols-[1fr_1fr] gap-3">
        <!-- Left of preview: header + condition tree -->
        <div>
          <div class="preview-header">
            <div class="preview-title">{editForm.name || '(unnamed agent)'}</div>
            {#if editForm.description}
              <div class="preview-desc">{editForm.description}</div>
            {/if}
            <div class="preview-meta">
              Scope: <b>{editForm.scope}</b>
              <span class="preview-sep">|</span>
              Schedule: <b>{editForm.schedule}</b>
              <span class="preview-sep">|</span>
              Cooldown: <b>{editForm.cooldown_minutes}m</b>
            </div>
          </div>
          <div class="preview-section-label">Condition tree</div>
          {#if parsedConditions.ok}
            <div class="preview-tree">
              {@render renderCondNode(parsedConditions.value)}
            </div>
          {:else}
            <div class="preview-error">Invalid JSON: {parsedConditions.error}</div>
          {/if}
        </div>

        <!-- Right of preview: notify + actions -->
        <div>
          <div class="preview-section-label">Notify</div>
          {#if parsedEvents.ok}
            {#if parsedEvents.value.length}
              <div class="flex flex-wrap gap-1">
                {#each parsedEvents.value as ev}
                  {@const on = ev.enabled !== false}
                  <span class="preview-chip {on ? 'chip-on' : 'chip-off'}">
                    {ev.channel || '?'}{on ? '' : ' (off)'}
                  </span>
                {/each}
              </div>
            {:else}
              <div class="preview-muted">no channels configured</div>
            {/if}
          {:else}
            <div class="preview-error">Invalid JSON: {parsedEvents.error}</div>
          {/if}

          <div class="preview-section-label">Actions</div>
          {#if parsedActions.ok}
            {#if parsedActions.value.length}
              <div class="space-y-1">
                {#each parsedActions.value as a}
                  <div class="preview-action">
                    <span class="preview-action-type">{a.type || '?'}</span>
                    {#if a.params && Object.keys(a.params).length}
                      <pre class="preview-action-params">{JSON.stringify(a.params, null, 2)}</pre>
                    {/if}
                  </div>
                {/each}
              </div>
            {:else}
              <div class="preview-muted">alert-only (no actions)</div>
            {/if}
          {:else}
            <div class="preview-error">Invalid JSON: {parsedActions.error}</div>
          {/if}
        </div>
      </div>
    </div>

    <!-- Form fields below the preview -->
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
    <!-- Validation feedback — v2 trees run through the grammar registry;
         v1 trees are accepted as-is and flow through the legacy evaluator. -->
    {#if validationErrors.length}
      <div class="mt-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.6rem] border border-red-500/40">
        <div class="font-semibold mb-1">Condition validation failed ({validationGrammar || '?'}):</div>
        <ul class="list-disc ml-4">
          {#each validationErrors as err}<li>{err}</li>{/each}
        </ul>
      </div>
    {:else if validationGrammar}
      <div class="mt-3 p-2 rounded bg-emerald-500/10 text-emerald-300 text-[0.6rem] border border-emerald-500/30">
        Validated as {validationGrammar} — ready to save.
      </div>
    {/if}

    <div class="flex gap-2 mt-3">
      <button onclick={async () => { await runValidation(); }}
        class="text-[0.65rem] py-1 px-3 rounded border border-[#7dd3fc]/50 bg-[#7dd3fc]/15 text-[#7dd3fc] hover:bg-[#7dd3fc]/25 font-semibold">
        Validate
      </button>
      <button onclick={saveEdit} class="btn-primary text-[0.65rem] py-1 px-4">Save</button>
      <button onclick={() => { editing = null; validationErrors = []; validationGrammar = ''; }}
        class="btn-secondary text-[0.65rem] py-1 px-4">Cancel</button>
    </div>
  </div>
{/if}

<style>
  /* Live-preview styling — compact, dense, matches algo dark palette. */
  .agent-preview {
    font-size: 0.65rem;
    color: #c8d8f0;
    border-left: 1px dashed rgba(255,255,255,0.08);
    padding-left: 0.75rem;
  }
  .preview-heading {
    font-size: 0.55rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #7e97b8;
    margin-bottom: 0.5rem;
  }
  .preview-header { margin-bottom: 0.5rem; }
  .preview-title { font-weight: 700; color: #fbbf24; font-size: 0.8rem; }
  .preview-desc  { font-style: italic; color: #c8d8f0aa; font-size: 0.6rem; margin-top: 0.1rem; }
  .preview-meta  { font-size: 0.55rem; color: #7e97b8; margin-top: 0.2rem; }
  .preview-sep   { margin: 0 0.35rem; color: #7e97b840; }
  .preview-section-label {
    font-size: 0.55rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #fbbf24;
    margin: 0.65rem 0 0.3rem;
    border-bottom: 1px solid rgba(251,191,36,0.15);
    padding-bottom: 0.1rem;
  }
  .preview-muted { color: #7e97b8; font-style: italic; }
  .preview-error {
    color: #f87171;
    background: rgba(239,68,68,0.1);
    border: 1px solid rgba(239,68,68,0.35);
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    font-family: ui-monospace, monospace;
    font-size: 0.6rem;
  }
  .preview-tree { font-family: ui-monospace, monospace; }
  /* Nested node pattern — indent on the left, operator badge at top, children below */
  :global(.tree-node) {
    border-left: 2px solid rgba(255,255,255,0.12);
    padding: 0.15rem 0 0.15rem 0.5rem;
    margin: 0.15rem 0;
  }
  :global(.tree-node-all) { border-left-color: #4ade80; }
  :global(.tree-node-any) { border-left-color: #fbbf24; }
  :global(.tree-node-not) { border-left-color: #f87171; }
  :global(.tree-op) {
    font-size: 0.5rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-weight: 700;
    color: inherit;
    margin-bottom: 0.1rem;
  }
  :global(.tree-node-all .tree-op) { color: #4ade80; }
  :global(.tree-node-any .tree-op) { color: #fbbf24; }
  :global(.tree-node-not .tree-op) { color: #f87171; }
  :global(.tree-children) { padding-left: 0.25rem; }
  :global(.tree-leaf) {
    font-size: 0.6rem;
    background: rgba(125,211,252,0.08);
    border: 1px solid rgba(125,211,252,0.2);
    color: #c8d8f0;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    margin: 0.15rem 0;
    display: inline-block;
  }
  .preview-chip {
    font-size: 0.55rem;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    border: 1px solid;
    font-family: ui-monospace, monospace;
  }
  .chip-on  { background: rgba(34,197,94,0.15);  color: #4ade80; border-color: rgba(34,197,94,0.4); }
  .chip-off { background: rgba(180,200,230,0.08); color: #7e97b8; border-color: rgba(180,200,230,0.2); }
  .preview-action {
    background: rgba(251,191,36,0.06);
    border: 1px solid rgba(251,191,36,0.2);
    border-radius: 3px;
    padding: 0.3rem 0.4rem;
  }
  .preview-action-type { color: #fbbf24; font-weight: 700; font-family: ui-monospace, monospace; font-size: 0.6rem; }
  .preview-action-params {
    font-size: 0.55rem;
    background: rgba(0,0,0,0.25);
    color: #c8d8f0;
    padding: 0.25rem 0.35rem;
    border-radius: 2px;
    margin-top: 0.2rem;
    overflow-x: auto;
  }
</style>

<LogPanel
  heightClass="h-[50vh]"
  initialTab={logTab}
  cmdHistory={[]}
  {orderLog}
  agentLog={agentEvents}
  {systemLog}
  onTabChange={(id) => { logTab = id; loadCurrentLog(); }}
/>
