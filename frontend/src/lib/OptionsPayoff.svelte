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
   *   spanSigmas?:  number,
   *   spanPct?:     number,
   *   dte?:         number|null,
   *   ivProxy?:     number|null,
   *   legCount?:    number|null,
   *   onRefresh?:   (() => void) | null,
   *   loading?:     boolean,
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
    spanSigmas = 0,
    spanPct    = 0,
    dte        = /** @type {number|null|undefined} */ (null),
    ivProxy    = /** @type {number|null|undefined} */ (null),
    legCount   = /** @type {number|null|undefined} */ (null),
    onRefresh  = /** @type {(() => void) | null} */ (null),
    loading    = false,
  } = $props();

  // Nearest curve point to current spot — drives the on-chart TDAY/EXP
  // readouts so the operator sees position P&L right beside the chart.
  const curveAtSpot = $derived.by(() => {
    if (!payoff.length) return null;
    let best = payoff[0];
    let bestDiff = Math.abs(best.spot - spot);
    for (const p of payoff) {
      const d = Math.abs(p.spot - spot);
      if (d < bestDiff) { bestDiff = d; best = p; }
    }
    return best;
  });

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
  // PAD_B widened from 28 → 40 so rotated σ labels (-30°) and the
  // breakeven labels stacked beneath them have the vertical room they
  // need without colliding with the chart legend.
  const PAD_L = 50, PAD_R = 12, PAD_T = 12, PAD_B = 40;
  const innerW = $derived(W - PAD_L - PAD_R);
  const innerH = $derived(height - PAD_T - PAD_B);

  // ── Zoom + pan state ──────────────────────────────────────────────
  // Operator can wheel-zoom into one strike or breakeven cluster, then
  // drag-pan to scan along the spot axis. Reset button (visible when
  // zoomed) snaps back to the auto ±2.5σ range supplied by the API.
  /** @type {{xMin: number, xMax: number} | null} */
  let zoom = $state(null);
  /** @type {{startClientX: number, startMin: number, startMax: number} | null} */
  let pan = $state(null);

  // X domain — `zoom` overrides the auto-derived spot range.
  const dataMin = $derived(payoff.length ? payoff[0].spot : (spot - 1));
  const dataMax = $derived(payoff.length ? payoff[payoff.length - 1].spot : (spot + 1));
  const sMin  = $derived(zoom ? zoom.xMin : dataMin);
  const sMax  = $derived(zoom ? zoom.xMax : dataMax);
  const sSpan = $derived(Math.max(0.001, sMax - sMin));
  const isZoomed = $derived(zoom !== null);

  // Y domain: union of both curves over the *visible* x-range. When
  // the operator zooms into a narrow spot range, the y-axis tightens
  // to the P&L excursion that's actually on screen — otherwise an
  // out-of-view +∞ wing of a long call would dominate the y-axis even
  // after zooming away from it. Force zero into the domain so the
  // loss/profit shading lands on the actual breakeven line.
  const visiblePayoff = $derived(
    payoff.filter(p => p.spot >= sMin && p.spot <= sMax)
  );
  const yDomain = $derived.by(() => {
    const src = visiblePayoff.length ? visiblePayoff : payoff;
    let lo = 0, hi = 0;
    for (const p of src) {
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

  // Snap the tooltip to the payoff point nearest to the given client X.
  // Shared between hover (mouse pointermove) and tap (touch pointerdown)
  // so the touch path produces the same tooltip as desktop hover.
  function _setHoverFromClientX(/** @type {SVGSVGElement} */ svg,
                                /** @type {number} */ clientX) {
    if (!payoff.length) return;
    const rect = svg.getBoundingClientRect();
    const xPx  = (clientX - rect.left) * (W / rect.width);
    const xVal = sMin + ((xPx - PAD_L) / innerW) * sSpan;
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

  function onPointerMove(/** @type {PointerEvent} */ e) {
    if (!payoff.length) return;
    const svg = /** @type {SVGSVGElement} */ (e.currentTarget);
    if (pan) {
      const rect = svg.getBoundingClientRect();
      const dxPx = (e.clientX - pan.startClientX) * (W / rect.width);
      const dxVal = (dxPx / innerW) * (pan.startMax - pan.startMin);
      zoom = { xMin: pan.startMin - dxVal, xMax: pan.startMax - dxVal };
      hover = null;
      return;
    }
    _setHoverFromClientX(svg, e.clientX);
  }
  // Mouse leave clears hover. Touch leaves the tooltip pinned (the
  // operator tapped to read; they expect it to stay until they tap
  // somewhere else).
  function onPointerLeave(/** @type {PointerEvent} */ e) {
    if (e.pointerType !== 'touch') hover = null;
  }

  function onWheel(/** @type {WheelEvent} */ e) {
    if (!payoff.length) return;
    e.preventDefault();
    const svg  = /** @type {SVGSVGElement} */ (e.currentTarget);
    const rect = svg.getBoundingClientRect();
    const xPx  = (e.clientX - rect.left) * (W / rect.width);
    const xVal = sMin + ((xPx - PAD_L) / innerW) * sSpan;
    const factor = e.deltaY > 0 ? 1.25 : 1 / 1.25;
    const newMin = xVal - (xVal - sMin) * factor;
    const newMax = xVal + (sMax - xVal) * factor;
    if (newMin <= dataMin && newMax >= dataMax) { zoom = null; return; }
    if (newMax - newMin < (dataMax - dataMin) * 0.02) return;   // floor at 2% of full range
    zoom = { xMin: newMin, xMax: newMax };
  }
  function onPointerDown(/** @type {PointerEvent} */ e) {
    if (!payoff.length || e.button !== 0) return;
    /** @type {any} */ const tgt = e.currentTarget;
    // Touch tap → show the tooltip at the tap location. Don't start
    // a pan: native scroll + page panning is rarely what the operator
    // wants when they're trying to read a value at a strike.
    if (e.pointerType === 'touch') {
      _setHoverFromClientX(/** @type {SVGSVGElement} */ (tgt), e.clientX);
      return;
    }
    tgt.setPointerCapture?.(e.pointerId);
    pan = { startClientX: e.clientX, startMin: sMin, startMax: sMax };
  }
  function onPointerUp(/** @type {PointerEvent} */ e) {
    if (pan) {
      /** @type {any} */ const tgt = e.currentTarget;
      tgt.releasePointerCapture?.(e.pointerId);
    }
    pan = null;
  }
  function resetZoom() { zoom = null; pan = null; }

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

  // X-axis ticks — sigma marks at every 0.5σ across ±spanSigmas
  // around the spot, when spanSigmas + spanPct are supplied (the API
  // returns both for auto-derived ranges). Each k-σ point sits at
  //   spot * (1 + k * spanPct / spanSigmas)
  // since the chart's spot range is ±spanPct and that range maps
  // 1-to-1 to ±spanSigmas. Falls back to evenly-spaced spot ticks
  // when spanSigmas isn't provided (operator-overridden span_pct).
  const xTicks = $derived.by(() => {
    if (!payoff.length) return [];
    if (spanSigmas > 0 && spanPct > 0 && spot > 0) {
      const ticks = [];
      // -spanSigmas → +spanSigmas in 0.5 steps. Round to single
      // decimal so floating math doesn't push 0 to 0.0000001.
      for (let k = -spanSigmas; k <= spanSigmas + 1e-9; k += 0.5) {
        const kRounded = Math.round(k * 2) / 2;
        const s = spot * (1 + (kRounded * spanPct) / spanSigmas);
        if (s < sMin - 1e-6 || s > sMax + 1e-6) continue;
        ticks.push({
          s,
          x: xOf(s),
          sigma: kRounded,
          label: kRounded === 0 ? '0' :
                 (kRounded > 0 ? '+' : '−') +
                 (Math.abs(kRounded) % 1 === 0
                   ? Math.abs(kRounded).toFixed(0)
                   : Math.abs(kRounded).toFixed(1)) + 'σ',
        });
      }
      return ticks;
    }
    // Fallback — evenly spaced spot prices when sigma metadata is
    // unavailable (custom span_pct).
    const n = 5;
    return Array.from({ length: n }, (_, i) => {
      const s = sMin + (sSpan * i) / (n - 1);
      return { s, x: xOf(s), sigma: null, label: s.toFixed(0) };
    });
  });
</script>

<div class="payoff-chart" style="--chart-h: {height}px">
  {#if !payoff.length}
    <div class="payoff-empty">
      No payoff data.
    </div>
  {:else}
    {#if isZoomed}
      <button type="button" class="payoff-reset"
              title="Reset zoom — return to the auto ±3σ range"
              onclick={resetZoom}>reset zoom</button>
    {/if}
    {#if onRefresh}
      <!-- Top-right refresh button. Absolutely positioned so the
           "Refresh" → "Refreshing…" text swap can never push the
           SVG / stat overlay / legend around. Width is locked to
           the wider "Refreshing…" string so the button itself also
           stays put across state changes. -->
      <button type="button"
              class="payoff-refresh"
              class:payoff-refresh-busy={loading}
              disabled={loading}
              title="Re-fetch spot, LTPs, Greeks, and the payoff curve now"
              aria-label="Refresh prices"
              onclick={() => onRefresh && onRefresh()}>
        <span class="payoff-refresh-label">
          {#if loading}Refreshing…{:else}↻ Refresh{/if}
        </span>
      </button>
    {/if}
    <!-- Top-left stat overlay — the chart's at-a-glance numerics so the
         operator doesn't have to glance at the Greeks / Risk cards just
         to read TDAY P&L or max profit. Pointer-events: none so the
         SVG hover / zoom / pan stay click-through. -->
    <div class="payoff-stats" aria-hidden="true">
      <div class="ps-row">
        <span class="ps-k">SPOT</span>
        <span class="ps-v ps-spot">₹{spot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
      </div>
      {#if curveAtSpot}
        <div class="ps-row">
          <span class="ps-k">TDAY</span>
          <span class={'ps-v ' + (curveAtSpot.today_value >= 0 ? 'ps-pos' : 'ps-neg')}>
            {fmtMoney(curveAtSpot.today_value)}
          </span>
        </div>
        <div class="ps-row">
          <span class="ps-k">EXP</span>
          <span class={'ps-v ' + (curveAtSpot.expiry_value >= 0 ? 'ps-pos' : 'ps-neg')}>
            {fmtMoney(curveAtSpot.expiry_value)}
          </span>
        </div>
      {/if}
      {#if dte != null}
        <div class="ps-row">
          <span class="ps-k">DTE</span>
          <span class="ps-v">{Math.round(dte)}</span>
        </div>
      {/if}
      {#if ivProxy != null}
        <div class="ps-row">
          <span class="ps-k">σ</span>
          <span class="ps-v">{(ivProxy * 100).toFixed(1)}%</span>
        </div>
      {/if}
      {#if legCount != null}
        <div class="ps-row">
          <span class="ps-k">LEGS</span>
          <span class="ps-v">{legCount}</span>
        </div>
      {/if}
    </div>
    <svg viewBox="0 0 {W} {height}" preserveAspectRatio="none"
         class="payoff-svg" class:payoff-panning={pan !== null}
         role="img" aria-label="Option payoff diagram — wheel to zoom, drag to pan"
         onwheel={onWheel}
         onpointerdown={onPointerDown}
         onpointerup={onPointerUp}
         onpointermove={onPointerMove}
         onpointerleave={onPointerLeave}>
      <!-- Profit / loss shading (under the curves so the lines pop) -->
      <path d={fillProfit} fill="rgba(34,197,94,0.10)" stroke="none"/>
      <path d={fillLoss}   fill="rgba(248,113,113,0.10)" stroke="none"/>

      <!-- Y-axis grid + labels -->
      {#each yTicks as t}
        <line x1={PAD_L} x2={W - PAD_R} y1={t.y} y2={t.y}
              stroke="rgba(200,216,240,0.10)" stroke-width="1"/>
        <text x={PAD_L - 6} y={t.y + 3} text-anchor="end"
              fill="#7e97b8" font-size="9" font-family="monospace">
          {fmtMoney(t.v)}
        </text>
      {/each}

      <!-- X-axis grid + labels — sigma marks at every 0.5σ across
           ±spanSigmas (when the API returned span metadata), or
           evenly spaced spot values otherwise. Whole-sigma ticks
           (±1σ, ±2σ, …) get a stronger grid line + brighter label;
           half-sigma ticks (±0.5σ, ±1.5σ, …) are subdued. Labels
           are rotated -30° so neighbouring ticks (every 0.5σ) don't
           collide on narrow charts — the slant also gives the axis
           a proper tabular feel without forcing label hiding. -->
      {#each xTicks as xt}
        {@const wholeSigma = xt.sigma != null && xt.sigma % 1 === 0}
        {@const isCenter   = xt.sigma === 0}
        {#if !isCenter}
          <line x1={xt.x} x2={xt.x} y1={PAD_T} y2={height - PAD_B}
                stroke="rgba(200,216,240,{wholeSigma ? 0.16 : 0.07})"
                stroke-width="1"/>
        {/if}
        {#if !isCenter}
          {@const ly = height - PAD_B + 10}
          <text x={xt.x} y={ly}
                text-anchor="end"
                transform="rotate(-30 {xt.x} {ly})"
                fill={wholeSigma ? '#fbbf24' : '#c8d8f0'}
                font-size={wholeSigma ? 11 : 10}
                font-weight={wholeSigma ? 700 : 500}
                font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">
            {xt.label}
          </text>
        {/if}
      {/each}

      <!-- Zero line — solid, slightly stronger than the grid -->
      <line x1={PAD_L} x2={W - PAD_R} y1={zeroY} y2={zeroY}
            stroke="rgba(255,255,255,0.25)" stroke-width="1"/>

      <!-- Strike markers — one dashed white vertical per strike,
           labelled with the strike's distance from spot in σ-units
           (e.g. "+1.5σ" / "−0.8σ"). Falls back to the raw strike
           value when σ metadata isn't available (operator-overridden
           span_pct on the API). The actual strike price is still
           visible in the kv-pair tables below the chart. -->
      {#each strikeList as k}
        {#if k >= sMin && k <= sMax}
          <line x1={xOf(k)} x2={xOf(k)} y1={PAD_T} y2={height - PAD_B}
                stroke="rgba(226,232,240,0.40)" stroke-width="1" stroke-dasharray="2 2"/>
          <text x={xOf(k)} y={PAD_T + 10}
                text-anchor="middle" fill="#e2e8f0"
                font-size="9" font-family="monospace" opacity="0.85">
            {#if spanSigmas > 0 && spanPct > 0 && spot > 0}
              {@const kSig = ((k / spot) - 1) * spanSigmas / spanPct}
              {kSig >= 0 ? '+' : '−'}{Math.abs(kSig).toFixed(1)}σ
            {:else}
              {k.toFixed(0)}
            {/if}
          </text>
        {/if}
      {/each}

      <!-- Breakeven markers — amber dashed verticals; multi-leg
           strategies (iron condor, butterfly) can produce two. -->
      {#each breakevenList as be}
        {#if be > sMin && be < sMax}
          <line x1={xOf(be)} x2={xOf(be)} y1={PAD_T} y2={height - PAD_B}
                stroke="rgba(251,191,36,0.55)" stroke-width="1" stroke-dasharray="3 3"/>
          <text x={xOf(be)} y={height - PAD_B + 32}
                text-anchor="middle" fill="#fbbf24"
                font-size="9" font-family="monospace">
            BE {be.toFixed(0)}
          </text>
        {/if}
      {/each}

      <!-- Current spot marker — cyan vertical (numeric value lives in
           the top-left stat overlay; the legend identifies the line). -->
      <line x1={xOf(spot)} x2={xOf(spot)} y1={PAD_T} y2={height - PAD_B}
            stroke="#7dd3fc" stroke-width="1.5"/>

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
            TDAY {fmtMoney(hover.today)}
          </text>
          <text x={tx + 6} y={ty + 44} fill="#7dd3fc"
                font-size="9" font-family="monospace">
            EXP  {fmtMoney(hover.expiry)}
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
    position: relative;
  }
  .payoff-svg {
    width: 100%;
    height: var(--chart-h, 280px);
    display: block;
    cursor: crosshair;
    touch-action: pan-y;
  }
  .payoff-svg.payoff-panning { cursor: grabbing; }
  .payoff-reset {
    position: absolute;
    top: 0.4rem;
    /* Sit immediately to the LEFT of the Refresh button (Refresh
       width 5.4rem + 0.6rem right offset + 0.3rem gap = 6.3rem) so
       the two top-right buttons never overlap. */
    right: 6.3rem;
    font-family: monospace;
    font-size: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 1px 6px;
    border-radius: 2px;
    border: 1px solid rgba(251,191,36,0.45);
    background: rgba(251,191,36,0.10);
    color: #fbbf24;
    cursor: pointer;
    z-index: 1;
  }
  .payoff-reset:hover {
    background: rgba(251,191,36,0.20);
    border-color: rgba(251,191,36,0.65);
  }

  /* Refresh button — top-right corner of the chart. Width is locked
     so the "Refresh" / "Refreshing…" swap never reflows; the inner
     <span> centers either label inside the same fixed box. Position
     is absolute so the button + its state changes can never push the
     SVG / stat overlay / legend around. */
  .payoff-refresh {
    position: absolute;
    top: 0.4rem;
    right: 0.6rem;
    width: 5.4rem;
    height: 1.1rem;
    padding: 0;
    border-radius: 2px;
    border: 1px solid rgba(125,211,252,0.55);
    background: rgba(125,211,252,0.10);
    color: #7dd3fc;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    line-height: 1;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
    transition: background 0.1s, border-color 0.1s, color 0.1s;
  }
  .payoff-refresh-label {
    /* Center the label inside the fixed-width button; tabular-nums
       keeps any digits steady if a future variant interleaves them. */
    display: inline-block;
    text-align: center;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .payoff-refresh:hover:not(:disabled) {
    background: rgba(125,211,252,0.22);
    border-color: rgba(125,211,252,0.85);
  }
  .payoff-refresh:disabled,
  .payoff-refresh-busy {
    cursor: progress;
    opacity: 0.7;
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

  /* On-chart stat overlay — reads the key numerics off the curve so
     the chart is self-contained. Sits top-left, semi-transparent,
     pointer-events disabled so it never blocks the SVG hover/zoom. */
  .payoff-stats {
    position: absolute;
    top: 0.5rem;
    left: 0.6rem;
    display: grid;
    grid-template-columns: max-content max-content;
    column-gap: 0.55rem;
    row-gap: 0.12rem;
    padding: 0.35rem 0.55rem;
    border-radius: 3px;
    background: rgba(13,21,38,0.72);
    border: 1px solid rgba(251,191,36,0.22);
    font-family: monospace;
    font-size: 0.6rem;
    line-height: 1.15;
    pointer-events: none;
    z-index: 1;
  }
  .ps-row {
    display: contents;
  }
  .ps-k {
    color: #7e97b8;
    letter-spacing: 0.04em;
    font-size: 0.55rem;
    align-self: center;
  }
  .ps-v {
    text-align: right;
    font-weight: 600;
    color: #c8d8f0;
    font-variant-numeric: tabular-nums;
  }
  .ps-v.ps-spot { color: #7dd3fc; }
  .ps-v.ps-pos  { color: #22c55e; }
  .ps-v.ps-neg  { color: #f87171; }
</style>
