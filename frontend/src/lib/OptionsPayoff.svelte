<script>
  // Payoff diagram for a single-leg option position.
  //
  // X-axis: underlying spot, ranging ±span_pct around current spot.
  // Y-axis: position P&L in rupees (already net of entry cost).
  // Two curves:
  //   - Today's value (BS @ current DTE/IV) — amber, what the position
  //     would be worth if the underlying moves NOW.
  //   - Expiry value (intrinsic only) — sky-blue dashed, what it'd be
  //     worth at settlement.
  // Markers: current spot (cyan), strike (white), breakeven (amber).
  // Profit zone shaded green, loss zone shaded red.

  /** @type {{
   *   payoff: Array<{spot:number,today_value:number,expiry_value:number}>,
   *   spot:         number,
   *   strike?:      number,
   *   breakeven?:   number,
   *   strikes?:     number[],
   *   breakevens?:  number[],
   *   height?:      number,
   *   currentPnl?:  number|null,
   * }} */
  let {
    payoff = [],
    spot,
    strike     = undefined,
    breakeven  = undefined,
    strikes    = /** @type {number[]|undefined} */ (undefined),
    breakevens = /** @type {number[]|undefined} */ (undefined),
    height     = 280,
    currentPnl = null,
  } = $props();

  // Multi-leg charts pass `strikes` / `breakevens` arrays; single-leg
  // charts pass scalars. Normalise to arrays so the render code is one
  // path. Undefined / empty falls through to no markers.
  const strikeList    = $derived(strikes
    ? strikes.filter(s => s != null)
    : (strike != null ? [strike] : []));
  const breakevenList = $derived(breakevens
    ? breakevens.filter(b => b != null)
    : (breakeven != null ? [breakeven] : []));

  /** @type {{x:number,y:number,spot:number,today:number,expiry:number}|null} */
  let hover = $state(null);

  // ── Geometry ──────────────────────────────────────────────────────
  const W = 720;
  const PAD_L = 50, PAD_R = 12, PAD_T = 12, PAD_B = 28;
  const innerW = $derived(W - PAD_L - PAD_R);
  const innerH = $derived(height - PAD_T - PAD_B);

  // X domain: spot range
  const sMin = $derived(payoff.length ? payoff[0].spot : (spot - 1));
  const sMax = $derived(payoff.length ? payoff[payoff.length - 1].spot : (spot + 1));
  const sSpan = $derived(Math.max(0.001, sMax - sMin));

  // Y domain: union of both curves with a 10% pad. Force zero into the
  // domain so the loss/profit shading lands on the actual breakeven line.
  const yDomain = $derived.by(() => {
    let lo = 0, hi = 0;
    for (const p of payoff) {
      if (p.today_value < lo)  lo = p.today_value;
      if (p.expiry_value < lo) lo = p.expiry_value;
      if (p.today_value > hi)  hi = p.today_value;
      if (p.expiry_value > hi) hi = p.expiry_value;
    }
    const pad = Math.max((hi - lo) * 0.10, 100);
    return { lo: lo - pad, hi: hi + pad, span: Math.max(1, (hi + pad) - (lo - pad)) };
  });

  function xOf(/** @type {number} */ s) {
    return PAD_L + ((s - sMin) / sSpan) * innerW;
  }
  function yOf(/** @type {number} */ v) {
    const { lo, span } = yDomain;
    return PAD_T + (1 - (v - lo) / span) * innerH;
  }
  // Y position of zero P&L line — the breakeven horizontal.
  const zeroY = $derived(yOf(0));

  // SVG paths
  const pathToday = $derived.by(() => {
    if (!payoff.length) return '';
    return payoff.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.spot).toFixed(1)},${yOf(p.today_value).toFixed(1)}`).join(' ');
  });
  const pathExpiry = $derived.by(() => {
    if (!payoff.length) return '';
    return payoff.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(p.spot).toFixed(1)},${yOf(p.expiry_value).toFixed(1)}`).join(' ');
  });

  // Profit + loss zones — shade above and below zero on the today curve
  // up to the chart bounds. Two filled paths whose top/bottom rides the
  // today curve and whose other edge is the chart's boundary.
  const fillProfit = $derived.by(() => {
    if (!payoff.length) return '';
    const top = payoff.map(p => `${xOf(p.spot).toFixed(1)},${yOf(Math.max(0, p.today_value)).toFixed(1)}`);
    const lastX  = xOf(payoff[payoff.length - 1].spot).toFixed(1);
    const firstX = xOf(payoff[0].spot).toFixed(1);
    return `M${firstX},${zeroY.toFixed(1)} L${top.join(' L')} L${lastX},${zeroY.toFixed(1)} Z`;
  });
  const fillLoss = $derived.by(() => {
    if (!payoff.length) return '';
    const bot = payoff.map(p => `${xOf(p.spot).toFixed(1)},${yOf(Math.min(0, p.today_value)).toFixed(1)}`);
    const lastX  = xOf(payoff[payoff.length - 1].spot).toFixed(1);
    const firstX = xOf(payoff[0].spot).toFixed(1);
    return `M${firstX},${zeroY.toFixed(1)} L${bot.join(' L')} L${lastX},${zeroY.toFixed(1)} Z`;
  });

  function fmtMoney(/** @type {number} */ v) {
    const sign = v < 0 ? '-' : v > 0 ? '+' : '';
    return `${sign}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  }
  function fmtSpot(/** @type {number} */ v) {
    return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
  }

  function onPointerMove(/** @type {PointerEvent} */ e) {
    if (!payoff.length) return;
    const svg = /** @type {SVGSVGElement} */ (e.currentTarget);
    const rect = svg.getBoundingClientRect();
    const xPx  = (e.clientX - rect.left) * (W / rect.width);
    const xVal = sMin + ((xPx - PAD_L) / innerW) * sSpan;
    // Find nearest payoff point
    let best = payoff[0];
    let bestDiff = Math.abs(best.spot - xVal);
    for (const p of payoff) {
      const d = Math.abs(p.spot - xVal);
      if (d < bestDiff) { best = p; bestDiff = d; }
    }
    hover = {
      x: xOf(best.spot), y: yOf(best.today_value),
      spot: best.spot, today: best.today_value, expiry: best.expiry_value,
    };
  }
  function onPointerLeave() { hover = null; }

  // Y-axis ticks — 5 evenly spaced labels.
  const yTicks = $derived.by(() => {
    if (!payoff.length) return [];
    const { lo, hi } = yDomain;
    const n = 5;
    return Array.from({ length: n }, (_, i) => {
      const v = lo + ((hi - lo) * i) / (n - 1);
      return { v, y: yOf(v) };
    });
  });
</script>

<div class="payoff-chart" style="--chart-h: {height}px">
  {#if !payoff.length}
    <div class="payoff-empty">
      No payoff data.
    </div>
  {:else}
    <svg viewBox="0 0 {W} {height}" preserveAspectRatio="none"
         class="payoff-svg"
         role="img" aria-label="Option payoff diagram"
         onpointermove={onPointerMove}
         onpointerleave={onPointerLeave}>
      <!-- Profit / loss shading (under the curves so the lines pop) -->
      <path d={fillProfit} fill="rgba(34,197,94,0.10)" stroke="none"/>
      <path d={fillLoss}   fill="rgba(248,113,113,0.10)" stroke="none"/>

      <!-- Y-axis grid + labels -->
      {#each yTicks as t}
        <line x1={PAD_L} x2={W - PAD_R} y1={t.y} y2={t.y}
              stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
        <text x={PAD_L - 6} y={t.y + 3} text-anchor="end"
              fill="#7e97b8" font-size="9" font-family="monospace">
          {fmtMoney(t.v)}
        </text>
      {/each}

      <!-- Zero line — solid, slightly stronger than the grid -->
      <line x1={PAD_L} x2={W - PAD_R} y1={zeroY} y2={zeroY}
            stroke="rgba(255,255,255,0.25)" stroke-width="1"/>

      <!-- Strike markers — one dashed white vertical per strike -->
      {#each strikeList as k}
        {#if k >= sMin && k <= sMax}
          <line x1={xOf(k)} x2={xOf(k)} y1={PAD_T} y2={height - PAD_B}
                stroke="rgba(226,232,240,0.40)" stroke-width="1" stroke-dasharray="2 2"/>
          <text x={xOf(k)} y={PAD_T + 10}
                text-anchor="middle" fill="#e2e8f0"
                font-size="9" font-family="monospace" opacity="0.7">
            K {k.toFixed(0)}
          </text>
        {/if}
      {/each}

      <!-- Breakeven markers — amber dashed verticals; multi-leg
           strategies (iron condor, butterfly) can produce two. -->
      {#each breakevenList as be}
        {#if be > sMin && be < sMax}
          <line x1={xOf(be)} x2={xOf(be)} y1={PAD_T} y2={height - PAD_B}
                stroke="rgba(251,191,36,0.55)" stroke-width="1" stroke-dasharray="3 3"/>
          <text x={xOf(be)} y={height - PAD_B + 18}
                text-anchor="middle" fill="#fbbf24"
                font-size="9" font-family="monospace">
            BE {be.toFixed(0)}
          </text>
        {/if}
      {/each}

      <!-- Current spot marker — cyan vertical -->
      <line x1={xOf(spot)} x2={xOf(spot)} y1={PAD_T} y2={height - PAD_B}
            stroke="#7dd3fc" stroke-width="1.5"/>
      <text x={xOf(spot)} y={height - PAD_B + 18}
            text-anchor="middle" fill="#7dd3fc"
            font-size="9" font-weight="700" font-family="monospace">
        spot {spot.toFixed(0)}
      </text>

      <!-- Expiry curve (dashed sky) -->
      <path d={pathExpiry} fill="none" stroke="#7dd3fc"
            stroke-width="1.25" stroke-dasharray="4 3" stroke-opacity="0.85"/>
      <!-- Today curve (solid amber, primary) -->
      <path d={pathToday}  fill="none" stroke="#fbbf24" stroke-width="1.75"/>

      <!-- Current P&L marker (dot at spot, today_value) -->
      {#if currentPnl != null && spot >= sMin && spot <= sMax}
        <circle cx={xOf(spot)} cy={yOf(currentPnl)} r="4"
                fill="#fbbf24" stroke="#0c1830" stroke-width="1.5"/>
      {/if}

      <!-- Hover crosshair + tooltip -->
      {#if hover}
        <line x1={hover.x} x2={hover.x} y1={PAD_T} y2={height - PAD_B}
              stroke="rgba(255,255,255,0.20)" stroke-width="1"/>
        {@const tx = Math.min(W - 170 - PAD_R, Math.max(PAD_L, hover.x + 10))}
        {@const ty = Math.max(PAD_T, hover.y - 60)}
        <g pointer-events="none">
          <rect x={tx} y={ty} width="170" height="56" rx="4"
                fill="#1d2a44" stroke="rgba(251,191,36,0.4)" stroke-width="1"/>
          <text x={tx + 6} y={ty + 14} fill="#7dd3fc"
                font-size="10" font-weight="700" font-family="monospace">
            spot {fmtSpot(hover.spot)}
          </text>
          <text x={tx + 6} y={ty + 30} fill="#fbbf24"
                font-size="9" font-family="monospace">
            today {fmtMoney(hover.today)}
          </text>
          <text x={tx + 6} y={ty + 44} fill="#7dd3fc"
                font-size="9" font-family="monospace">
            expiry {fmtMoney(hover.expiry)}
          </text>
        </g>
      {/if}
    </svg>
    <div class="payoff-legend">
      <span class="legend-item">
        <span class="legend-line legend-today"></span>
        Today (BS)
      </span>
      <span class="legend-item">
        <span class="legend-line legend-expiry"></span>
        Expiry (intrinsic)
      </span>
      <span class="legend-item legend-spot">
        <span class="legend-mark legend-spot-mark"></span>
        Spot
      </span>
      <span class="legend-item legend-be">
        <span class="legend-mark legend-be-mark"></span>
        Breakeven
      </span>
    </div>
  {/if}
</div>

<style>
  .payoff-chart {
    background: linear-gradient(180deg, #1d2a44 0%, #152033 100%);
    border: 1px solid rgba(251,191,36,0.18);
    border-left: 3px solid #fbbf24;
    border-radius: 4px;
    padding: 6px 8px 8px;
    width: 100%;
    box-sizing: border-box;
  }
  .payoff-svg {
    width: 100%;
    height: var(--chart-h, 280px);
    display: block;
    cursor: crosshair;
  }
  .payoff-empty {
    height: var(--chart-h, 280px);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #7e97b8;
    font-size: 0.65rem;
    font-family: monospace;
  }
  .payoff-legend {
    display: flex;
    gap: 0.9rem;
    flex-wrap: wrap;
    padding-top: 0.4rem;
    font-size: 0.55rem;
    font-family: monospace;
    color: #c8d8f0;
    border-top: 1px solid rgba(255,255,255,0.05);
    margin-top: 0.3rem;
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .legend-line {
    width: 16px;
    height: 0;
  }
  .legend-today  { border-top: 2px solid #fbbf24; }
  .legend-expiry { border-top: 1.5px dashed #7dd3fc; }
  .legend-mark {
    display: inline-block;
    width: 0;
    height: 12px;
  }
  .legend-spot-mark { border-left: 2px solid #7dd3fc; }
  .legend-be-mark   { border-left: 2px dashed #fbbf24; }
</style>
