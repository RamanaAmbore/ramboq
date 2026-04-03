<script>
  import '../app.css';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { authStore } from '$lib/stores';

  const { children } = $props();

  // Redirect /orders to signin if not authed
  $effect(() => {
    const path = page.url.pathname;
    if (path.startsWith('/orders') && !$authStore.token) {
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

  // Base nav links visible to everyone
  const baseLinks = [
    { href: '/about',       label: 'About'       },
    { href: '/market',      label: 'Market'      },
    { href: '/performance', label: 'Performance' },
    { href: '/faq',         label: 'FAQ'         },
    { href: '/post',        label: 'Insights'    },
    { href: '/contact',     label: 'Contact'     },
  ];

  // Additional links for signed-in users
  const partnerLinks = [
    { href: '/portfolio', label: 'My Portfolio' },
    // { href: '/orders',    label: 'Orders'       },  // temporarily hidden
  ];

  // Admin-only links
  const adminLinks = [
    { href: '/admin', label: 'Users' },
    // { href: '/console', label: 'Console' },  // temporarily hidden
  ];

  /** All nav links for current auth state. */
  function navLinks(user) {
    if (!user) return baseLinks;
    const extra = user.role === 'admin' ? [...partnerLinks, ...adminLinks] : partnerLinks;
    return [...baseLinks, ...extra];
  }

  let menuOpen = $state(false);
  const closeMenu = () => { menuOpen = false; };
</script>

<div class="viewport">
  <div class="accent-bar accent-bar-top"></div>

  <div class="page-card">
    <header class="navbar">
      <!-- Desktop -->
      <div class="nav-inner hidden md:flex items-center gap-1 h-14">
        <a href="/about" class="shrink-0 mr-4" tabindex="-1">
          <img src="/logo.png" alt="RamboQuant Analytics LLP" class="h-9 w-auto pointer-events-none" />
        </a>
        <nav class="flex items-center gap-0.5 flex-1">
          {#each navLinks($authStore.user) as link}
            <button
              onclick={() => goto(link.href)}
              class="nav-btn {isActive(link.href) ? 'nav-btn-active' : ''}"
            >{link.label}</button>
          {/each}
        </nav>
        {#if $authStore.user}
          <span class="nav-user-pill">{$authStore.user.display_name}</span>
          <button onclick={signOut} class="nav-btn">Sign Out</button>
        {:else}
          <button onclick={() => goto('/signin')} class="nav-btn-signin {isActive('/signin') ? 'nav-btn-active' : ''}">Sign In</button>
        {/if}
      </div>

      <!-- Mobile bar -->
      <div class="nav-inner md:hidden flex items-center justify-between h-12">
        <a href="/about" class="shrink-0" tabindex="-1">
          <img src="/logo.png" alt="RamboQuant Analytics LLP" class="h-8 w-auto pointer-events-none" />
        </a>
        <button
          onclick={() => menuOpen = !menuOpen}
          class="hamburger"
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

      <!-- Mobile dropdown -->
      {#if menuOpen}
        <nav class="mobile-dropdown">
          {#each navLinks($authStore.user) as link}
            <button
              onclick={() => { goto(link.href); closeMenu(); }}
              class="mobile-nav-item {isActive(link.href) ? 'mobile-nav-active' : ''}"
            >{link.label}</button>
          {/each}
          {#if $authStore.user}
            <div class="mobile-nav-user">{$authStore.user.display_name}</div>
            <button onclick={() => { signOut(); closeMenu(); }} class="mobile-nav-item">Sign Out</button>
          {:else}
            <button onclick={() => { goto('/signin'); closeMenu(); }} class="mobile-nav-item">Sign In</button>
          {/if}
        </nav>
      {/if}
    </header>

    <main class="content">
      {@render children()}
    </main>

    <footer class="site-footer">
      <p class="hidden md:block text-center leading-none footer-text">
        © RamboQuant Analytics LLP
        <span class="text-accent font-bold mx-1">|</span>
        ACU-5195
        <span class="text-accent font-bold mx-1">|</span>
        Disclaimer: Investment in markets is subject to risk. Past performance is not indicative of future results.
      </p>
      <p class="md:hidden text-center leading-none footer-text">
        © RamboQuant Analytics LLP
        <span class="text-accent font-bold mx-1">|</span>
        ACU-5195
        <span class="text-accent font-bold mx-1">|</span>
        Markets carry risk.
      </p>
    </footer>
  </div>

  <div class="accent-bar accent-bar-bottom"></div>
</div>

<style>
  .viewport {
    min-height: 100vh;
    background-color: #e0e0e3;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .accent-bar {
    position: fixed;
    height: 3px;
    background-color: #ef9309;
    z-index: 200;
    max-width: 958px;
    width: 100%;
    left: 50%;
    transform: translateX(-50%);
  }
  .accent-bar-top    { top: 0; }
  .accent-bar-bottom { bottom: 0; }

  .page-card {
    width: 100%;
    max-width: 960px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background-color: #f5f5f7;
    border-left:  1px solid #c4c4c8;
    border-right: 1px solid #c4c4c8;
    box-shadow: -2px 0 5px rgba(0,0,0,0.10), 2px 0 5px rgba(0,0,0,0.10);
    margin-top: 3px;
    margin-bottom: 3px;
  }

  .navbar {
    position: sticky;
    top: 3px;
    z-index: 50;
    background-image: url('/nav_image.png');
    background-size: cover;
    background-position: center;
    background-attachment: local;
    box-shadow: inset 0 0 0 100vw rgba(8, 35, 35, 0.10), 0 1px 3px rgba(0,0,0,0.05);
    overflow: visible;
  }

  .nav-inner {
    max-width: 960px;
    margin: 0 auto;
    padding: 0 1rem;
  }

  :global(.nav-btn) {
    padding: 0.28rem 0.7rem;
    font-size: 0.8rem;
    font-weight: 500;
    border-radius: 0.3rem;
    background: transparent;
    color: rgba(255,255,255,0.85);
    border: none;
    cursor: pointer;
    transition: background-color 0.05s;
    white-space: nowrap;
    text-decoration: none;
    display: inline-block;
    outline: none !important;
    -webkit-tap-highlight-color: transparent;
  }
  :global(.nav-btn:hover) { background-color: rgba(255,255,255,0.15); color: #fff; }
  :global(.nav-btn-active) { background-color: rgba(255,255,255,0.22); color: #fff; font-weight: 500; }

  /* Sign In button — filled, matches btn-primary */
  .nav-btn-signin {
    padding: 0.25rem 0.8rem;
    font-size: 0.8rem;
    font-weight: 600;
    border-radius: 0.3rem;
    background: rgba(255,255,255,0.18);
    color: #fff;
    border: 1px solid rgba(255,255,255,0.4);
    cursor: pointer;
    transition: background-color 0.05s;
    outline: none !important;
    white-space: nowrap;
  }
  .nav-btn-signin:hover { background: rgba(255,255,255,0.28); }

  /* Signed-in user pill */
  .nav-user-pill {
    font-size: 0.72rem;
    font-weight: 600;
    color: rgba(255,255,255,0.7);
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.12);
    margin-right: 0.25rem;
    white-space: nowrap;
  }

  .hamburger {
    padding: 0.35rem;
    border-radius: 0.3rem;
    background: transparent;
    color: rgba(255,255,255,0.9);
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .hamburger:hover { background-color: rgba(255,255,255,0.15); }

  .mobile-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 49;
    background-image: url('/nav_image.png');
    background-size: cover;
    background-position: center;
    box-shadow: inset 0 0 0 100vw rgba(8, 35, 35, 0.6), 0 4px 8px rgba(0,0,0,0.2);
  }
  .mobile-nav-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.65rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    color: rgba(255,255,255,0.85);
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    cursor: pointer;
    transition: background-color 0.05s;
    outline: none !important;
  }
  .mobile-nav-item:last-child { border-bottom: none; }
  .mobile-nav-item:hover { background-color: rgba(255,255,255,0.12); color: #fff; }
  .mobile-nav-active { color: #fff; background-color: rgba(255,255,255,0.18); }

  .mobile-nav-user {
    padding: 0.4rem 1.25rem;
    font-size: 0.72rem;
    font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid rgba(255,255,255,0.1);
  }

  .content {
    flex: 1;
    padding: 1rem 1rem 1.5rem;
  }

  .site-footer {
    position: sticky;
    bottom: 3px;
    z-index: 40;
    background-image: url('/nav_image.png');
    background-size: cover;
    background-position: center bottom;
    box-shadow: inset 0 0 0 100vw rgba(8, 35, 35, 0.10), 0 -1px 2px rgba(0,0,0,0.05);
    height: 1.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 0.75rem;
  }
  .site-footer p { width: 100%; }

  :global(.text-accent) { color: #ef9309; }
  .footer-text { color: rgba(255,255,255,0.92); font-size: 0.58rem; line-height: 1; }
</style>
