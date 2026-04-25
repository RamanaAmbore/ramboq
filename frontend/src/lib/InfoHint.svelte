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
   * }} */
  let {
    children,
    label = 'i',
    maxWidth = '36rem',
    align = 'left',
    defaultOpen = false,
  } = $props();

  let open = $state(defaultOpen);
</script>

<span class="info-wrap" class:align-right={align === 'right'}>
  <button type="button"
          class="info-btn"
          class:open
          aria-expanded={open}
          aria-label={open ? 'Hide details' : 'Show details'}
          title={open ? 'Hide details' : 'Show details'}
          onclick={() => open = !open}>{label}</button>
  {#if open}
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
  /* Reset margin on common children so the popover content reads
     compactly without the operator wondering about padding. */
  :global(.info-popout p)  { margin: 0 0 0.4rem; }
  :global(.info-popout p:last-child) { margin-bottom: 0; }
  :global(.info-popout code),
  :global(.info-popout .font-mono) { color: #7dd3fc; }
</style>
