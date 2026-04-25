<script>
  // Compact (i) chip with a click-toggle / hover-preview popover.
  // Used across the algo admin pages to gloss page sections, stats,
  // and form fields without taking up screen real estate.
  //
  // Two display modes:
  //   - default (popup=false) — inline expansion below the chip
  //   - popup (popup=true)    — floating absolute-positioned tooltip
  //                            (preferred for compact stat panels)
  //
  // Content delivery: pass either a `text` prop (string, may include
  // HTML) OR a children snippet. `text` wins when both are provided.
  // The text-prop path is the safer one for stable rendering across
  // SvelteKit hydration / SSR — children snippets occasionally lose
  // their content during the SSR → CSR handoff in this codebase.

  /** @type {{
   *   children?: any,
   *   text?: string,
   *   label?: string,
   *   maxWidth?: string,
   *   align?: 'left'|'right',
   *   defaultOpen?: boolean,
   *   popup?: boolean,
   * }} */
  let {
    children,
    text = '',
    label = 'i',
    maxWidth = '36rem',
    align = 'left',
    defaultOpen = false,
    popup = false,
  } = $props();

  let open = $state(defaultOpen);
  let hovered = $state(false);
  /** @type {HTMLSpanElement | undefined} */
  let wrap;

  // Close on click-outside when in popup mode so the tooltip doesn't
  // get stranded mid-page after the operator's attention has moved on.
  $effect(() => {
    if (!popup || !open) return;
    function onDocClick(/** @type {MouseEvent} */ e) {
      if (wrap && !wrap.contains(/** @type {Node} */ (e.target))) open = false;
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  });

  // Whether to render the popout right now.
  const visible = $derived(popup ? (open || hovered) : open);
</script>

<span class="info-wrap" class:align-right={align === 'right'}
      class:info-wrap-popup={popup}
      bind:this={wrap}>
  <button type="button"
          class="info-btn"
          class:open
          aria-expanded={open}
          aria-label={open ? 'Hide details' : 'Show details'}
          title={open ? 'Hide details' : 'Show details'}
          onclick={() => open = !open}
          onmouseenter={() => hovered = true}
          onmouseleave={() => hovered = false}>{label}</button>
  {#if visible}
    <span class="info-popout"
          class:info-popout-popup={popup}
          class:info-popout-pinned={popup && open}
          style="max-width: {maxWidth}">
      {#if text}
        {@html text}
      {:else if children}
        {@render children()}
      {/if}
    </span>
  {/if}
</span>

<style>
  .info-wrap {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .align-right { justify-content: flex-end; }
  /* Popup mode — wrap is positioned so the floating popout anchors
     to it. No flex-wrap (popup floats absolutely so it can never
     push siblings down into a new line). */
  .info-wrap-popup {
    position: relative;
    flex-wrap: nowrap;
  }

  .info-btn {
    width: 1.05rem;
    height: 1.05rem;
    border-radius: 9999px;
    border: 1px solid rgba(251,191,36,0.45);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
    font-size: 0.6rem;
    font-style: italic;
    font-weight: 700;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex: 0 0 auto;
    transition: background 0.12s, border-color 0.12s;
  }
  .info-btn:hover {
    background: rgba(251,191,36,0.22);
    border-color: rgba(251,191,36,0.7);
  }
  .info-btn.open {
    background: #fbbf24;
    color: #0c1830;
    border-color: #fbbf24;
  }

  /* Popover — same gradient + amber accent the Settings page row info
     uses, so the affordance is consistent across the algo surface. */
  .info-popout {
    display: inline-block;
    margin: 0;
    padding: 0.5rem 0.7rem;
    border-radius: 0.25rem;
    border: 1px solid rgba(251,191,36,0.35);
    border-left: 3px solid #fbbf24;
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    font-size: 0.7rem;
    color: #c8d8f0;
    line-height: 1.5;
    flex: 1 1 100%;
  }
  /* Popup variant — absolute-positioned so it floats above siblings
     instead of pushing them. Adds a drop-shadow so it reads as a
     tooltip layer, not part of the content flow. min-width keeps a
     tiny popup readable even when the content is short. */
  .info-popout-popup {
    position: absolute;
    top: calc(100% + 0.4rem);
    left: 0;
    z-index: 50;
    flex: none;
    width: max-content;
    min-width: 14rem;
    box-shadow: 0 6px 20px rgba(0,0,0,0.55);
  }
  .info-popout-pinned { pointer-events: auto; }

  /* Reset margins on common children so the popover content reads
     compactly without unintended padding. */
  :global(.info-popout p)  { margin: 0 0 0.4rem; }
  :global(.info-popout p:last-child) { margin-bottom: 0; }
  :global(.info-popout code),
  :global(.info-popout .font-mono) { color: #7dd3fc; }
  :global(.info-popout b),
  :global(.info-popout strong) { color: #fbbf24; font-weight: 700; }
</style>
