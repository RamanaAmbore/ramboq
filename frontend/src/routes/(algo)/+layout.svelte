<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { authStore } from '$lib/stores';

  const { children } = $props();

  const bullSrc = "/bull.png";

  // All algo pages require admin
  $effect(() => {
    if (!$authStore.user || $authStore.user.role !== 'admin') {
      goto('/signin');
    }
  });

  function isActive(/** @type {string} */ href) {
    return page.url.pathname.startsWith(href);
  }

  function signOut() {
    authStore.logout();
    goto('/about');
  }

  const algoLinks = [
    { href: '/dashboard', label: 'Dashboard' },
    { href: '/console',   label: 'Terminal'  },
    { href: '/algo',      label: 'AI Agents' },
    { href: '/orders',    label: 'Orders'    },
    { href: '/admin',     label: 'Users'     },
  ];

  let menuOpen = $state(false);
  const closeMenu = () => { menuOpen = false; };
</script>

<div class="algo-viewport">
  <div class="algo-card">
    <!-- Top bar -->
    <header class="algo-navbar">
      <div class="algo-nav-inner hidden md:flex items-center gap-1 h-12">
        <!-- Site label -->
        <button onclick={() => goto('/about')} class="algo-brand">
          <img src={bullSrc} alt="" style="height:1.2rem;width:auto;display:block;filter:drop-shadow(0 0 3px rgba(251,191,36,0.75)) drop-shadow(0 0 6px rgba(251,191,36,0.45));" />
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
          <img src={bullSrc} alt="" style="height:1.0rem;width:auto;display:block;filter:drop-shadow(0 0 3px rgba(251,191,36,0.75)) drop-shadow(0 0 6px rgba(251,191,36,0.45));" />
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

  /* Page-level timestamp line (cyan, matches log timestamps) */
  :global(.algo-ts) {
    font-size: 0.65rem;
    color: #7dd3fc;
    margin-bottom: 0.25rem;
    font-family: ui-monospace, monospace;
  }

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
