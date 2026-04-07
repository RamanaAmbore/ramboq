<script>
  // Generic grammar-driven command bar with token-by-token autocomplete.
  // Usage:
  //   <CommandBar {grammar} context={{...}} onsubmit={(parsed)=>{...}} placeholder="…" />
  //
  // Props:
  //   grammar  — grammar object from command/engine.js conventions
  //   context  — extra ctx passed to suggesters (e.g. { openOrderIds: [...] })
  //   onsubmit — called with `parse(line, grammar, context)` on Enter (if errors.length === 0)
  //   onsubmitRaw — called with raw parse output regardless of errors (optional)
  //   placeholder, rows, showHelp, disabled — passthrough
  //
  // Keys: Arrow up/down to navigate suggestions, Tab or Enter to complete,
  //       Enter on empty suggestion or after valid command → submit.
  //       Escape closes the dropdown.

  import { suggestAt, applySuggestion, parse } from '$lib/command/engine';

  let {
    grammar,
    context = {},
    onsubmit = () => {},
    onsubmitRaw = null,
    placeholder = '',
    rows = 2,
    showHelp = true,
    disabled = false,
    initialValue = '',
    minPrefixLen = 3,
    previewFn = null,
    class: cls = '',
  } = $props();

  let symbolPreview = $state('');

  let value     = $state(initialValue);
  let cursor    = $state(0);
  let suggOpen  = $state(false);
  let suggIdx   = $state(0);
  let suggList  = $state(/** @type {string[]} */([]));
  let role      = $state(/** @type {string|null} */(null));
  let hint      = $state(/** @type {string|null} */(null));
  let errors    = $state(/** @type {string[]} */([]));
  let taEl;
  let suggListEl = $state(/** @type {HTMLDivElement | null} */(null));
  let prevRole = '';

  function _currentPrefix() {
    // The text of the token currently under the cursor (or empty if at a space).
    const before = value.slice(0, cursor);
    const lastSpace = before.lastIndexOf(' ');
    const tok = lastSpace >= 0 ? before.slice(lastSpace + 1) : before;
    // Strip any kwarg-key portion (chase=) — we want just the value part
    const eq = tok.indexOf('=');
    return eq >= 0 ? tok.slice(eq + 1) : tok;
  }

  function refreshSuggestions() {
    if (!grammar) { suggList = []; return; }
    try {
      const result = suggestAt(value, cursor, grammar, context);
      let newList = result.suggestions || [];
      const newRole = result.role;
      const roleChanged = newRole !== prevRole;
      // Enforce minimum prefix length for large-list roles (symbol/strike/etc.)
      // Verb, account, kwarg-key, and fixed-value roles (orderType, instType, chase)
      // always show. Free-text roles require `minPrefixLen` chars typed.
      const alwaysShowRoles = new Set(['verb', 'account', 'kwarg-key', 'orderType', 'instType', 'order_id', 'qty', 'price', 'strike']);
      const currentPrefix = _currentPrefix();
      const isGatedRole = !alwaysShowRoles.has(newRole) && !newRole?.startsWith('kwarg:');
      if (isGatedRole && currentPrefix.length < minPrefixLen) {
        newList = [];
      }
      suggList = newList;
      role = newRole;
      hint = result.hint;
      // On role change (new token), initialize suggIdx to suggester's focus hint
      // (e.g. ATM strike) or 0; otherwise clamp existing suggIdx.
      if (roleChanged) {
        const focus = /** @type {any} */ (newList)._focusIndex;
        suggIdx = (typeof focus === 'number' && focus >= 0 && focus < newList.length) ? focus : 0;
      } else {
        suggIdx = Math.min(suggIdx, Math.max(0, newList.length - 1));
      }
      prevRole = newRole;
      if (!suggOpen && newList.length > 0) suggOpen = true;
      if (newList.length === 0) suggOpen = false;
      // Scroll active item into view after DOM updates
      if (suggOpen && newList.length > 0) {
        queueMicrotask(_scrollActiveIntoView);
      }
    } catch (e) {
      suggList = []; suggOpen = false;
    }
  }

  function _scrollActiveIntoView() {
    if (!suggListEl) return;
    const active = suggListEl.querySelector('.cmd-suggest-item.active');
    if (active) active.scrollIntoView({ block: 'center' });
  }

  function refreshErrors() {
    if (!grammar || !value.trim()) { errors = []; symbolPreview = ''; return; }
    try {
      const p = parse(value, grammar, context);
      // Only show errors that are NOT "missing X" — those are expected while
      // the user is still typing. Show only validation errors (wrong value, etc.)
      errors = (p.errors || []).filter(e => !e.startsWith('missing '));
      symbolPreview = (previewFn && (p.errors || []).length === 0) ? (previewFn(p) || '') : '';
    } catch (e) {
      errors = [e.message]; symbolPreview = '';
    }
  }

  function applyCurrent() {
    if (suggList.length === 0) return false;
    const pick = suggList[suggIdx];
    const result = applySuggestion(value, cursor, pick);
    value = result.line;
    cursor = result.cursor;
    suggOpen = false;
    // Update textarea DOM cursor after Svelte applies the new value
    queueMicrotask(() => {
      if (taEl) {
        taEl.focus();
        taEl.setSelectionRange(cursor, cursor);
      }
      refreshSuggestions();
      refreshErrors();
    });
    return true;
  }

  function submit() {
    if (!value.trim()) return;
    const p = parse(value, grammar, context);
    if (onsubmitRaw) onsubmitRaw(p);
    if (!p.errors || p.errors.length === 0) {
      onsubmit(p);
    }
  }

  function onKeydown(e) {
    if (e.key === 'ArrowDown' && suggOpen) {
      e.preventDefault();
      suggIdx = (suggIdx + 1) % suggList.length;
      queueMicrotask(_scrollActiveIntoView);
    } else if (e.key === 'ArrowUp' && suggOpen) {
      e.preventDefault();
      suggIdx = (suggIdx - 1 + suggList.length) % suggList.length;
      queueMicrotask(_scrollActiveIntoView);
    } else if (e.key === 'Tab') {
      if (applyCurrent()) e.preventDefault();
    } else if (e.key === 'Escape') {
      suggOpen = false;
    } else if (e.key === 'Enter' && !e.shiftKey) {
      // If suggestion is open AND the user is mid-token → apply; else submit
      if (suggOpen && suggList.length > 0) {
        const trimmedBefore = value.slice(0, cursor);
        const endsWithSpace = trimmedBefore.endsWith(' ') || trimmedBefore === '';
        if (!endsWithSpace) {
          e.preventDefault();
          applyCurrent();
          return;
        }
      }
      e.preventDefault();
      submit();
    }
  }

  function onInput(e) {
    value = e.target.value;
    cursor = e.target.selectionStart;
    refreshSuggestions();
    refreshErrors();
  }

  function onSelect(e) {
    cursor = e.target.selectionStart;
    refreshSuggestions();
  }

  function onFocus() {
    refreshSuggestions();
  }

  function onBlur() {
    // Delay so click on suggestion still fires
    setTimeout(() => { suggOpen = false; }, 120);
  }

  function pickSuggestion(i) {
    suggIdx = i;
    applyCurrent();
  }

  // NOTE: intentionally no $effect on `context` — suggestions and errors are
  // recomputed only on actual keystrokes / focus / cursor moves. Reacting to
  // every context change would re-run the (expensive) symbol suggester every
  // time the parent polls orders/websocket, freezing the input.

  export function clear() { value = ''; cursor = 0; suggOpen = false; errors = []; }
  export function setValue(v) { value = v; cursor = v.length; refreshSuggestions(); refreshErrors(); }
  export function refresh() { refreshSuggestions(); refreshErrors(); }
  export { submit };
</script>

<div class="cmdbar {cls}">
  <textarea
    bind:this={taEl}
    {placeholder}
    {rows}
    {disabled}
    class="field-input cmd-input font-mono text-xs w-full"
    value={value}
    oninput={onInput}
    onkeydown={onKeydown}
    onselect={onSelect}
    onfocus={onFocus}
    onblur={onBlur}
  ></textarea>

  {#if suggOpen && suggList.length > 0}
    <div class="cmd-suggest" bind:this={suggListEl}>
      {#each suggList as item, i}
        <button
          type="button"
          tabindex="-1"
          onmousedown={(e) => { e.preventDefault(); pickSuggestion(i); }}
          class="cmd-suggest-item {i === suggIdx ? 'active' : ''}"
        >{item}</button>
      {/each}
    </div>
  {/if}

  {#if showHelp}
    <div class="text-[0.6rem] mt-0.5 flex gap-3 items-center flex-wrap">
      {#if role}
        <span class="role-badge">{role}</span>
      {/if}
      {#if hint}<span class="text-muted opacity-70">{hint}</span>{/if}
      {#if symbolPreview}<span class="symbol-preview">{symbolPreview}</span>{/if}
      {#if errors.length > 0}<span class="text-red-500">{errors.join(' · ')}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .cmdbar {
    position: relative;
    width: 100%;
  }
  .cmd-suggest {
    position: absolute;
    top: calc(100% + 2px);
    left: 0;
    min-width: 160px;
    max-width: 100%;
    width: max-content;
    max-height: 220px;
    overflow-y: auto;
    background: #1a2332;
    border: 1px solid #334155;
    border-radius: 0.375rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    z-index: 40;
    font-size: 0.7rem;
  }
  .cmd-suggest-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.2rem 0.7rem;
    background: transparent;
    border: none;
    color: #cbd5e1;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    cursor: pointer;
    white-space: nowrap;
  }
  .cmd-suggest-item:hover { background: rgba(255,255,255,0.06); }
  .cmd-suggest-item.active { background: rgba(245,158,11,0.2); color: #fbbf24; }
  :global(.text-accent) { color: #f59e0b; }

  .symbol-preview {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.6rem;
    font-weight: 600;
    color: #22d3ee;
    background: rgba(34,211,238,0.1);
    padding: 0.1rem 0.4rem;
    border-radius: 0.25rem;
  }
  .role-badge {
    display: inline-block;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
    font-size: 0.65rem;
    color: #fff;
    background: #f59e0b;
    padding: 0.1rem 0.5rem;
    border-radius: 0.25rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
</style>
