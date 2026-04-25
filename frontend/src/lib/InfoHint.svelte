<script>
  // Compact (i) chip → click to toggle an inline popover with the
  // explanatory text. Replaces the verbose top-of-page paragraphs that
  // were eating screen real estate on every algo admin page. Same
  // amber palette as the Settings page's row-level info chips so the
  // affordance reads as a familiar "tell me more" signal.
  //
  // Usage:
  //   <InfoHint>
  //     Some helpful text. Can include <b>HTML</b> and Svelte snippets.
  //   </InfoHint>
  //
  // The popover renders inline (not absolutely positioned) so layout
  // never overlaps unexpected things and mobile viewports work fine.

  /** @type {{
   *   children?: any,
   *   label?: string,
   *   maxWidth?: string,
   *   align?: 'left'|'right',
   *   defaultOpen?: boolean,
   *   popup?: boolean,
   * }} */
  let {
    children,
    label = 'i',
    maxWidth = '36rem',
    align = 'left',
    defaultOpen = false,
    // popup=false (default): inline expansion below the chip — best for
    //   page-level hints where a sliding card doesn't disrupt layout.
    // popup=true: floating absolute-positioned tooltip — best for compact
    //   stats (Greeks tables, risk metrics) where pushing siblings down
    //   would feel disruptive. Click chip to toggle, click outside to
    //   close. Hovering also triggers a soft preview.
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
  {#if popup}
    {#if open || hovered}
      <span class="info-popout info-popout-popup"
            class:info-popout-pinned={open}
            style="max-width: {maxWidth}">
        {#if children}{@render children()}{/if}
      </span>
    {/if}
  {:else if open}
    <span class="info-popout" style="max-width: {maxWidth}">
      {#if children}{@render children()}{/if}
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
  /* Popup mode — wrap is positioned so the floating popout anchors to
     it. No flex-wrap (popup floats absolutely so it can never push
     siblings down into a new line). */
  .info-wrap-popup {
    position: relative;
    flex-wrap: nowrap;
  }

  .info-btn {
    width: 1.05rem;
    height: 1.05rem;
    border-radius: 9999px;
    border: 1px solid rgba(251,191,36,0.35);
    background: rgba(251,191,36,0.08);
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
    background: rgba(251,191,36,0.18);
    border-color: rgba(251,191,36,0.6);
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
    padding: 0.45rem 0.65rem;
    border-radius: 0.25rem;
    border: 1px solid rgba(251,191,36,0.25);
    border-left: 3px solid #fbbf24;
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    font-size: 0.65rem;
    color: #c8d8f0;
    line-height: 1.5;
    flex: 1 1 100%;
  }
  /* Popup variant — absolute-positioned so it floats above siblings
     instead of pushing them. Drops a small drop-shadow so it reads as
     a tooltip layer, not part of the content flow. */
  .info-popout-popup {
    position: absolute;
    top: calc(100% + 0.4rem);
    left: -0.3rem;
    z-index: 30;
    flex: none;
    width: max-content;
    box-shadow: 0 4px 14px rgba(0,0,0,0.45);
    pointer-events: none;
  }
  /* When pinned (toggled open with click), allow pointer events so
     the operator can copy text from the popup. */
  .info-popout-pinned { pointer-events: auto; }
  /* Reset margin on common children so the popover content reads
     compactly without the operator wondering about padding. */
  :global(.info-popout p)  { margin: 0 0 0.4rem; }
  :global(.info-popout p:last-child) { margin-bottom: 0; }
  :global(.info-popout code),
  :global(.info-popout .font-mono) { color: #7dd3fc; }
</style>
