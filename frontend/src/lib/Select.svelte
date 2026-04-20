<script>
  // Custom dropdown that mirrors the OrderPopup modal's palette —
  // linear-gradient(#273552 → #1d2a44), amber accents, monospace,
  // rounded corners. Replaces the native <select> on pages where the
  // OS-rendered popup looks foreign on the dark theme.
  //
  // Props:
  //   value         — currently-selected option value (bindable)
  //   options       — Array<{ value, label, hint? }>
  //   placeholder?  — shown when value is empty
  //   id?           — for <label for="...">
  //   disabled?     — bool
  //   ariaLabel?    — a11y fallback if no <label> is in scope

  import { onMount, onDestroy } from 'svelte';

  let {
    value = $bindable(''),
    options = [],
    placeholder = '',
    id = '',
    disabled = false,
    ariaLabel = '',
  } = $props();

  let open = $state(false);
  let triggerEl;
  let panelEl;
  let highlighted = $state(-1);

  const current = $derived(
    options.find(o => String(o.value) === String(value)) || null
  );
  const displayLabel = $derived(current?.label ?? placeholder ?? '');

  function toggle() {
    if (disabled) return;
    open = !open;
    if (open) {
      highlighted = Math.max(0, options.findIndex(o => String(o.value) === String(value)));
    }
  }

  function pick(/** @type {any} */ opt) {
    value = opt.value;
    open = false;
    triggerEl?.focus();
  }

  function onKey(/** @type {KeyboardEvent} */ e) {
    if (disabled) return;
    if (!open) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault();
        toggle();
      }
      return;
    }
    if (e.key === 'Escape') { open = false; e.preventDefault(); return; }
    if (e.key === 'ArrowDown') { highlighted = Math.min(options.length - 1, highlighted + 1); e.preventDefault(); return; }
    if (e.key === 'ArrowUp')   { highlighted = Math.max(0, highlighted - 1); e.preventDefault(); return; }
    if (e.key === 'Enter') {
      if (highlighted >= 0) pick(options[highlighted]);
      e.preventDefault();
      return;
    }
  }

  /** @type {(e: MouseEvent) => void} */
  function onDocClick(e) {
    if (!open) return;
    const t = /** @type {Node} */ (e.target);
    if (triggerEl?.contains(t) || panelEl?.contains(t)) return;
    open = false;
  }
  onMount(() => { document.addEventListener('mousedown', onDocClick); });
  onDestroy(() => { document.removeEventListener('mousedown', onDocClick); });
</script>

<div class="rbq-select {open ? 'rbq-select-open' : ''}">
  <button type="button" bind:this={triggerEl}
    {id} {disabled} aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}
    class="rbq-select-trigger"
    onclick={toggle}
    onkeydown={onKey}>
    <span class="rbq-select-label {!current ? 'rbq-select-placeholder' : ''}">{displayLabel || '\u00a0'}</span>
    <span class="rbq-select-caret" aria-hidden="true">▾</span>
  </button>

  {#if open}
    <ul class="rbq-select-panel" role="listbox" bind:this={panelEl}>
      {#each options as opt, i}
        {@const selected = String(opt.value) === String(value)}
        <li role="option" aria-selected={selected}
            class="rbq-select-option
              {selected ? 'rbq-select-option-selected' : ''}
              {highlighted === i ? 'rbq-select-option-hl' : ''}"
            onmousedown={() => pick(opt)}
            onmouseenter={() => { highlighted = i; }}>
          <span class="rbq-select-option-label">{opt.label}</span>
          {#if opt.hint}<span class="rbq-select-option-hint">{opt.hint}</span>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .rbq-select {
    position: relative;
    display: block;
    width: 100%;
    font-family: ui-monospace, monospace;
    color: #e2e8f0;
  }

  /* Trigger looks like .field-input but with the popup gradient so it
     clearly reads as "opens a popup, not a generic text input". */
  .rbq-select-trigger {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-height: 1.55rem;
    padding: 0.25rem 0.5rem 0.25rem 0.4rem;
    background-image: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    background-color: #1d2a44;
    border: 1px solid rgba(251,191,36,0.25);
    border-radius: 3px;
    color: #e2e8f0;
    font-size: 0.62rem;
    font-family: inherit;
    cursor: pointer;
    text-align: left;
    transition: border-color 0.08s;
  }
  .rbq-select-trigger:hover:not(:disabled)  { border-color: rgba(251,191,36,0.6); }
  .rbq-select-trigger:focus                 { outline: none; border-color: #fbbf24; }
  .rbq-select-trigger:disabled              { opacity: 0.45; cursor: not-allowed; }
  .rbq-select-open .rbq-select-trigger      { border-color: #fbbf24; }

  .rbq-select-label { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rbq-select-placeholder { color: rgba(180,200,230,0.55); }
  .rbq-select-caret {
    flex: 0 0 auto;
    color: #fbbf24;
    font-size: 0.55rem;
    transform: translateY(-1px);
  }
  .rbq-select-open .rbq-select-caret { transform: translateY(-1px) rotate(180deg); }

  /* Popup panel — mirrors .popup-modal from OrderPopup: same gradient,
     same amber-accent border, same box-shadow. Floats absolutely below
     the trigger. max-height + scroll for long lists. */
  .rbq-select-panel {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 60;
    margin: 0;
    padding: 0.2rem 0;
    list-style: none;
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    border: 1.5px solid rgba(251,191,36,0.35);
    border-radius: 4px;
    box-shadow: 0 10px 28px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06);
    max-height: 14rem;
    overflow-y: auto;
    font-size: 0.62rem;
    color: #e2e8f0;
  }

  .rbq-select-option {
    padding: 0.3rem 0.55rem;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    cursor: pointer;
    transition: background 0.06s, color 0.06s;
    border-left: 2px solid transparent;
  }
  .rbq-select-option-hl,
  .rbq-select-option:hover {
    background: rgba(251,191,36,0.15);
    color: #fbbf24;
    border-left-color: #fbbf24;
  }
  .rbq-select-option-selected {
    color: #fbbf24;
    font-weight: 700;
  }
  .rbq-select-option-selected::before {
    content: '✓';
    color: #4ade80;
    margin-right: 0.3rem;
  }
  .rbq-select-option-label { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rbq-select-option-hint {
    flex: 0 0 auto;
    font-size: 0.55rem;
    color: rgba(180,200,230,0.55);
  }
</style>
