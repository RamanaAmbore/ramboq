<script>
  const content = `About RamboQuant Analytics LLP

Invest. Grow. Compound. — not just a mantra, but the core DNA that drives every decision we make.

RamboQuant Analytics LLP is helmed by a seasoned FinTech professional with 25+ years of proven success in active investing and trading across both U.S. and Indian markets. What started in 1998 as a deep, hands-on exploration of equities and derivatives has evolved into a precision-driven investment powerhouse built on data, discipline, and performance.

The founder's credentials speak for themselves — FRM Certified, CFA Level II, PGCBM from XLRI, and a Master's in Computer Science — matched with decades of cutting-edge innovation in financial technology for capital markets.

With a long-term portfolio XIRR exceeding 22%, Rambo's approach blends high-conviction stock picks with strategic covered calls and intelligent derivatives positioning. Every move is grounded in deep analytics, rigorous risk management, and an unwavering commitment to the power of compounding.

RamboQuant Analytics is not for those content with average, index-like returns. It's built for partners who demand more — smarter strategies, sharper execution, and sustainable wealth creation.`;
</script>
<svelte:head>
  <title>About | RamboQuant Analytics</title>
  <meta name="description" content="Learn about RamboQuant Analytics LLP — investment strategy, philosophy, and team." />
</svelte:head>


<div class="w-full">
  <div class="bg-white rounded-lg border border-gray-200 shadow-sm p-5 pt-4">
    {#each content.split('\n\n') as para, i}
      {#if i === 0}
        <h2 class="page-heading">{para}</h2>
      {:else}
        <p class="text-text/90 leading-relaxed mb-3 text-sm">{para}</p>
      {/if}
    {/each}
  </div>
</div>
