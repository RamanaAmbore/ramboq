<script>
  import CommandBar from '$lib/CommandBar.svelte';
  import { orderGrammar, buildOrderPayload, previewSymbol, parseKiteSymbol, setQuoteLoadedCallback, getLtp } from '$lib/command/grammars/orders';
  import { placeOrder } from '$lib/api';
  import { loadInstruments } from '$lib/data/instruments';
  import { loadAccounts } from '$lib/data/accounts';
  import { logTime } from '$lib/stores';

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
  const parsed = parseKiteSymbol(row.tradingsymbol);
  const ltp = getLtp(parsed.symbol) || row.close_price || row.average_price || 0;
  const qty = Math.abs(row.quantity);
  const lotSize = parsed.instType !== 'EQ' ? (qty > 0 ? qty : 1) : 0;

  // Ensure instruments/accounts loaded
  loadInstruments().catch(() => {});
  loadAccounts().catch(() => {});
  setQuoteLoadedCallback(() => cmdBar?.refresh());

  function buildCommand(act) {
    action = act;
    const verb = (act === 'add') === isLong ? 'buy' : 'sell';
    let cmd = `${verb} ${row.account}`;
    if (parsed.instType !== 'EQ') cmd += ` ${parsed.instType}`;
    cmd += ` ${parsed.symbol}`;
    if (parsed.strike) cmd += ` ${parsed.strike}`;
    if (parsed.expiry) cmd += ` ${parsed.expiry}`;
    if (act === 'close') cmd += ` ${qty}`;
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

<!-- Backdrop -->
<div class="popup-backdrop" onclick={onclose} role="presentation">
  <!-- Modal -->
  <div class="popup-modal" onclick={(e) => e.stopPropagation()} role="dialog">
    <!-- Header -->
    <div class="popup-header">
      <div class="flex items-center gap-2">
        <span class="font-semibold text-sm">
          <span class="{isLong ? 'text-green-700' : 'text-red-600'}">{isLong ? 'LONG' : 'SHORT'}</span>
          <span class="text-blue-700">{row.account}</span>
          <span class="text-slate-700">{row.tradingsymbol}</span>
        </span>
        <span class="text-xs text-gray-500">qty:{qty} ltp:{ltp}</span>
      </div>
      <button onclick={onclose} class="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
    </div>

    <!-- Action buttons -->
    <div class="flex gap-2 px-3 py-2">
      <button onclick={() => buildCommand('add')}
        class="flex-1 text-xs py-1.5 rounded-sm font-medium border
          {action === 'add' ? 'border-green-500 bg-green-100 text-green-800' : 'border-gray-300 bg-gray-50 text-gray-700 hover:bg-gray-100'}">
        Add Position
      </button>
      <button onclick={() => buildCommand('close')}
        class="flex-1 text-xs py-1.5 rounded-sm font-medium border
          {action === 'close' ? 'border-red-500 bg-red-100 text-red-800' : 'border-gray-300 bg-gray-50 text-gray-700 hover:bg-gray-100'}">
        Close Position
      </button>
    </div>

    <!-- Command bar -->
    <div class="px-3 pb-2 relative">
      <CommandBar
        bind:this={cmdBar}
        grammar={orderGrammar}
        rows={2}
        placeholder="Select Add or Close above"
        onsubmit={runParsed}
        previewFn={previewSymbol}
        {enrichPairs}
        disabled={running}
      />
      <div class="absolute bottom-3 right-4 flex gap-1 z-10">
        <button onclick={() => cmdBar?.submit()} disabled={running || !action}
          class="text-[0.6rem] py-0.5 px-2.5 rounded-sm border border-emerald-500 bg-emerald-200 text-emerald-900 hover:bg-emerald-300 font-semibold disabled:opacity-50">Submit</button>
        <button onclick={() => { cmdBar?.clear(); action = null; result = null; }}
          class="text-[0.6rem] py-0.5 px-2.5 rounded-sm border border-orange-300 bg-orange-50 text-orange-700 hover:bg-orange-100 font-medium">Clear</button>
      </div>
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
    overflow-y: auto;
  }
  .popup-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 0.75rem 0.5rem;
    border-bottom: 1px solid #e2e8f0;
  }
</style>
