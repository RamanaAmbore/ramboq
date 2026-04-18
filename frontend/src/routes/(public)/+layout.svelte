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
          <img src={bullSrc} alt="" style="height:2.6rem;width:auto;display:block;flex-shrink:0;pointer-events:none;" />
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
          <img src={bullSrc} alt="" style="height:2.2rem;width:auto;display:block;flex-shrink:0;pointer-events:none;" />
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
