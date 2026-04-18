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

  const bullSrc = "data:image/png;base64,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";
</script>

<div class="pub-viewport">
  <div class="pub-accent-top"></div>

  <div class="pub-card">
    <!-- Desktop navbar -->
    <header class="pub-navbar">
      <div class="pub-nav-inner hidden md:flex items-center gap-1 h-14">
        <a href="/about" class="pub-brand shrink-0 mr-5" tabindex="-1">
          <img src={bullSrc} alt="" style="height:2.6rem;width:auto;display:block;flex-shrink:0;pointer-events:none;filter:brightness(0) invert(1) sepia(50%) saturate(2.5) hue-rotate(5deg) brightness(0.9);" />
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
          <img src={bullSrc} alt="" style="height:2.2rem;width:auto;display:block;flex-shrink:0;pointer-events:none;filter:brightness(0) invert(1) sepia(50%) saturate(2.5) hue-rotate(5deg) brightness(0.9);" />
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
