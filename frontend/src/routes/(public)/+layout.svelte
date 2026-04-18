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
        <a href="/about" class="pub-brand shrink-0 mr-5" tabindex="-1">
          <img src="/bull.png" alt="" class="pub-brand-bull pointer-events-none" />
          <div class="pub-brand-text">
            <span class="pub-brand-name">RAMBO QUANT</span>
            <span class="pub-brand-sub">ANALYTICS LLP</span>
            <span class="pub-brand-tagline">INVEST · GROW · COMPOUND</span>
          </div>
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
        <a href="/about" class="pub-brand pub-brand-mobile" tabindex="-1">
          <img src="/bull.png" alt="" class="pub-brand-bull pointer-events-none" />
          <div class="pub-brand-text">
            <span class="pub-brand-name">RAMBO QUANT</span>
            <span class="pub-brand-sub">ANALYTICS LLP</span>
            <span class="pub-brand-tagline">INVEST · GROW · COMPOUND</span>
          </div>
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
  /*
   * ── Investor palette: Deep Navy + Champagne Gold ───────────────────────────
   *   Navy primary:    #0c1830   navbar, footer, grid headers
   *   Champagne gold:  #c8a84b   accents, borders, active states
   *   Gold bright:     #e8c86a   text on dark, brand name
   *   Page bg:         #f0ece3   warm cream — premium feel
   *   Card bg:         #faf7f0   warm white
   *   Body text:       #1a1e35   near-black navy
   */

  /* ── Viewport / card shell ─────────────────────────────────────────────── */
  .pub-viewport {
    min-height: 100vh;
    background-color: #b8bcc8;
    background-image: repeating-linear-gradient(
      135deg,
      transparent,
      transparent 40px,
      rgba(255,255,255,0.05) 40px,
      rgba(255,255,255,0.05) 41px
    );
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .pub-accent-top, .pub-accent-bottom {
    position: fixed;
    height: 4px;
    z-index: 200;
    max-width: 958px;
    width: 100%;
    left: 50%;
    transform: translateX(-50%);
    background: linear-gradient(90deg, #0c1830 0%, #c8a84b 30%, #f0d878 50%, #c8a84b 70%, #0c1830 100%);
  }
  .pub-accent-top    { top: 0; }
  .pub-accent-bottom { bottom: 0; }
  @media (max-width: 767px) {
    .pub-accent-top { height: 5px; }
  }

  .pub-card {
    width: 100%;
    max-width: 960px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background-color: #faf7f0;
    border-left:  none;
    border-right: none;
    box-shadow: -4px 0 14px rgba(0,0,0,0.22), 4px 0 14px rgba(0,0,0,0.22);
    margin-top: 4px;
    margin-bottom: 4px;
    position: relative;
  }

  /* ── Navbar ─────────────────────────────────────────────────────────────── */
  .pub-navbar {
    position: sticky;
    top: 4px;
    z-index: 50;
    background-color: #0c1830;
    background-image:
      linear-gradient(rgba(8,14,30,0.78), rgba(8,14,30,0.78)),
      url('/nav_image.png');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    border-bottom: 2px solid #c8a84b;
    overflow: visible;
  }

  .pub-nav-inner {
    max-width: 960px;
    margin: 0 auto;
    padding: 0 1rem;
  }

  /* ── Brand text logo ────────────────────────────────────────────────────── */
  .pub-brand {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.55rem;
    text-decoration: none;
    line-height: 1;
    margin-right: 1rem;
  }
  .pub-brand-bull {
    height: 2.6rem;
    width: auto;
    object-fit: contain;
    display: block;
    filter:
      brightness(0) invert(1)
      sepia(55%) saturate(2.5) hue-rotate(5deg) brightness(0.92)
      drop-shadow(0 1px 3px rgba(0,0,0,0.45));
  }
  .pub-brand-text {
    display: flex;
    flex-direction: column;
    gap: 0.09rem;
    padding: 0.1rem 0 0.1rem 0.6rem;
    border-left: 2px solid #c8a84b;
  }
  .pub-brand-name {
    font-size: 1.08rem;
    font-weight: 900;
    color: #ffffff;
    letter-spacing: 0.06em;
    font-family: 'Trebuchet MS', 'Arial Narrow', Arial, sans-serif;
    text-shadow: 0 1px 10px rgba(200,168,75,0.55), 0 0 2px rgba(0,0,0,0.4);
  }
  .pub-brand-sub {
    font-size: 0.58rem;
    font-weight: 600;
    color: #c8a84b;
    letter-spacing: 0.18em;
    font-family: 'Trebuchet MS', Arial, sans-serif;
    text-transform: uppercase;
  }
  .pub-brand-tagline {
    font-size: 0.43rem;
    font-weight: 500;
    color: rgba(255,255,255,0.52);
    letter-spacing: 0.06em;
    display: block;
    margin-top: 0.03rem;
  }
  .pub-brand-mobile .pub-brand-bull    { height: 2.25rem; }
  .pub-brand-mobile .pub-brand-name    { font-size: 0.94rem; }
  .pub-brand-mobile .pub-brand-sub     { font-size: 0.52rem; }
  .pub-brand-mobile .pub-brand-tagline { font-size: 0.4rem; }

  /* Nav buttons */
  :global(.pub-nav-btn) {
    padding: 0.25rem 0.65rem;
    font-size: 0.7rem;
    font-weight: 500;
    border-radius: 0.25rem;
    background: transparent;
    color: rgba(215, 228, 255, 0.82);
    border: none;
    cursor: pointer;
    letter-spacing: 0.02em;
    transition: background-color 0.08s, color 0.08s;
    white-space: nowrap;
    outline: none !important;
    -webkit-tap-highlight-color: transparent;
    text-shadow: 0 1px 3px rgba(0,0,0,0.55);
  }
  :global(.pub-nav-btn:hover) { background: rgba(255,255,255,0.09); color: #fff; }
  :global(.pub-nav-btn-active) { background: rgba(200,168,75,0.25); color: #f0d070; font-weight: 600; }

  /* Algo link */
  .pub-nav-algo-btn {
    padding: 0.2rem 0.6rem;
    font-size: 0.65rem;
    font-weight: 600;
    border-radius: 0.25rem;
    background: rgba(200,168,75,0.18);
    color: #e8c86a;
    border: 1px solid rgba(200,168,75,0.5);
    cursor: pointer;
    letter-spacing: 0.03em;
    transition: background-color 0.08s;
    outline: none !important;
    white-space: nowrap;
    margin-right: 0.25rem;
  }
  .pub-nav-algo-btn:hover { background: rgba(200,168,75,0.32); }

  /* Sign-in button */
  .pub-nav-signin {
    padding: 0.22rem 0.85rem;
    font-size: 0.7rem;
    font-weight: 700;
    border-radius: 0.25rem;
    background: rgba(200,168,75,0.22);
    color: #e8c86a;
    border: 1px solid rgba(200,168,75,0.55);
    cursor: pointer;
    transition: background-color 0.08s;
    outline: none !important;
    white-space: nowrap;
    text-shadow: 0 1px 2px rgba(0,0,0,0.4);
    letter-spacing: 0.03em;
  }
  .pub-nav-signin:hover { background: rgba(200,168,75,0.4); color: #fff; }

  /* User pill */
  .pub-user-pill {
    font-size: 0.72rem;
    font-weight: 500;
    color: rgba(210, 225, 255, 0.72);
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    margin-right: 0.2rem;
    white-space: nowrap;
  }

  /* Hamburger */
  .pub-hamburger {
    padding: 0.35rem;
    border-radius: 0.25rem;
    background: transparent;
    color: rgba(215,228,255,0.88);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.08s;
    outline: none !important;
  }
  .pub-hamburger:hover { background: rgba(255,255,255,0.10); }

  /* Mobile dropdown */
  .pub-mobile-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 49;
    background-color: #0c1830;
    background-image:
      linear-gradient(rgba(8,14,30,0.82), rgba(8,14,30,0.82)),
      url('/nav_image.png');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    border-top: 1px solid rgba(200,168,75,0.35);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }
  .pub-mobile-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.7rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: rgba(215,228,255,0.85);
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    cursor: pointer;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .pub-mobile-item:last-child { border-bottom: none; }
  .pub-mobile-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
  .pub-mobile-active { color: #f0d070; background: rgba(200,168,75,0.15); }
  .pub-mobile-algo   { color: #e8c86a; font-weight: 600; letter-spacing: 0.02em; }

  /* ── Content + footer ────────────────────────────────────────────────────── */
  .pub-content {
    flex: 1;
    padding: 1rem 1rem 1.5rem;
  }

  .pub-footer {
    position: sticky;
    bottom: 4px;
    z-index: 40;
    background-color: #0c1830;
    background-image:
      linear-gradient(rgba(8,14,30,0.78), rgba(8,14,30,0.78)),
      url('/nav_image.png');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    border-top: 1px solid rgba(200,168,75,0.45);
    height: 1.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 0.75rem;
  }
  .pub-footer p { width: 100%; }
  .pub-footer-text { color: rgba(210,225,255,0.75); font-size: 0.65rem; line-height: 1; }
  .pub-sep { color: #c8a84b; font-weight: bold; margin: 0 0.35rem; }
</style>
