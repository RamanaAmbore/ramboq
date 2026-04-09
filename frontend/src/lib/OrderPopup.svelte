<script>
  import { onMount, tick } from 'svelte';
  import CommandBar from '$lib/CommandBar.svelte';
  import { orderGrammar, buildOrderPayload, previewSymbol, parseKiteSymbol, resolveInstrument, setQuoteLoadedCallback, getLtp } from '$lib/command/grammars/orders';
  import { placeOrder } from '$lib/api';
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
  let cmdFocused = $state(false);

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
    if (act === 'close') {
      tokens.push(String(lots));
    }
    const cmd = tokens.join(' ') + ' ';
    cmdBar?.setValue(cmd);
  }

  async function runParsed(p) {
    running = true;
    result = null;
    try {
      const payload = buildOrderPayload(p);
      const res = await placeOrder(payload);
      result = { status: '✓', message: `Order placed — ${res.order_id}` };
      onordered();
      setTimeout(onclose, 1500);
    } catch (e) {
      result = { status: '✗', message: e.message };
    } finally {
      running = false;
    }
  }

  function enrichPairs(pairs) {
    return pairs.map(p => {
      if (p.role === 'symbol' && p.status === 'filled' && p.value) {
        const l = getLtp(p.value);
        if (l) return { ...p, value: `${p.value}:${l}` };
      }
      return p;
    });
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
        <div class="font-semibold text-sm uppercase">
          <span class="{isLong ? 'text-green-700' : 'text-red-600'}">{isLong ? 'LONG' : 'SHORT'}</span>
          <span class="text-blue-700">{row.account}</span>
          <span class="text-slate-700">{parsed.symbol}</span>
        </div>
        <div class="text-[0.65rem] text-gray-600 uppercase mt-0.5">
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
      <button onclick={onclose} class="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
    </div>

    <!-- Action buttons -->
    <div class="flex gap-2 px-3 py-2">
      <button onclick={() => buildCommand('add')}
        class="flex-1 text-xs py-1.5 rounded-sm font-semibold border uppercase
          {action === 'add' ? 'border-green-500 bg-green-100 text-green-800' : 'border-gray-300 bg-gray-50 text-gray-600 hover:bg-gray-100'}">
        Add Position
      </button>
      <button onclick={() => buildCommand('close')}
        class="flex-1 text-xs py-1.5 rounded-sm font-semibold border uppercase
          {action === 'close' ? 'border-red-500 bg-red-100 text-red-800' : 'border-gray-300 bg-gray-50 text-gray-600 hover:bg-gray-100'}">
        Close Position
      </button>
    </div>

    <!-- Command bar — fixed height container to prevent layout shifts -->
    <div class="popup-cmd-area">
      <CommandBar
        bind:this={cmdBar}
        grammar={orderGrammar}
        context={action === 'close' ? { maxLots: lots } : {}}
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
            class="text-[0.6rem] py-0.5 px-3 rounded-sm font-semibold disabled:opacity-50 border
              {verb === 'BUY' ? 'border-green-500 bg-green-200 text-green-900 hover:bg-green-300' : 'border-red-500 bg-red-200 text-red-900 hover:bg-red-300'}">{verb}</button>
        </div>
      {/if}
    </div>

    <!-- Result -->
    {#if result}
      <div class="px-3 pb-2 text-xs {result.status === '✓' ? 'text-green-700' : 'text-red-600'}">
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
    background: rgba(0,0,0,0.4);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .popup-modal {
    background: #fff;
    border-radius: 0.5rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    width: min(95vw, 480px);
    max-height: 90vh;
    overflow: visible;
  }
  .popup-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 0.75rem 0.75rem 0.5rem;
    border-bottom: 1px solid #e2e8f0;
  }
  .popup-cmd-area {
    padding: 0.5rem 0.75rem 0.75rem;
    position: relative;
  }
</style>
