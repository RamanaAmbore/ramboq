<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount, onDestroy } from 'svelte';
  import { authStore, visibleInterval } from '$lib/stores';
  import { fetchSimStatus } from '$lib/api';

  const { children } = $props();

  const bullSrc = "/bull.png";

  // All algo pages require admin
  $effect(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin');
    }
  });

  function isActive(/** @type {string} */ href) {
    // Longest-match semantics so sub-pages (e.g. /admin/tokens) don't light up
    // their parent (/admin) in the hamburger at the same time.
    const path = page.url.pathname;
    let bestHref = '';
    for (const link of algoLinks) {
      const h = link.href;
      if ((path === h || path.startsWith(h + '/')) && h.length > bestHref.length) {
        bestHref = h;
      }
    }
    return href === bestHref;
  }

  function signOut() {
    authStore.logout();
    goto('/about');
  }

  // Grouped by frequency of use: operational daily work first
  // (Dashboard / Agents / Orders), then tools (Terminal / Simulator),
  // then configuration (Tokens / Settings), then user admin last.
  const algoLinks = [
    { href: '/dashboard',        label: 'Dashboard' },
    { href: '/agents',           label: 'Agents'    },
    { href: '/orders',           label: 'Orders'    },
    { href: '/console',          label: 'Terminal'  },
    { href: '/admin/simulator',  label: 'Simulator' },
    { href: '/admin/tokens',     label: 'Tokens'    },
    { href: '/admin/settings',   label: 'Settings'  },
    { href: '/admin',            label: 'Users'     },
  ];

  let menuOpen = $state(false);
  const closeMenu = () => { menuOpen = false; };

  // ── Global simulator status ─────────────────────────────────────────
  // Polled every 4 seconds so the SIMULATOR banner appears/disappears on
  // every algo page without each page having to track status on its own.
  // Errors silently no-op — the capability flag may be off.
  let simStatus = $state(/** @type {any} */ ({ active: false }));
  let simTeardown;
  async function pollSim() {
    try { simStatus = await fetchSimStatus(); }
    catch (_) { /* cap flag off or auth gone — treat as idle */ }
  }
  onMount(() => {
    pollSim();
    simTeardown = visibleInterval(pollSim, 4000);
  });
  onDestroy(() => { simTeardown?.(); });
</script>

<!-- Algo-side favicon — a circled "algo" mark so the browser tab visually
     separates the trading-console tabs from the public marketing site. -->
<svelte:head>
  <link rel="icon" type="image/svg+xml" href="/algo-favicon.svg" />
</svelte:head>

<div class="algo-viewport">
  <div class="algo-card">
    <!-- Top bar -->
    <header class="algo-navbar">
      <div class="algo-nav-inner hidden md:flex items-center gap-1 h-12">
        <!-- Site label -->
        <button onclick={() => goto('/about')} class="algo-brand">
          <img src={bullSrc} alt="" class="algo-brand-bull" />
          <span class="algo-brand-name">RAMBO QUANT ANALYTICS LLP</span>
        </button>

        <nav class="flex items-center gap-0.5 flex-1">
          {#each algoLinks as link}
            <button
              onclick={() => goto(link.href)}
              class="algo-nav-btn {isActive(link.href) ? 'algo-nav-btn-active' : ''}"
            >{link.label}</button>
          {/each}
        </nav>

        <span class="algo-user-pill">
          {$authStore.user?.display_name?.toLowerCase() ?? ''}
          <span class="algo-user-role">admin</span>
        </span>
        <button onclick={signOut} class="algo-nav-btn">Sign Out</button>
        <button onclick={() => goto('/about')} class="algo-pub-link">↙ Site</button>
      </div>

      <!-- Mobile -->
      <div class="algo-nav-inner md:hidden flex items-center justify-between h-12">
        <button onclick={() => goto('/about')} class="algo-brand">
          <img src={bullSrc} alt="" class="algo-brand-bull algo-brand-bull-sm" />
          <span class="algo-brand-name">RAMBO QUANT ANALYTICS LLP</span>
        </button>
        <span class="algo-user-pill">
          {$authStore.user?.display_name?.toLowerCase() ?? ''}
          <span class="algo-user-role">admin</span>
        </span>
        <button
          onclick={() => menuOpen = !menuOpen}
          class="algo-hamburger"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
        >
          {#if menuOpen}
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          {:else}
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
          {/if}
        </button>
      </div>

      <!-- Mobile dropdown -->
      {#if menuOpen}
        <nav class="algo-mobile-dropdown">
          {#each algoLinks as link}
            <button
              onclick={() => { goto(link.href); closeMenu(); }}
              class="algo-mobile-item {isActive(link.href) ? 'algo-mobile-active' : ''}"
            >{link.label}</button>
          {/each}
          <button onclick={() => { goto('/about'); closeMenu(); }} class="algo-mobile-item algo-mobile-site">↙ Back to Site</button>
          <button onclick={() => { signOut(); closeMenu(); }} class="algo-mobile-item">Sign Out</button>
        </nav>
      {/if}
    </header>

    {#if simStatus?.active}
      <div class="sim-banner" role="status" aria-live="polite">
        <span class="sim-banner-dot"></span>
        <span class="sim-banner-label">SIMULATOR</span>
        <span class="sim-banner-sep">·</span>
        <span><b class="sim-banner-scenario">{simStatus.scenario || '—'}</b></span>
        {#if simStatus.seed_mode}
          <span class="sim-banner-sep">·</span>
          <span>seed {simStatus.seed_mode}</span>
        {/if}
        <span class="sim-banner-sep">·</span>
        <span>tick {simStatus.tick_index}/{simStatus.total_ticks}</span>
        {#if simStatus.only_agent_ids?.length}
          <span class="sim-banner-sep">·</span>
          <span>agents=[{simStatus.only_agent_ids.join(',')}]</span>
        {/if}
      </div>
    {/if}

    <main class="algo-content">
      {@render children()}
    </main>

    <footer class="algo-footer">
      <span class="algo-footer-text">RamboQuant Analytics</span>
      <span class="algo-footer-sep">·</span>
      <span class="algo-footer-text">ACU-5195</span>
      <span class="algo-footer-sep">·</span>
      <span class="algo-footer-text">Admin Console</span>
    </footer>
  </div>
</div>

<style>
  /* ── Algo viewport ─────────────────────────────────────────────────────── */
  .algo-viewport {
    min-height: 100vh;
    background-color: #080f1c;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .algo-card {
    width: 100%;
    max-width: 1440px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background-color: #0d1829;
    border-left:  1px solid #1e2d45;
    border-right: 1px solid #1e2d45;
  }

  /* ── Navbar ─────────────────────────────────────────────────────────────── */
  .algo-navbar {
    position: sticky;
    top: 0;
    z-index: 50;
    background: #0a1020;
    border-bottom: 1px solid #d97706;
    overflow: visible;
  }

  .algo-nav-inner {
    max-width: 1440px;
    margin: 0 auto;
    padding: 0 1rem;
  }

  /* Brand mark */
  .algo-brand {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.1rem 0.5rem 0.1rem 0;
    margin-right: 0.75rem;
    outline: none !important;
  }
  .algo-brand-name {
    font-size: 0.72rem;
    font-weight: 800;
    color: #fbbf24;
    letter-spacing: 0.08em;
    font-family: ui-monospace, monospace;
    line-height: 1;
  }
  /* Plain bull — no circle / wordmark decoration. The amber drop-shadow
     keeps it matching the public-site brand. */
  .algo-brand-bull {
    height: 1.2rem;
    width: auto;
    display: block;
    filter: drop-shadow(0 0 3px rgba(251,191,36,0.75))
            drop-shadow(0 0 6px rgba(251,191,36,0.45));
  }
  .algo-brand-bull-sm { height: 1rem; }


  /* Nav buttons */
  :global(.algo-nav-btn) {
    padding: 0.22rem 0.6rem 0.22rem calc(0.6rem - 2px);
    font-size: 0.68rem;
    font-weight: 500;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(180, 200, 230, 0.75);
    border: none;
    border-left: 2px solid transparent;
    cursor: pointer;
    letter-spacing: 0.03em;
    font-family: ui-monospace, monospace;
    transition: background-color 0.06s, color 0.06s, border-left-color 0.06s;
    white-space: nowrap;
    outline: none !important;
    -webkit-tap-highlight-color: transparent;
  }
  :global(.algo-nav-btn:hover) {
    background: rgba(251,191,36,0.1);
    color: #fbbf24;
    border-left-color: #fbbf24;
  }
  :global(.algo-nav-btn-active) {
    background: rgba(251,191,36,0.15);
    color: #fbbf24;
    font-weight: 700;
    border-left-color: #fbbf24;
  }

  /* Back-to-site link */
  .algo-pub-link {
    padding: 0.18rem 0.5rem;
    font-size: 0.62rem;
    font-weight: 500;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(150,170,200,0.5);
    border: 1px solid rgba(150,170,200,0.15);
    cursor: pointer;
    font-family: ui-monospace, monospace;
    transition: color 0.06s, border-color 0.06s;
    outline: none !important;
    margin-left: 0.5rem;
  }
  .algo-pub-link:hover { color: rgba(150,170,200,0.85); border-color: rgba(150,170,200,0.35); }

  /* User pill */
  .algo-user-pill {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    font-weight: 500;
    color: #c8d8f0;
    padding: 0.18rem 0.5rem;
    border-radius: 3px;
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    border: 1px solid rgba(255,255,255,0.1);
    margin-right: 0.25rem;
    white-space: nowrap;
    font-family: ui-monospace, monospace;
  }
  .algo-user-role {
    font-size: 0.5rem;
    color: #fbbf24;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  /* Hamburger */
  .algo-hamburger {
    padding: 0.3rem;
    border-radius: 0.2rem;
    background: transparent;
    color: rgba(180,200,230,0.8);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    transition: background-color 0.06s;
    outline: none !important;
  }
  .algo-hamburger:hover { background: rgba(251,191,36,0.12); }

  /* Mobile dropdown */
  .algo-mobile-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 49;
    background: #0a1020;
    border-top: 1px solid rgba(251,191,36,0.2);
    border-bottom: 1px solid rgba(251,191,36,0.2);
    box-shadow: 0 8px 20px rgba(0,0,0,0.5);
  }
  .algo-mobile-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.65rem 1.25rem;
    font-size: 0.85rem;
    font-weight: 500;
    color: rgba(180,200,230,0.8);
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    cursor: pointer;
    font-family: ui-monospace, monospace;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .algo-mobile-item:last-child { border-bottom: none; }
  .algo-mobile-item:hover { background: rgba(251,191,36,0.1); color: #fbbf24; }
  .algo-mobile-active { color: #fbbf24; background: rgba(251,191,36,0.1); }
  .algo-mobile-site { color: rgba(150,170,200,0.5); font-size: 0.75rem; }

  /* ── Simulator banner — pinned under the nav when sim is active ──────────
     Opaque background (solid over a tinted overlay) so page content
     scrolling underneath never bleeds through. Compact padding so it
     steals minimum vertical space. */
  .sim-banner {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.2rem 0.85rem;
    background-color: #0a1020;   /* solid under the tint — prevents bleed */
    background-image: linear-gradient(90deg,
                      rgba(251,113,133,0.22) 0%,
                      rgba(251,191,36,0.22) 100%);
    border-top: 1px solid rgba(251,113,133,0.45);
    border-bottom: 1px solid rgba(251,113,133,0.45);
    color: #fecaca;
    font-family: ui-monospace, monospace;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    position: sticky;
    top: 3rem;                  /* sits just under the algo navbar */
    z-index: 49;
    animation: sim-banner-pulse 2.2s ease-in-out infinite;
  }
  .sim-banner-dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: #fb7185;
    box-shadow: 0 0 5px rgba(251,113,133,0.85);
    flex-shrink: 0;
  }
  .sim-banner-label {
    color: #fbbf24;
    letter-spacing: 0.1em;
    font-size: 0.6rem;
    font-weight: 800;
  }
  .sim-banner-sep { color: rgba(251,191,36,0.5); }
  .sim-banner-scenario { color: #fde68a; }
  @keyframes sim-banner-pulse {
    0%, 100% { box-shadow: inset 0 0 0 0 rgba(251,113,133,0);   }
    50%      { box-shadow: inset 0 0 10px 0 rgba(251,113,133,0.30); }
  }

  /* ── Content ─────────────────────────────────────────────────────────────── */
  .algo-content {
    flex: 1;
    padding: 1rem 1rem 1.5rem;
    color: #c8d8f0;
  }

  /* ── Footer ─────────────────────────────────────────────────────────────── */
  .algo-footer {
    background: #0a1020;
    border-top: 1px solid rgba(251,191,36,0.2);
    height: 1.6rem;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    padding: 0 1rem;
  }
  .algo-footer-text { font-size: 0.6rem; color: rgba(160,185,220,0.7); font-family: ui-monospace, monospace; }
  .algo-footer-sep  { font-size: 0.6rem; color: rgba(251,191,36,0.6); margin: 0 0.4rem; }

  /* Visible scrollbars on algo pages. Default browser scrollbars on
     dark themes are so low-contrast they're easy to miss when content
     overflows; colouring the thumb in the site's amber makes "there is
     more below" obvious at a glance. Firefox uses `scrollbar-color`;
     WebKit/Blink use the pseudo-elements. Idle state is faint, hover is
     bright so moving the mouse near the bar lights it up. */
  :global(.algo-viewport),
  :global(.algo-viewport *),
  :global(.algo-content *) {
    scrollbar-color: rgba(251,191,36,0.45) rgba(148,163,184,0.08);
    scrollbar-width: thin;
  }
  :global(.algo-viewport ::-webkit-scrollbar),
  :global(.algo-content ::-webkit-scrollbar) {
    width: 10px;
    height: 10px;
  }
  :global(.algo-viewport ::-webkit-scrollbar-track),
  :global(.algo-content ::-webkit-scrollbar-track) {
    background: rgba(148,163,184,0.06);
  }
  :global(.algo-viewport ::-webkit-scrollbar-thumb),
  :global(.algo-content ::-webkit-scrollbar-thumb) {
    background: rgba(251,191,36,0.45);
    border-radius: 5px;
    border: 2px solid transparent;
    background-clip: padding-box;
  }
  :global(.algo-viewport ::-webkit-scrollbar-thumb:hover),
  :global(.algo-content ::-webkit-scrollbar-thumb:hover) {
    background: #fbbf24;
    background-clip: padding-box;
  }

  /* Page-top header row — H1 on the left, timestamp right-aligned on
     the same line to conserve vertical space. Wraps to its own line on
     narrow widths. Used by every admin page via `.page-header`. */
  :global(.page-header) {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }
  /* Every algo page gets the full-width amber underline that dashboard
     already had — keeps the headline visually separated from the
     content cards below without crowding the title chip itself. */
  :global(.algo-content .page-header) {
    border-bottom: 1px solid rgba(251,191,36,0.25);
    padding-bottom: 0.35rem;
    margin-bottom: 1rem;
  }

  /* Page-level timestamp (cyan, matches log timestamps). Works inline
     inside .page-header OR stand-alone when a page renders it on its
     own row (left over on public pages). */
  :global(.algo-ts) {
    font-size: 0.62rem;
    color: #fde047;
    font-family: ui-monospace, monospace;
    white-space: nowrap;
  }

  /* Algo dark-theme overrides for classes shared with public pages */
  :global(.algo-content .text-muted) { color: #7e97b8; }
  :global(.algo-content .field-label) { color: #7e97b8; }
  :global(.algo-content .field-input) {
    background: #152033;
    border-color: rgba(255,255,255,0.12);
    color: #e2e8f0;
    color-scheme: dark;
    accent-color: #fbbf24;
  }
  :global(.algo-content .field-input:focus) { border-color: #fbbf24 !important; }

  /* .field-input sets border-color shorthand which overwrites the amber
     left rule shipped with .cmd-input — restore it inside algo pages so
     the Terminal textarea and any other cmd-input surface keep the
     Bloomberg-style amber accent that the Orders command bar uses. */
  :global(.algo-content .cmd-input) {
    border-left: 3px solid #fbbf24 !important;
  }
  :global(.algo-content .cmd-input:focus) {
    border-left-color: #fbbf24 !important;
  }

  /* .cmd-surface: mirrors the Orders command-bar amber left accent onto
     any entry/form card so the user knows at a glance "this is where
     input goes". Applied to the Simulator's control card; can be added
     to future form surfaces as-is. */
  :global(.algo-content .cmd-surface) {
    border-left: 3px solid #fbbf24 !important;
  }

  /* .sim-btn-order: compact modifier for places where the sim-btn
     palette is reused outside the Simulator's grow-to-fill row. Drops
     the flex grow/basis so the button sizes to its content (e.g. the
     Submit/BUY/SELL/Clear cluster on the Orders page). */
  :global(.sim-btn.sim-btn-order) {
    flex: 0 0 auto;
    max-width: none;
    padding: 0.3rem 0.9rem;
  }

  /* <select> element + dropdown popup — matches the OrderPopup modal's
     palette (linear-gradient(#273552 → #1d2a44) + amber accent border).
     Native browsers render the option list as OS chrome, but setting
     background-color + color on <option> is honoured by Chromium + FF,
     so the dropdown reads as a continuation of the OrderPopup instead
     of a foreign OS widget. */
  :global(.algo-content select.field-input) {
    background-image: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    background-color: #1d2a44;
    border-color: rgba(251,191,36,0.25);
  }
  :global(.algo-content select.field-input:hover) {
    border-color: rgba(251,191,36,0.5);
  }
  :global(.algo-content select.field-input option),
  :global(.algo-content select option) {
    background-color: #1d2a44;
    color: #e2e8f0;
    padding: 0.35rem 0.5rem;
  }
  :global(.algo-content select.field-input option:checked),
  :global(.algo-content select option:checked) {
    background-color: #273552;
    color: #fbbf24;
    font-weight: 700;
  }
  :global(.algo-content select.field-input option:hover),
  :global(.algo-content select option:hover) {
    background-color: rgba(251,191,36,0.15);
    color: #fbbf24;
  }
  :global(.algo-content .section-heading) { color: #fbbf24; }
  :global(.algo-content .page-title-chip) {
    color: #fbbf24;
    border-bottom: none;
    padding-bottom: 0;
  }
  :global(.algo-content .btn-secondary) {
    color: #c8d8f0;
    border-color: rgba(255,255,255,0.2);
    background: transparent;
  }
  :global(.algo-content .btn-secondary:hover:not(:disabled)) {
    background: rgba(251,191,36,0.1);
    border-color: rgba(251,191,36,0.5);
    color: #fbbf24;
  }
  :global(.algo-content .btn-tertiary) { color: #c8d8f0; }
  :global(.algo-content .btn-tertiary:hover) { background: rgba(251,191,36,0.1); color: #fbbf24; }
  :global(.algo-content .btn-tertiary.active) { color: #fbbf24; background: rgba(251,191,36,0.15); }

  /* ── Status-driven surface card — used across algo pages ─────────────────── */
  :global(.algo-status-card) {
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    border: 1.5px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 0.75rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.08);
    color: #c8d8f0;
    transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
  }
  :global(.algo-status-card[data-status="active"]) {
    border-color: rgba(34,197,94,0.6);
    box-shadow: 0 2px 8px rgba(0,0,0,0.45), 0 0 0 1px rgba(34,197,94,0.18);
  }
  :global(.algo-status-card[data-status="inactive"]) {
    border-color: rgba(180,200,230,0.18);
    opacity: 0.82;
  }
  :global(.algo-status-card[data-status="triggered"]) {
    border-color: rgba(239,68,68,0.75);
    box-shadow: 0 2px 8px rgba(0,0,0,0.45), 0 0 0 1px rgba(239,68,68,0.22);
  }
  :global(.algo-status-card[data-status="running"]) {
    border-color: rgba(251,191,36,0.65);
    box-shadow: 0 2px 8px rgba(0,0,0,0.45), 0 0 0 1px rgba(251,191,36,0.18);
  }
  :global(.algo-status-card[data-status="cooldown"]) {
    border-color: rgba(251,191,36,0.4);
  }
  :global(.algo-status-card[data-status="error"]) {
    border-color: rgba(220,38,38,0.85);
    box-shadow: 0 2px 8px rgba(0,0,0,0.45), 0 0 0 1px rgba(220,38,38,0.28);
  }
</style>
