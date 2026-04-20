<script>
  // Admin Settings — DB-backed tunables grouped by category. Pairs with
  // backend/api/routes/settings.py and backend/shared/helpers/settings.py.
  // Seed list is the authoritative catalog of editable knobs; this page
  // renders it and writes back via PATCH.

  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authStore, clientTimestamp } from '$lib/stores';
  import { fetchSettings, updateSetting, resetSetting } from '$lib/api';

  /** @type {Array<{id:number, category:string, key:string, value_type:string,
   *                value:string, default_value:string, description:string,
   *                schema:any, units:string|null, updated_at:string}>} */
  let settings = $state([]);
  let loading  = $state(true);
  let error    = $state('');
  let note     = $state('');
  let dirty    = $state(/** @type {Record<string, string>} */({}));

  async function load() {
    loading = true; error = '';
    try { settings = await fetchSettings(); }
    catch (e) { error = e.message; }
    finally   { loading = false; }
  }

  function onEdit(/** @type {any} */ s, /** @type {any} */ newVal) {
    dirty[s.key] = String(newVal);
  }

  async function save(/** @type {any} */ s) {
    error = ''; note = '';
    try {
      const updated = await updateSetting(s.key, dirty[s.key]);
      // Replace the row in-place so the UI reflects canonical server value.
      settings = settings.map(r => r.key === s.key ? updated : r);
      delete dirty[s.key];
      dirty = { ...dirty };
      note = `Saved ${s.key}`;
    } catch (e) { error = `Save failed: ${e.message}`; }
  }

  async function reset(/** @type {any} */ s) {
    error = ''; note = '';
    try {
      const updated = await resetSetting(s.key);
      settings = settings.map(r => r.key === s.key ? updated : r);
      delete dirty[s.key];
      dirty = { ...dirty };
      note = `Reset ${s.key} to ${updated.default_value}`;
    } catch (e) { error = `Reset failed: ${e.message}`; }
  }

  // Group settings by category for rendering.
  const grouped = $derived.by(() => {
    const out = /** @type {Record<string, typeof settings>} */({});
    for (const s of settings) (out[s.category] ??= []).push(s);
    return Object.entries(out).sort(([a], [b]) => a.localeCompare(b));
  });

  function currentValue(/** @type {any} */ s) {
    return s.key in dirty ? dirty[s.key] : s.value;
  }
  function isDirty(/** @type {any} */ s) {
    return s.key in dirty && dirty[s.key] !== s.value;
  }
  function isModified(/** @type {any} */ s) {
    return s.value !== s.default_value;
  }

  onMount(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') { goto('/signin'); return; }
    load();
  });
</script>

<svelte:head><title>Settings | RamboQuant Analytics</title></svelte:head>

<div class="algo-ts">{clientTimestamp()}</div>
<h1 class="page-title-chip mb-2">Settings</h1>

<p class="text-[0.65rem] text-[#c8d8f0]/70 mb-3 max-w-3xl">
  DB-backed tunables. Edits here take effect on the next agent tick / sim run
  without a deploy. Values are preserved across deploys; pressing <b>Reset</b>
  returns a key to its code-shipped default. Infrastructure parameters (DB
  credentials, market hours, Kite URLs, IPv6 addresses) deliberately stay in
  <span class="font-mono">backend_config.yaml</span> — they change once a
  quarter and have no business being in the DB.
</p>

{#if error}<div class="mb-3 p-2 rounded bg-red-500/15 text-red-300 text-[0.65rem] border border-red-500/40">{error}</div>{/if}
{#if note}<div class="mb-3 p-2 rounded bg-emerald-500/10 text-emerald-300 text-[0.65rem] border border-emerald-500/30">{note}</div>{/if}

{#if loading}
  <div class="text-[0.65rem] text-[#c8d8f0]/60">Loading…</div>
{:else if !settings.length}
  <div class="text-[0.65rem] text-[#c8d8f0]/60">No settings seeded yet.</div>
{:else}
  {#each grouped as [category, rows]}
    <section class="algo-status-card p-3 mb-3" data-status="inactive">
      <h2 class="text-[0.6rem] font-bold uppercase tracking-wider text-[#fbbf24] mb-2 pb-1 border-b border-[#fbbf24]/25">
        {category} <span class="opacity-60 font-normal ml-1">({rows.length})</span>
      </h2>
      <div class="space-y-2">
        {#each rows as s}
          <div class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_120px_auto_auto] gap-2 items-start text-[0.65rem] py-1 border-b border-white/5 last:border-0">
            <div>
              <div class="flex items-baseline gap-2 flex-wrap">
                <span class="font-mono text-[#7dd3fc]">{s.key}</span>
                {#if isModified(s)}
                  <span class="px-1 rounded bg-[#fbbf24]/15 text-[#fbbf24] border border-[#fbbf24]/30 text-[0.55rem]">modified</span>
                {/if}
              </div>
              <div class="text-[0.6rem] text-[#c8d8f0]/75 mt-0.5">{s.description}</div>
              <div class="text-[0.55rem] text-[#7e97b8] mt-0.5">
                default: <span class="font-mono">{s.default_value}</span>
                {#if s.schema && (s.schema.min !== undefined || s.schema.max !== undefined)}
                  <span class="mx-1">·</span>range: {s.schema.min ?? '−∞'} … {s.schema.max ?? '+∞'}
                {/if}
                {#if s.schema?.enum}
                  <span class="mx-1">·</span>choices: {s.schema.enum.join(' / ')}
                {/if}
              </div>
            </div>

            <div class="flex items-center gap-1">
              {#if s.value_type === 'bool'}
                <select class="field-input flex-1"
                        value={currentValue(s)}
                        onchange={(e) => onEdit(s, e.currentTarget.value)}>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              {:else if s.value_type === 'enum'}
                <select class="field-input flex-1"
                        value={currentValue(s)}
                        onchange={(e) => onEdit(s, e.currentTarget.value)}>
                  {#each (s.schema?.enum || []) as opt}<option value={opt}>{opt}</option>{/each}
                </select>
              {:else if s.value_type === 'int' || s.value_type === 'float'}
                <input type="number"
                       class="field-input flex-1"
                       value={currentValue(s)}
                       min={s.schema?.min} max={s.schema?.max} step={s.schema?.step ?? 1}
                       oninput={(e) => onEdit(s, e.currentTarget.value)} />
              {:else}
                <input type="text"
                       class="field-input flex-1"
                       value={currentValue(s)}
                       oninput={(e) => onEdit(s, e.currentTarget.value)} />
              {/if}
              {#if s.units}<span class="text-[0.55rem] text-[#7e97b8] whitespace-nowrap">{s.units}</span>{/if}
            </div>

            <button type="button"
              onclick={() => save(s)}
              disabled={!isDirty(s)}
              class="btn-primary text-[0.6rem] py-1 px-3 disabled:opacity-30 whitespace-nowrap">Save</button>

            <button type="button"
              onclick={() => reset(s)}
              disabled={!isModified(s)}
              class="btn-secondary text-[0.6rem] py-1 px-3 disabled:opacity-30 whitespace-nowrap">Reset</button>
          </div>
        {/each}
      </div>
    </section>
  {/each}
{/if}
