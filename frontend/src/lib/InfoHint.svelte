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
  /** @type {HTMLSpanElement | undefined} */
  let popoutEl = $state();

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

  // Viewport-bound the popup — once it's mounted, measure its
  // bounding rect; if either edge clips outside the viewport, shift
  // it horizontally so it sits fully inside. Re-runs whenever the
  // popup opens (or the window resizes while it's open).
  $effect(() => {
    if (!popup || !visible || !popoutEl || typeof window === 'undefined') return;
    /** @type {number} */ let raf;
    function fit() {
      if (!popoutEl) return;
      // Reset before measuring so the previous nudge doesn't bias the
      // calculation (otherwise the popup snaps further every open).
      popoutEl.style.transform = '';
      const r = popoutEl.getBoundingClientRect();
      const margin = 8;
      const vw = window.innerWidth;
      let dx = 0;
      if (r.right > vw - margin)  dx -= (r.right - (vw - margin));
      if (r.left + dx < margin)   dx += (margin - (r.left + dx));
      popoutEl.style.transform = dx ? `translateX(${dx}px)` : '';
    }
    raf = requestAnimationFrame(fit);
    window.addEventListener('resize', fit);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', fit);
    };
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
  {#if visible}
    <span class="info-popout"
          class:info-popout-popup={popup}
          class:info-popout-pinned={popup && open}
          style="max-width: {maxWidth}"
          bind:this={popoutEl}>
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

  /* Chip — subtle and small. Earlier iterations were a saturated
     amber pill; toned down to slate-blue at low alpha so the chip
     reads as "supplemental info available" without competing with
     the labels it sits next to. The amber accent only appears on
     hover / open so the chip lights up when intentionally invoked. */
  .info-btn {
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 9999px;
    border: 1px solid rgba(125,151,184,0.35);
    background: rgba(125,151,184,0.08);
    color: #7e97b8;
    font-size: 0.5rem;
    font-style: italic;
    font-weight: 600;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex: 0 0 auto;
    transition: background 0.12s, border-color 0.12s, color 0.12s;
  }
  .info-btn:hover {
    background: rgba(251,191,36,0.14);
    border-color: rgba(251,191,36,0.5);
    color: #fbbf24;
  }
  .info-btn.open {
    background: rgba(251,191,36,0.22);
    color: #fbbf24;
    border-color: rgba(251,191,36,0.6);
  }

  /* Popover — subtle dark-blue surface with a soft border. Earlier
     iterations used a gradient + amber-accent left border; the
     accent shouted louder than the helper text it was framing. The
     subtler look is a flat slate background, faint blue-grey border,
     no left accent, and softer body type. Bold spans inside (b /
     strong) keep amber so the information hierarchy is preserved. */
  .info-popout {
    display: inline-block;
    margin: 0;
    padding: 0.5rem 0.7rem;
    border-radius: 0.3rem;
    border: 1px solid rgba(125,211,252,0.18);
    background: rgba(15, 25, 45, 0.95);
    font-size: 0.72rem;
    color: #c8d8f0;
    line-height: 1.5;
    flex: 1 1 100%;
  }
  /* Popup variant — absolute-positioned so it floats above siblings
     instead of pushing them. Width caps tightly to the viewport so
     a popup never overflows on a narrow phone (`min(20rem, calc(100vw
     - 1rem))` leaves at least 0.5 rem on each edge); JS in the
     component nudges the popup horizontally after open so even a
     chip near the right edge keeps the popup fully on-screen. */
  .info-popout-popup {
    position: absolute;
    top: calc(100% + 0.4rem);
    left: 0;
    z-index: 50;
    flex: none;
    width: max-content;
    min-width: min(12rem, calc(100vw - 1rem));
    max-width: min(20rem, calc(100vw - 1rem));
    box-shadow: 0 4px 14px rgba(0,0,0,0.45);
  }
  /* Right-aligned variant — flips the popup to anchor on the right
     edge of its trigger. Used when the chip sits at the right side
     of a row and a left-anchored popup would clip off-screen. */
  .info-wrap-popup.align-right .info-popout-popup {
    left: auto;
    right: 0;
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
