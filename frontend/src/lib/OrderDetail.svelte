<script>
  // Expandable order detail panel — appears inline between the order cards
  // grid and the log panel when a card is clicked. Shows full details plus
  // inline cancel / modify controls for open orders.

  import { modifyOrder, cancelOrder } from '$lib/api';

  /** @type {{ order: any|null, onclose: () => void, onchanged: () => void }} */
  let { order = null, onclose = () => {}, onchanged = () => {} } = $props();

  let busy  = $state(false);
  let error = $state('');
  let success = $state('');
  let modifyOpen = $state(false);
  let modPrice = $state('');
  let modQty   = $state('');

  $effect(() => {
    if (order) {
      modPrice = String(order.price ?? '');
      modQty = String(order.quantity ?? '');
      modifyOpen = false;
      error = ''; success = '';
    }
  });

  function fmt(v, dflt = '—') { return (v === null || v === undefined || v === '') ? dflt : v; }
  const isOpen = $derived(order && (order.status === 'OPEN' || order.status === 'TRIGGER PENDING'));

  async function doCancel() {
    if (!order) return;
    busy = true; error = ''; success = '';
    try {
      await cancelOrder(order.order_id, order.account);
      success = 'Cancelled';
      onchanged();
    } catch (e) { error = e.message; }
    finally { busy = false; }
  }

  async function doModify() {
    if (!order) return;
    const payload = {};
    if (modPrice !== '' && Number(modPrice) !== order.price) payload.price = Number(modPrice);
    if (modQty !== ''   && Number(modQty)   !== order.quantity) payload.quantity = Number(modQty);
    if (Object.keys(payload).length === 0) { error = 'no changes'; return; }
    payload.account = order.account;
    busy = true; error = ''; success = '';
    try {
      await modifyOrder(order.order_id, payload);
      success = 'Modified';
      modifyOpen = false;
      onchanged();
    } catch (e) { error = e.message; }
    finally { busy = false; }
  }
</script>

{#if order}
  <div class="order-detail rounded-lg border border-gray-300 bg-white p-3 mb-3">
    <div class="flex items-start justify-between mb-2">
      <div>
        <div class="text-xs font-bold text-primary">{order.tradingsymbol}
          <span class="ml-2 text-[0.6rem] font-medium {order.transaction_type === 'BUY' ? 'text-green-600' : 'text-red-600'}">{order.transaction_type} {order.quantity}</span>
          <span class="ml-2 text-[0.55rem] px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 uppercase">{order.status}</span>
        </div>
        <div class="text-[0.6rem] text-muted font-mono">{order.order_id}</div>
      </div>
      <button type="button" onclick={onclose} class="text-gray-400 hover:text-gray-700 text-sm">×</button>
    </div>

    <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-[0.6rem] text-text/80 mb-2">
      <div><span class="text-muted">Account:</span> {fmt(order.account)}</div>
      <div><span class="text-muted">Exchange:</span> {fmt(order.exchange)}</div>
      <div><span class="text-muted">Type:</span> {fmt(order.order_type)}</div>
      <div><span class="text-muted">Product:</span> {fmt(order.product)}</div>
      <div><span class="text-muted">Price:</span> {fmt(order.price)}</div>
      <div><span class="text-muted">Avg price:</span> {fmt(order.average_price)}</div>
      <div><span class="text-muted">Filled:</span> {fmt(order.filled_quantity, 0)} / {order.quantity}</div>
      <div><span class="text-muted">Pending:</span> {fmt(order.pending_quantity, 0)}</div>
      <div><span class="text-muted">Trigger:</span> {fmt(order.trigger_price)}</div>
      <div><span class="text-muted">Variety:</span> {fmt(order.variety)}</div>
    </div>

    {#if error}<div class="text-[0.6rem] text-red-600 mb-1">{error}</div>{/if}
    {#if success}<div class="text-[0.6rem] text-green-600 mb-1">{success}</div>{/if}

    {#if isOpen}
      <div class="flex gap-2 items-center">
        {#if !modifyOpen}
          <button type="button" onclick={() => modifyOpen = true}
            class="btn-secondary text-[0.6rem] py-0.5 px-2" disabled={busy}>Modify</button>
          <button type="button" onclick={doCancel}
            class="text-[0.6rem] text-red-600 border border-red-300 rounded py-0.5 px-2 hover:bg-red-50"
            disabled={busy}>{busy ? '…' : 'Cancel'}</button>
        {:else}
          <label class="text-[0.6rem] text-muted">price
            <input type="number" step="0.05" bind:value={modPrice}
              class="field-input text-[0.65rem] py-0.5 px-1 w-20 ml-1" />
          </label>
          <label class="text-[0.6rem] text-muted">qty
            <input type="number" bind:value={modQty}
              class="field-input text-[0.65rem] py-0.5 px-1 w-16 ml-1" />
          </label>
          <button type="button" onclick={doModify} disabled={busy}
            class="btn-primary text-[0.6rem] py-0.5 px-2">{busy ? '…' : 'Save'}</button>
          <button type="button" onclick={() => modifyOpen = false} disabled={busy}
            class="text-[0.6rem] text-muted hover:text-text">Cancel</button>
        {/if}
      </div>
    {/if}
  </div>
{/if}
