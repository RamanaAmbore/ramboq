<script>
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { authStore } from '$lib/stores';

  const { children } = $props();

  // Portfolio page requires sign-in (any role)
  $effect(() => {
    const path = page.url.pathname;
    if (path.startsWith('/portfolio')) {
      if (!$authStore.user) goto('/signin');
    }
  });

  function isActive(/** @type {string} */ href) {
    return page.url.pathname.startsWith(href);
  }

  function signOut() {
    authStore.logout();
    goto('/about');
  }

  const baseLinks = [
    { href: '/about',       label: 'About'       },
    { href: '/market',      label: 'Market'      },
    { href: '/performance', label: 'Performance' },
    { href: '/faq',         label: 'FAQ'         },
    { href: '/post',        label: 'Insights'    },
    { href: '/contact',     label: 'Contact'     },
  ];

  const partnerLinks = [
    { href: '/portfolio', label: 'Portfolio' },
  ];

  function navLinks(user) {
    if (!user) return baseLinks;
    return [...baseLinks, ...partnerLinks];
  }

  let menuOpen = $state(false);
  const closeMenu = () => { menuOpen = false; };
</script>

<div class="pub-viewport">
  <div class="pub-accent-top"></div>

  <div class="pub-card">
    <!-- Desktop navbar -->
    <header class="pub-navbar">
      <div class="pub-nav-inner hidden md:flex items-center gap-1 h-14">
        <a href="/about" class="shrink-0 mr-5" tabindex="-1">
          <img src="/logo.png" alt="RamboQuant Analytics LLP" class="h-9 w-auto pointer-events-none" />
        </a>

        <nav class="flex items-center gap-0.5 flex-1">
          {#each navLinks($authStore.user) as link}
            <button
              onclick={() => goto(link.href)}
              class="pub-nav-btn {isActive(link.href) ? 'pub-nav-btn-active' : ''}"
            >{link.label}</button>
          {/each}
        </nav>

        {#if $authStore.user?.role === 'admin'}
          <button onclick={() => goto('/dashboard')} class="pub-nav-algo-btn">
            Algo ↗
          </button>
        {/if}

        {#if $authStore.user}
          <span class="pub-user-pill">
            {$authStore.user.display_name.toLowerCase()}
          </span>
          <button onclick={signOut} class="pub-nav-btn">Sign Out</button>
        {:else}
          <button onclick={() => goto('/signin')} class="pub-nav-signin {isActive('/signin') ? 'pub-nav-btn-active' : ''}">Sign In</button>
        {/if}
      </div>

      <!-- Mobile bar -->
      <div class="pub-nav-inner md:hidden flex items-center justify-between h-16 py-2">
        <a href="/about" class="shrink-0" tabindex="-1">
          <img src="/logo.png" alt="RamboQuant Analytics LLP" class="h-12 w-auto pointer-events-none" />
        </a>
        <div class="flex items-center gap-2">
          {#if $authStore.user}
            <span class="pub-user-pill text-[0.6rem]">
              {$authStore.user.display_name.toLowerCase()}
            </span>
          {/if}
          <button
            onclick={() => menuOpen = !menuOpen}
            class="pub-hamburger"
            aria-label="Toggle menu"
            aria-expanded={menuOpen}
          >
            {#if menuOpen}
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            {:else}
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 6h16M4 12h16M4 18h16"/>
              </svg>
            {/if}
          </button>
        </div>
      </div>

      <!-- Mobile dropdown -->
      {#if menuOpen}
        <nav class="pub-mobile-dropdown">
          {#each navLinks($authStore.user) as link}
            <button
              onclick={() => { goto(link.href); closeMenu(); }}
              class="pub-mobile-item {isActive(link.href) ? 'pub-mobile-active' : ''}"
            >{link.label}</button>
          {/each}
          {#if $authStore.user?.role === 'admin'}
            <button
              onclick={() => { goto('/dashboard'); closeMenu(); }}
              class="pub-mobile-item pub-mobile-algo"
            >Algo Dashboard ↗</button>
          {/if}
          {#if $authStore.user}
            <button onclick={() => { signOut(); closeMenu(); }} class="pub-mobile-item">Sign Out</button>
          {:else}
            <button onclick={() => { goto('/signin'); closeMenu(); }} class="pub-mobile-item">Sign In</button>
          {/if}
        </nav>
      {/if}
    </header>

    <main class="pub-content">
      {@render children()}
    </main>

    <footer class="pub-footer">
      <p class="hidden md:block text-center leading-none pub-footer-text">
        © RamboQuant Analytics LLP
        <span class="pub-sep">|</span>
        ACU-5195
        <span class="pub-sep">|</span>
        Disclaimer: Investment in markets is subject to risk. Past performance is not indicative of future results.
      </p>
      <p class="md:hidden text-center leading-none pub-footer-text">
        © RamboQuant Analytics LLP
        <span class="pub-sep">|</span>
        ACU-5195
        <span class="pub-sep">|</span>
        Markets carry risk.
      </p>
    </footer>
  </div>

  <div class="pub-accent-bottom"></div>
</div>

<style>
  /* ── Viewport / card shell ─────────────────────────────────────────────── */
  .pub-viewport {
    min-height: 100vh;
    background-color: #dde2e8;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .pub-accent-top, .pub-accent-bottom {
    position: fixed;
    height: 3px;
    z-index: 200;
    max-width: 958px;
    width: 100%;
    left: 50%;
    transform: translateX(-50%);
    background: linear-gradient(90deg, #1a2744 0%, #b8830a 40%, #c9940f 60%, #1a2744 100%);
  }
  .pub-accent-top    { top: 0; }
  .pub-accent-bottom { bottom: 0; }
  @media (max-width: 767px) {
    .pub-accent-top { height: 4px; }
  }

  .pub-card {
    width: 100%;
    max-width: 960px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background-color: #f8f9fb;
    border-left:  1px solid #c8cdd6;
    border-right: 1px solid #c8cdd6;
    box-shadow: -2px 0 6px rgba(0,0,0,0.12), 2px 0 6px rgba(0,0,0,0.12);
    margin-top: 3px;
    margin-bottom: 3px;
  }

  /* ── Navbar ─────────────────────────────────────────────────────────────── */
  .pub-navbar {
    position: sticky;
    top: 3px;
    z-index: 50;
    background: linear-gradient(160deg, #1a2744 0%, #1e3a5f 55%, #152038 100%);
    border-bottom: 2px solid #b8830a;
    overflow: visible;
  }

  .pub-nav-inner {
    max-width: 960px;
    margin: 0 auto;
    padding: 0 1rem;
  }

  /* Nav buttons */
  :global(.pub-nav-btn) {
    padding: 0.25rem 0.65rem;
    font-size: 0.7rem;
    font-weight: 500;
    border-radius: 0.25rem;
    background: transparent;
    color: rgba(220, 230, 245, 0.85);
    border: none;
    cursor: pointer;
    letter-spacing: 0.02em;
    transition: background-color 0.08s, color 0.08s;
    white-space: nowrap;
    outline: none !important;
    -webkit-tap-highlight-color: transparent;
    text-shadow: 0 1px 3px rgba(0,0,0,0.5);
  }
  :global(.pub-nav-btn:hover) { background: rgba(255,255,255,0.10); color: #fff; }
  :global(.pub-nav-btn-active) { background: rgba(184,131,10,0.22); color: #f0c060; font-weight: 600; }

  /* Algo link — stands apart with gold border */
  .pub-nav-algo-btn {
    padding: 0.2rem 0.6rem;
    font-size: 0.65rem;
    font-weight: 600;
    border-radius: 0.25rem;
    background: rgba(184,131,10,0.15);
    color: #f0c060;
    border: 1px solid rgba(184,131,10,0.4);
    cursor: pointer;
    letter-spacing: 0.03em;
    transition: background-color 0.08s;
    outline: none !important;
    white-space: nowrap;
    margin-right: 0.25rem;
  }
  .pub-nav-algo-btn:hover { background: rgba(184,131,10,0.28); }

  /* Sign-in button */
  .pub-nav-signin {
    padding: 0.22rem 0.75rem;
    font-size: 0.7rem;
    font-weight: 600;
    border-radius: 0.25rem;
    background: rgba(184,131,10,0.2);
    color: #f0c060;
    border: 1px solid rgba(184,131,10,0.45);
    cursor: pointer;
    transition: background-color 0.08s;
    outline: none !important;
    white-space: nowrap;
    text-shadow: 0 1px 2px rgba(0,0,0,0.4);
  }
  .pub-nav-signin:hover { background: rgba(184,131,10,0.32); color: #fff; }

  /* User pill */
  .pub-user-pill {
    font-size: 0.72rem;
    font-weight: 500;
    color: rgba(210, 225, 245, 0.7);
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    margin-right: 0.2rem;
    white-space: nowrap;
  }

  /* Hamburger */
  .pub-hamburger {
    padding: 0.35rem;
    border-radius: 0.25rem;
    background: transparent;
    color: rgba(220,230,245,0.9);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.08s;
    outline: none !important;
  }
  .pub-hamburger:hover { background: rgba(255,255,255,0.12); }

  /* Mobile dropdown */
  .pub-mobile-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 49;
    background: linear-gradient(180deg, #1e3060 0%, #162040 100%);
    border-top: 1px solid rgba(184,131,10,0.3);
    box-shadow: 0 6px 16px rgba(0,0,0,0.35);
  }
  .pub-mobile-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.65rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: rgba(210,225,245,0.85);
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    cursor: pointer;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .pub-mobile-item:last-child { border-bottom: none; }
  .pub-mobile-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
  .pub-mobile-active { color: #f0c060; background: rgba(184,131,10,0.12); }
  .pub-mobile-algo { color: #f0c060; font-weight: 600; letter-spacing: 0.02em; }

  /* ── Content + footer ────────────────────────────────────────────────────── */
  .pub-content {
    flex: 1;
    padding: 1rem 1rem 1.5rem;
  }

  .pub-footer {
    position: sticky;
    bottom: 3px;
    z-index: 40;
    background: linear-gradient(160deg, #1a2744 0%, #1e3a5f 55%, #152038 100%);
    border-top: 1px solid rgba(184,131,10,0.25);
    height: 1.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 0.75rem;
  }
  .pub-footer p { width: 100%; }
  .pub-footer-text { color: rgba(200,215,240,0.75); font-size: 0.65rem; line-height: 1; }
  .pub-sep { color: #b8830a; font-weight: bold; margin: 0 0.35rem; }
</style>
