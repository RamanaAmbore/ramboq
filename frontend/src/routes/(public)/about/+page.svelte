<svelte:head>
  <title>About | RamboQuant Analytics</title>
  <meta name="description" content="Learn about RamboQuant Analytics LLP — investment strategy, philosophy, and team." />
</svelte:head>

<!-- Bold statement banner -->
<div class="statement-banner">
  <div class="statement-text">INVEST. GROW. COMPOUND.</div>
  <div class="statement-sub">Not just a mantra — the core DNA behind every decision.</div>
</div>

<!-- Stat strip -->
<div class="stat-strip">
  <div class="stat-item">
    <div class="stat-num">22%<span class="stat-plus">+</span></div>
    <div class="stat-label">Long-term Portfolio XIRR</div>
  </div>
  <div class="stat-divider"></div>
  <div class="stat-item">
    <div class="stat-num">25<span class="stat-plus">+</span></div>
    <div class="stat-label">Years Active Investing</div>
  </div>
  <div class="stat-divider"></div>
  <div class="stat-item">
    <div class="stat-creds">FRM · CFA II · XLRI</div>
    <div class="stat-label">Credentials &amp; Qualifications</div>
  </div>
</div>

<!-- Prose -->
<div class="about-prose">
  <p>RamboQuant Analytics LLP is helmed by a seasoned FinTech professional with 25+ years of proven success in active investing and trading across both U.S. and Indian markets. What started in 1998 as a deep, hands-on exploration of equities and derivatives has evolved into a precision-driven investment powerhouse built on data, discipline, and performance.</p>

  <p>The founder's credentials speak for themselves — FRM Certified, CFA Level II, PGCBM from XLRI, and a Master's in Computer Science — matched with decades of cutting-edge innovation in financial technology for capital markets.</p>

  <p>With a long-term portfolio XIRR exceeding 22%, Rambo's approach blends high-conviction stock picks with strategic covered calls and intelligent derivatives positioning. Every move is grounded in deep analytics, rigorous risk management, and an unwavering commitment to the power of compounding.</p>

  <div class="closing-statement">
    RamboQuant Analytics is not for those content with average, index-like returns. It's built for partners who demand more — smarter strategies, sharper execution, and sustainable wealth creation.
  </div>
</div>

<style>
  /* ── Statement banner ──────────────────────────────────────────────────── */
  .statement-banner {
    background: #1a2744;
    margin: -1rem -1rem 0;
    padding: 2.5rem 1.75rem 2rem;
    border-bottom: 3px solid #d4920c;
  }
  .statement-text {
    font-size: 1.85rem;
    font-weight: 900;
    color: #fff;
    letter-spacing: 0.04em;
    line-height: 1.1;
  }
  .statement-sub {
    font-size: 0.78rem;
    color: rgba(200, 220, 255, 0.65);
    margin-top: 0.5rem;
    font-style: italic;
    letter-spacing: 0.01em;
  }
  @media (max-width: 767px) {
    .statement-banner { padding: 2rem 1.25rem 1.75rem; }
    .statement-text { font-size: 1.4rem; }
  }

  /* ── Stat strip ────────────────────────────────────────────────────────── */
  .stat-strip {
    display: flex;
    align-items: stretch;
    background: #f0f3f8;
    border-bottom: 1px solid #d8e0ee;
    margin: 0 -1rem 2rem;
    padding: 0 1.75rem;
  }
  .stat-item {
    flex: 1;
    padding: 1.4rem 0;
    text-align: center;
  }
  .stat-divider {
    width: 1px;
    background: #ccd4e4;
    margin: 1rem 0;
  }
  .stat-num {
    font-size: 2rem;
    font-weight: 900;
    color: #1a2744;
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .stat-plus {
    font-size: 1.2rem;
    font-weight: 700;
    color: #d4920c;
  }
  .stat-creds {
    font-size: 0.9rem;
    font-weight: 800;
    color: #1a2744;
    letter-spacing: 0.04em;
    line-height: 1.3;
  }
  .stat-label {
    font-size: 0.6rem;
    font-weight: 600;
    color: #5a7090;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.3rem;
  }
  @media (max-width: 480px) {
    .stat-strip { flex-direction: column; padding: 0 1.25rem; }
    .stat-divider { width: auto; height: 1px; margin: 0; }
    .stat-item { padding: 1rem 0; }
  }

  /* ── Prose ─────────────────────────────────────────────────────────────── */
  .about-prose {
    padding: 0 0.25rem;
  }
  .about-prose p {
    font-size: 0.9rem;
    color: #1e3050;
    line-height: 1.75;
    margin-bottom: 1.1rem;
  }
  .closing-statement {
    font-size: 0.95rem;
    font-weight: 600;
    color: #1a2744;
    line-height: 1.65;
    border-left: 3px solid #d4920c;
    padding-left: 1rem;
    margin-top: 1.75rem;
    font-style: italic;
  }
</style>
