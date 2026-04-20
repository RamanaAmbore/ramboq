<script>
  import { onMount, tick } from 'svelte';
  import CommandBar from '$lib/CommandBar.svelte';
  import { orderGrammar, previewSymbol, parseKiteSymbol, resolveInstrument, setQuoteLoadedCallback, getLtp, enrichOrderPairs, executeBuySell } from '$lib/command/grammars/orders';
  import { loadInstruments } from '$lib/data/instruments';
  import { loadAccounts } from '$lib/data/accounts';

  let {
    row,
    source = 'holdings',
    onclose = () => {},
    onordered = () => {},
  } = $props();

  let cmdBar;
  let running = $state(false);
  let result = $state(/** @type {{status:string, message:string}|null} */(null));
  let action = $state(/** @type {'add'|'close'|null} */(null));
  const isLong = row.quantity > 0;
  const totalQty = Math.abs(row.quantity);

  // These are set after instruments load
  let parsed = $state(/** @type {{instType:string, symbol:string, strike?:string, expiry?:string}} */({ instType: 'EQ', symbol: row.tradingsymbol }));
  let isFO = $state(false);
  let lotSize = $state(1);
  let lots = $state(totalQty);
  let ltp = $state(row.close_price || row.average_price || 0);

  const verb = $derived(
    action ? ((action === 'add') === isLong ? 'BUY' : 'SELL') : null
  );

  setQuoteLoadedCallback(() => cmdBar?.refresh());

  function _baseTokens() {
    const tokens = [row.account];
    if (isFO) tokens.push(parsed.instType);
    tokens.push(parsed.symbol);
    if (parsed.strike) tokens.push(parsed.strike);
    if (parsed.expiry) tokens.push(parsed.expiry);
    return tokens;
  }

  // After mount: load instruments, parse symbol, show chips
  onMount(async () => {
    await loadInstruments().catch(() => {});
    await loadAccounts().catch(() => {});

    // Now instruments are loaded — parse the symbol
    parsed = parseKiteSymbol(row.tradingsymbol);
    isFO = parsed.instType !== 'EQ';
    ltp = getLtp(parsed.symbol) || row.close_price || row.average_price || 0;
    try {
      const inst = resolveInstrument(parsed);
      lotSize = inst.ls || 1;
    } catch {}
    lots = isFO && lotSize > 1 ? Math.round(totalQty / lotSize) : totalQty;

    await tick();
    const cmd = `buy ${_baseTokens().join(' ')}`;
    cmdBar?.setValueQuiet(cmd);
  });

  function buildCommand(act) {
    action = act;
    const v = (act === 'add') === isLong ? 'buy' : 'sell';
    const tokens = [v, ..._baseTokens()];
    if (act === 'close' && lots <= 1) {
      // Single lot: pre-fill qty and skip to orderType
      tokens.push(String(lots));
    }
    // Multiple lots close or add: leave qty empty for user to choose
    const cmd = tokens.join(' ') + ' ';
    cmdBar?.setValue(cmd);
  }

  async function runParsed(p) {
    running = true;
    result = null;
    try {
      const { order_id } = await executeBuySell(p);
      result = { status: '✓', message: `Order placed — ${order_id}` };
      onordered();
      setTimeout(onclose, 1500);
    } catch (e) {
      result = { status: '✗', message: e.message };
    } finally {
      running = false;
    }
  }

  function enrichPairs(pairs, ctx) {
    return enrichOrderPairs(pairs, { ...ctx, _lotSize: lotSize });
  }

  function onKeydown(e) {
    if (e.key === 'Escape') onclose();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="popup-backdrop" onclick={onclose} role="presentation">
  <div class="popup-modal" onclick={(e) => e.stopPropagation()} role="dialog">
    <!-- Header -->
    <div class="popup-header">
      <div>
        <div class="popup-symbol">
          <span class="{isLong ? 'pos-long' : 'pos-short'}">{isLong ? 'LONG' : 'SHORT'}</span>
          <span class="pos-account">{row.account}</span>
          <span class="pos-name">{parsed.symbol}</span>
        </div>
        <div class="popup-meta">
          {#if isFO}
            <span>{parsed.instType}</span>
            {#if parsed.strike}<span> STRIKE:{parsed.strike}</span>{/if}
            {#if parsed.expiry}<span> EXP:{parsed.expiry}</span>{/if}
          {:else}
            <span>EQUITY</span>
          {/if}
          <span> QTY:{isFO && lotSize > 1 ? `${lots} (×${lotSize}=${totalQty})` : totalQty}</span>
          <span> LTP:{ltp}</span>
        </div>
      </div>
      <button onclick={onclose} class="popup-close">&times;</button>
    </div>

    <!-- Action buttons — each carries its own tinted idle state so the
         green-for-open / red-for-close semantics are legible before
         selection, not only after a click. -->
    <div class="popup-actions">
      <button onclick={() => buildCommand('add')}
        class="popup-action-btn {action === 'add' ? 'popup-action-add-active' : 'popup-action-add-idle'}">
        Add Position
      </button>
      <button onclick={() => buildCommand('close')}
        class="popup-action-btn {action === 'close' ? 'popup-action-close-active' : 'popup-action-close-idle'}">
        Close Position
      </button>
    </div>

    <!-- Command bar — fixed height container to prevent layout shifts -->
    <div class="popup-cmd-area">
      <CommandBar
        bind:this={cmdBar}
        grammar={orderGrammar}
        context={{ ...(action === 'close' ? { maxLots: lots } : {}), _lotSize: lotSize }}
        rows={2}
        placeholder="SELECT ADD OR CLOSE ABOVE"
        onsubmit={runParsed}
        previewFn={previewSymbol}
        {enrichPairs}
        disabled={running || !action}
        showHelp={false}
      />
      {#if verb}
        <div class="flex justify-end mt-1 px-1">
          <button onclick={() => cmdBar?.submit()} disabled={running}
            class="popup-submit-btn {verb === 'BUY' ? 'popup-submit-buy' : 'popup-submit-sell'}">{verb}</button>
        </div>
      {/if}
    </div>

    <!-- Result -->
    {#if result}
      <div class="popup-result {result.status === '✓' ? 'popup-result-ok' : 'popup-result-err'}">
        {result.status} {result.message}
      </div>
    {/if}
  </div>
</div>

<style>
  .popup-backdrop {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: rgba(0,0,0,0.6);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .popup-modal {
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    border: 1.5px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06);
    width: min(95vw, 480px);
    max-height: 90vh;
    overflow: visible;
  }
  .popup-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 0.65rem 0.75rem 0.5rem;
    background: rgba(10,16,32,0.5);
    border-bottom: 1px solid rgba(251,191,36,0.35);
    border-radius: 6px 6px 0 0;
  }
  .popup-symbol {
    font-size: 0.72rem;
    font-weight: 700;
    font-family: ui-monospace, monospace;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
  }
  .pos-long    { color: #4ade80; }
  .pos-short   { color: #f87171; }
  .pos-account { color: #fbbf24; }
  .pos-name    { color: #e2e8f0; }
  .popup-meta {
    font-size: 0.58rem;
    color: rgba(180,200,230,0.55);
    font-family: ui-monospace, monospace;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-top: 0.2rem;
  }
  .popup-close {
    background: transparent;
    border: none;
    color: rgba(180,200,230,0.5);
    font-size: 1.1rem;
    line-height: 1;
    cursor: pointer;
    padding: 0;
    transition: color 0.06s;
  }
  .popup-close:hover { color: #fbbf24; }
  .popup-actions {
    display: flex;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: transparent;
    border-bottom: 1px solid rgba(255,255,255,0.08);
  }
  .popup-action-btn {
    flex: 1;
    font-size: 0.65rem;
    padding: 0.35rem 0;
    border-radius: 3px;
    font-weight: 700;
    font-family: ui-monospace, monospace;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
    border: 1px solid;
    transition: background 0.08s, border-color 0.08s, color 0.08s;
  }
  /* Idle buttons carry their own semantic tint — green for Add (opens
     a position), red for Close (closes a position) — so the colour cue
     is legible before any click. Active state is a stronger saturation
     of the same hue. */
  .popup-action-add-idle {
    border-color: rgba(34,197,94,0.4);
    background: rgba(34,197,94,0.1);
    color: rgba(134,239,172,0.85);
  }
  .popup-action-add-idle:hover {
    background: rgba(34,197,94,0.18);
    border-color: rgba(34,197,94,0.6);
    color: #4ade80;
  }
  .popup-action-close-idle {
    border-color: rgba(239,68,68,0.4);
    background: rgba(239,68,68,0.1);
    color: rgba(252,165,165,0.85);
  }
  .popup-action-close-idle:hover {
    background: rgba(239,68,68,0.18);
    border-color: rgba(239,68,68,0.6);
    color: #f87171;
  }
  .popup-action-add-active   { border-color: rgba(34,197,94,0.75); background: rgba(34,197,94,0.28);  color: #4ade80; font-weight: 800; }
  .popup-action-close-active { border-color: rgba(239,68,68,0.75); background: rgba(239,68,68,0.28);  color: #f87171; font-weight: 800; }
  .popup-cmd-area {
    padding: 0.5rem 0.75rem 0.6rem;
    position: relative;
  }
  .popup-submit-btn {
    font-size: 0.6rem;
    padding: 0.25rem 0.9rem;
    border-radius: 2px;
    font-weight: 700;
    font-family: ui-monospace, monospace;
    letter-spacing: 0.08em;
    cursor: pointer;
    border: 1px solid;
    transition: background 0.06s;
  }
  .popup-submit-btn:disabled { opacity: 0.45; cursor: not-allowed; }
  .popup-submit-buy  { border-color: #22c55e; background: rgba(34,197,94,0.2);  color: #4ade80; }
  .popup-submit-buy:hover:not(:disabled)  { background: rgba(34,197,94,0.35); }
  .popup-submit-sell { border-color: #ef4444; background: rgba(239,68,68,0.2);  color: #f87171; }
  .popup-submit-sell:hover:not(:disabled) { background: rgba(239,68,68,0.35); }
  .popup-result {
    padding: 0.35rem 0.75rem 0.5rem;
    font-size: 0.65rem;
    font-family: ui-monospace, monospace;
    letter-spacing: 0.04em;
  }
  .popup-result-ok  { color: #4ade80; }
  .popup-result-err { color: #f87171; }
</style>
