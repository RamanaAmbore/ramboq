<script>
  // Top-of-book depth ladder for an order ticket.
  //
  // Phase 1: placeholder UI only — shows a 5-row x 4-col scaffold
  // (bid qty / bid / ask / ask qty) with em-dashes, plus a hint
  // line explaining that the live ladder lands in phase 2 once
  // /api/quote/depth is wired.
  //
  // Phase 2: poll `/api/quote/depth?symbol=…&exchange=…` every 1 s
  // while the parent ticket is mounted. Backend is a thin wrapper
  // around the existing broker.quote() depth field.

  /** @type {{ symbol: string, exchange?: string }} */
  let { symbol, exchange = '' } = $props();
</script>

<div class="ot-depth">
  <div class="ot-depth-h">
    Depth · {symbol}{exchange ? ' · ' + exchange : ''}
    <span class="ot-depth-meta">live ladder lands in phase 2</span>
  </div>
  <div class="ot-depth-grid">
    <span class="ot-depth-label">Bid qty</span>
    <span class="ot-depth-label">Bid</span>
    <span class="ot-depth-label">Ask</span>
    <span class="ot-depth-label">Ask qty</span>
    {#each Array(5) as _, i (i)}
      <span class="ot-depth-cell ot-depth-bid-qty">—</span>
      <span class="ot-depth-cell ot-depth-bid">—</span>
      <span class="ot-depth-cell ot-depth-ask">—</span>
      <span class="ot-depth-cell ot-depth-ask-qty">—</span>
    {/each}
  </div>
</div>

<style>
  .ot-depth {
    margin-top: 0.4rem;
    padding: 0.45rem 0.5rem;
    background: rgba(0,0,0,0.18);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 3px;
  }
  .ot-depth-h {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.4rem;
    font-size: 0.55rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.3rem;
  }
  .ot-depth-meta {
    color: #7e97b8;
    font-style: italic;
    font-size: 0.5rem;
    text-transform: none;
    letter-spacing: 0;
    opacity: 0.7;
  }
  .ot-depth-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 0.15rem 0.4rem;
    font-family: monospace;
    font-size: 0.62rem;
  }
  .ot-depth-label {
    font-size: 0.5rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    text-align: right;
  }
  .ot-depth-cell {
    text-align: right;
    color: #c8d8f0;
  }
  .ot-depth-bid     { color: #4ade80; }
  .ot-depth-bid-qty { color: #4ade80; opacity: 0.7; }
  .ot-depth-ask     { color: #f87171; }
  .ot-depth-ask-qty { color: #f87171; opacity: 0.7; }
</style>
