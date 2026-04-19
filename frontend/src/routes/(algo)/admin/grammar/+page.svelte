<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp } from '$lib/stores';
  import { fetchGrammarTokens, patchGrammarToken, reloadGrammarRegistry } from '$lib/api';

  // Grammar catalog viewer — read + is_active toggle for every token in
  // grammar_tokens. System tokens are toggle-only (per the backend
  // contract); custom tokens will get a full edit modal in a later phase.

  /** @type {{id:number, grammar_kind:string, token_kind:string, token:string,
   *          value_type:string|null, units:string|null, description:string,
   *          resolver:string|null, params_schema:object|null,
   *          enum_values:any[]|null, template_body:string|null,
   *          is_system:boolean, is_active:boolean}[]} */
  let tokens   = $state([]);
  let loading  = $state(true);
  let error    = $state('');
  let reloading = $state(false);
  let activeTab = $state(/** @type {'condition'|'notify'|'action'} */('condition'));
  let expandedId = $state(/** @type {number|null} */(null));

  async function load() {
    loading = true; error = '';
    try {
      tokens = await fetchGrammarTokens();
    } catch (e) { error = e.message || 'Failed to load'; tokens = []; }
    loading = false;
  }

  async function toggle(id, currentActive) {
    try {
      const updated = await patchGrammarToken(id, { is_active: !currentActive });
      const idx = tokens.findIndex(t => t.id === id);
      if (idx >= 0) tokens[idx] = updated;
    } catch (e) { error = e.message || 'Toggle failed'; }
  }

  async function doReload() {
    reloading = true; error = '';
    try { await reloadGrammarRegistry(); }
    catch (e) { error = e.message || 'Reload failed'; }
    reloading = false;
  }

  function filtered() {
    return tokens.filter(t => t.grammar_kind === activeTab);
  }

  function tokenCount(kind) {
    return tokens.filter(t => t.grammar_kind === kind).length;
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    load();
  });
</script>

<svelte:head><title>Grammar | RamboQuant Analytics</title></svelte:head>

<div class="algo-ts">{clientTimestamp()}</div>

<div class="algo-status-card p-4 mb-3" data-status="inactive">
  <div class="flex items-center justify-between mb-2">
    <h1 class="text-sm font-bold uppercase tracking-wider text-[#fbbf24]">
      Agent Grammar
    </h1>
    <button onclick={doReload} disabled={reloading}
      class="text-[0.65rem] py-1 px-3 rounded border border-[#fbbf24]/50 bg-[#fbbf24]/15 text-[#fbbf24] hover:bg-[#fbbf24]/25 font-semibold disabled:opacity-50">
      {reloading ? 'Reloading…' : 'Reload registry'}
    </button>
  </div>
  <p class="text-[0.65rem] text-[#7e97b8] mb-0">
    Every token the Agent engine can reference. System tokens are toggle-only.
    Use the tabs to browse condition / notify / action grammars.
    After any change, hit <b>Reload registry</b> so the dispatch table refreshes
    without a service restart.
  </p>
</div>

{#if error}
  <div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-xs border border-red-500/40">{error}</div>
{/if}

<!-- Tab row -->
<div class="flex gap-1 mb-3">
  {#each [['condition', 'Condition'], ['notify', 'Notify'], ['action', 'Action']] as [key, label]}
    <button onclick={() => { activeTab = key; expandedId = null; }}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {activeTab === key
          ? 'border-[#fbbf24] text-[#fbbf24]'
          : 'border-transparent text-[#b4c8e6] hover:text-[#fbbf24]'}">
      {label}
      <span class="ml-1 text-[0.55rem] opacity-70">({tokenCount(key)})</span>
    </button>
  {/each}
</div>

{#if loading}
  <div class="text-center text-[#7e97b8] text-xs animate-pulse py-6">Loading tokens…</div>
{:else if !filtered().length}
  <div class="text-center text-[#7e97b8] text-xs py-6">No tokens in this grammar.</div>
{:else}
  <div class="algo-status-card p-0 overflow-hidden" data-status="inactive">
    <table class="w-full text-[0.65rem]">
      <thead>
        <tr class="bg-[#0a1020] text-[#fbbf24]">
          <th class="text-left py-1.5 px-2">Kind</th>
          <th class="text-left py-1.5 px-2">Token</th>
          <th class="text-left py-1.5 px-2">Value</th>
          <th class="text-left py-1.5 px-2">Units</th>
          <th class="text-left py-1.5 px-2">Description</th>
          <th class="text-left py-1.5 px-2">Origin</th>
          <th class="text-left py-1.5 px-2">Active</th>
        </tr>
      </thead>
      <tbody>
        {#each filtered() as t}
          <tr class="border-t border-white/5 hover:bg-white/5 cursor-pointer"
              onclick={() => expandedId = expandedId === t.id ? null : t.id}>
            <td class="py-1.5 px-2 text-[#7e97b8] font-mono uppercase text-[0.55rem]">{t.token_kind}</td>
            <td class="py-1.5 px-2 font-mono text-[#fbbf24]">{t.token}</td>
            <td class="py-1.5 px-2 text-[#c8d8f0]">{t.value_type ?? '—'}</td>
            <td class="py-1.5 px-2 text-[#c8d8f0]">{t.units ?? '—'}</td>
            <td class="py-1.5 px-2 text-[#c8d8f0]/80 text-[0.6rem] max-w-[360px] truncate"
                title={t.description}>{t.description || '—'}</td>
            <td class="py-1.5 px-2">
              {#if t.is_system}
                <span class="px-1.5 py-0.5 rounded bg-slate-500/20 text-slate-300 text-[0.55rem] font-semibold uppercase border border-slate-500/40">System</span>
              {:else}
                <span class="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 text-[0.55rem] font-semibold uppercase border border-emerald-500/40">Custom</span>
              {/if}
            </td>
            <td class="py-1.5 px-2" onclick={(e) => e.stopPropagation()}>
              <button onclick={() => toggle(t.id, t.is_active)}
                class="text-[0.6rem] px-2 py-0.5 rounded font-medium border
                  {t.is_active
                    ? 'bg-green-500/15 text-green-400 border-green-500/40'
                    : 'bg-slate-700/40 text-slate-400 border-slate-500/30'}">
                {t.is_active ? 'ON' : 'OFF'}
              </button>
            </td>
          </tr>
          {#if expandedId === t.id}
            <tr class="bg-[#0a1020]">
              <td colspan="7" class="py-2 px-3 text-[0.6rem] text-[#c8d8f0]/80">
                <div class="grid grid-cols-2 gap-x-6 gap-y-1">
                  {#if t.resolver}
                    <div><span class="text-[#7e97b8]">Resolver:</span> <span class="font-mono">{t.resolver}</span></div>
                  {/if}
                  {#if t.params_schema}
                    <div class="col-span-2">
                      <div class="text-[#7e97b8] mb-0.5">Params schema</div>
                      <pre class="text-[0.55rem] bg-black/30 p-2 rounded overflow-x-auto">{JSON.stringify(t.params_schema, null, 2)}</pre>
                    </div>
                  {/if}
                  {#if t.enum_values}
                    <div class="col-span-2">
                      <span class="text-[#7e97b8]">Enum values:</span> {JSON.stringify(t.enum_values)}
                    </div>
                  {/if}
                  {#if t.template_body}
                    <div class="col-span-2">
                      <div class="text-[#7e97b8] mb-0.5">Template body</div>
                      <pre class="text-[0.55rem] bg-black/30 p-2 rounded whitespace-pre-wrap">{t.template_body}</pre>
                    </div>
                  {/if}
                </div>
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
{/if}
