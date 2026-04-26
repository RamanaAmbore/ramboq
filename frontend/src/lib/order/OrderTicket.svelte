<script>
  // Reusable order-placement ticket — single component for every
  // order op the platform needs (open / close / modify / repeat /
  // cancel) across every instrument (EQ / FUT / OPT / commodities).
  //
  // Phase 1 scope (this file): visual shell + DRAFT mode wired.
  // PAPER / LIVE submit paths come in phase 2 (backend endpoints)
  // and phase 3 (live broker wiring per the existing
  // execution.live.<action> setting flag).
  //
  // Calling pages own:
  //   - the symbol + side + qty defaults (passed as props)
  //   - the onSubmit handler that decides what DRAFT does (typically
  //     append to a local drafts[] array)
  //   - opening / closing the ticket via <{#if showTicket}> wrap
  //
  // The ticket itself owns:
  //   - field state (qty / type / price / trigger / variety …)
  //   - validation (price required when LIMIT, trigger when SL …)
  //   - mode toggle (DRAFT today; PAPER / LIVE in phase 2 / 3)
  //   - viewport-bounded modal positioning
  //
  // Component is intentionally "dumb" — it doesn't know about the
  // page's drafts array, the strategy state, the broker. Every
  // outcome routes through onSubmit(payload).

  import { onMount } from 'svelte';
  import OrderDepth from './OrderDepth.svelte';
  import { placeTicketOrder } from '$lib/api';

  /** @type {{
   *   symbol:    string,
   *   exchange?: string,
   *   side?:     'BUY' | 'SELL',
   *   action?:   'open' | 'close' | 'modify' | 'repeat',
   *   qty?:      number,
   *   product?:  'CNC' | 'MIS' | 'NRML',
   *   orderType?:'MARKET' | 'LIMIT' | 'SL' | 'SL-M',
   *   variety?:  'regular' | 'co' | 'bo' | 'amo' | 'iceberg',
   *   price?:    number,
   *   trigger?:  number,
   *   lotSize?:  number,
   *   onSubmit:  (payload: any) => void | Promise<void>,
   *   onClose:   () => void,
   * }} */
  let {
    symbol,
    exchange  = '',
    side      = /** @type {'BUY' | 'SELL'} */ ('BUY'),
    action    = /** @type {'open' | 'close' | 'modify' | 'repeat'} */ ('open'),
    qty       = 0,
    product   = /** @type {'CNC' | 'MIS' | 'NRML' | undefined} */ (undefined),
    orderType = /** @type {'MARKET' | 'LIMIT' | 'SL' | 'SL-M'} */ ('LIMIT'),
    variety   = /** @type {'regular' | 'co' | 'bo' | 'amo' | 'iceberg'} */ ('regular'),
    price     = /** @type {number | undefined} */ (undefined),
    trigger   = /** @type {number | undefined} */ (undefined),
    lotSize   = 0,
    onSubmit,
    onClose,
  } = $props();

  // Derived instrument kind from the tradingsymbol — simple suffix
  // match. Drives which fields show.
  const kind = $derived.by(() => {
    const s = (symbol || '').toUpperCase();
    if (/CE$/.test(s)) return 'CE';
    if (/PE$/.test(s)) return 'PE';
    if (/FUT$/.test(s)) return 'FUT';
    return 'EQ';
  });
  const isOption = $derived(kind === 'CE' || kind === 'PE');
  const isFuture = $derived(kind === 'FUT');
  const isEquity = $derived(kind === 'EQ');

  // Default product based on instrument when caller didn't specify.
  const productVal = $derived(product ?? (isEquity ? 'CNC' : 'NRML'));
  const productOptions = $derived(isEquity
    ? ['CNC', 'MIS']
    : ['NRML', 'MIS']);

  // Local form state — start from prop defaults, then operator edits.
  let _side    = $state(side);
  let _qty     = $state(qty || lotSize || 0);
  let _type    = $state(orderType);
  let _variety = $state(variety);
  let _price   = $state(price ?? '');
  let _trigger = $state(trigger ?? '');
  let _product = $state(productVal);
  let _mode    = $state(/** @type {'draft' | 'paper' | 'live'} */ ('draft'));

  // Field visibility derived from order type + variety.
  const showLimit   = $derived(_type === 'LIMIT' || _type === 'SL');
  const showTrigger = $derived(_type === 'SL' || _type === 'SL-M');

  // Validation — minimal phase-1 guard. Backend will validate again.
  const validationErr = $derived.by(() => {
    if (!Number(_qty)) return 'Qty required';
    if (showLimit   && !Number(_price))   return 'Limit price required';
    if (showTrigger && !Number(_trigger)) return 'Trigger price required';
    return '';
  });

  let submitting = $state(false);
  /** @type {string} */ let submitErr = $state('');

  async function submit() {
    if (validationErr) return;
    // LIVE confirmation — surfaces a hard-stop browser confirm so an
    // accidental click doesn't put real money on the wire. The
    // backend separately gates by branch + the
    // execution.live.place_order setting flag, but that's silent;
    // this dialog is the loud one.
    if (_mode === 'live') {
      const px = showLimit ? `@₹${_price}` : '@MARKET';
      const ok = typeof window !== 'undefined' && window.confirm(
        `Place LIVE broker order?\n\n${_side} ${_qty} ${symbol} ${px}\n\n` +
        `This is a REAL trade. Click Cancel to stop.`
      );
      if (!ok) return;
    }
    const payload = {
      mode:           _mode,
      action,
      symbol,
      exchange,
      side:           _side,
      quantity:       Number(_qty),
      product:        _product,
      order_type:     _type,
      variety:        _variety,
      price:          showLimit   ? Number(_price)   : null,
      trigger_price:  showTrigger ? Number(_trigger) : null,
    };
    submitting = true; submitErr = '';
    try {
      // PAPER + LIVE both route through the backend. DRAFT hands off
      // to the caller's onSubmit only (no API call).
      if (_mode === 'paper' || _mode === 'live') {
        await placeTicketOrder({
          mode:             _mode,
          side:             _side,
          tradingsymbol:    symbol,
          exchange:         exchange || 'NFO',
          quantity:         Number(_qty),
          product:          _product,
          order_type:       _type,
          variety:          _variety,
          price:            showLimit   ? Number(_price)   : null,
          trigger_price:    showTrigger ? Number(_trigger) : null,
        });
      }
      // Notify the caller — DRAFT mode appends to drafts[]; PAPER /
      // LIVE let the caller refresh its local view if it wants to.
      await onSubmit(payload);
      onClose();
    } catch (e) {
      submitErr = /** @type {any} */ (e)?.message || String(e);
    } finally {
      submitting = false;
    }
  }

  // Esc to close.
  onMount(() => {
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

<div class="ot-overlay" role="dialog" aria-modal="true" aria-label="Place order"
     onclick={onClose}>
  <div class="ot-modal" role="document" onclick={(e) => e.stopPropagation()}>
    <div class="ot-header">
      <div class="ot-symbol">
        <span class="ot-symbol-text">{symbol}</span>
        <span class="ot-symbol-meta">
          {exchange ? exchange + ' · ' : ''}
          {kind}{lotSize ? ' · lot ' + lotSize : ''}
          {action !== 'open' ? ' · ' + action.toUpperCase() : ''}
        </span>
      </div>
      <button type="button" class="ot-close" title="Close" aria-label="Close" onclick={onClose}>×</button>
    </div>

    <!-- Side toggle -->
    <div class="ot-row">
      <div class="ot-side-toggle">
        <button type="button" class="ot-side-btn ot-side-buy"  class:on={_side === 'BUY'}
                onclick={() => _side = 'BUY'}>BUY</button>
        <button type="button" class="ot-side-btn ot-side-sell" class:on={_side === 'SELL'}
                onclick={() => _side = 'SELL'}>SELL</button>
      </div>
      <div class="ot-qty-block">
        <label class="ot-label" for="ot-qty">Qty</label>
        <input id="ot-qty" type="number" class="ot-input ot-num"
               step={lotSize || 1}
               min="1"
               bind:value={_qty} />
        {#if lotSize}
          <span class="ot-meta">lot {lotSize}</span>
        {/if}
      </div>
    </div>

    <!-- Order type pills -->
    <div class="ot-row">
      <div class="ot-label-block">
        <label class="ot-label">Type</label>
        <div class="ot-pills">
          {#each ['MARKET', 'LIMIT', 'SL', 'SL-M'] as t}
            <button type="button" class="ot-pill" class:on={_type === t}
                    onclick={() => _type = /** @type {any} */ (t)}>{t}</button>
          {/each}
        </div>
      </div>
      <div class="ot-label-block">
        <label class="ot-label">Product</label>
        <div class="ot-pills">
          {#each productOptions as p}
            <button type="button" class="ot-pill" class:on={_product === p}
                    onclick={() => _product = /** @type {any} */ (p)}>{p}</button>
          {/each}
        </div>
      </div>
    </div>

    <!-- Price + Trigger (conditional) -->
    {#if showLimit || showTrigger}
      <div class="ot-row">
        {#if showLimit}
          <div class="ot-label-block">
            <label class="ot-label" for="ot-price">Limit price</label>
            <input id="ot-price" type="number" class="ot-input ot-num"
                   step="0.05"
                   bind:value={_price} />
          </div>
        {/if}
        {#if showTrigger}
          <div class="ot-label-block">
            <label class="ot-label" for="ot-trigger">Trigger</label>
            <input id="ot-trigger" type="number" class="ot-input ot-num"
                   step="0.05"
                   bind:value={_trigger} />
          </div>
        {/if}
      </div>
    {/if}

    <!-- Depth (read-only) -->
    <OrderDepth {symbol} {exchange} />

    <!-- Mode selector — only DRAFT wired in phase 1 -->
    <div class="ot-mode-row">
      <span class="ot-label">Mode</span>
      <div class="ot-mode-pills">
        <button type="button" class="ot-mode-pill ot-mode-draft" class:on={_mode === 'draft'}
                onclick={() => _mode = 'draft'}>DRAFT</button>
        <button type="button" class="ot-mode-pill ot-mode-paper" class:on={_mode === 'paper'}
                title="Routes through the prod paper engine — real bid/ask, no broker hit"
                onclick={() => _mode = 'paper'}>PAPER</button>
        <button type="button" class="ot-mode-pill ot-mode-live" class:on={_mode === 'live'}
                title="Real broker order — gated by branch (main only) + execution.live.place_order setting"
                onclick={() => _mode = 'live'}>LIVE</button>
      </div>
    </div>

    {#if validationErr}
      <div class="ot-err">{validationErr}</div>
    {/if}
    {#if submitErr}
      <div class="ot-err">{submitErr}</div>
    {/if}

    <div class="ot-footer">
      <button type="button" class="ot-cancel" onclick={onClose}>Cancel</button>
      <button type="button" class="ot-submit"
              class:ot-submit-buy={_side === 'BUY'}
              class:ot-submit-sell={_side === 'SELL'}
              disabled={!!validationErr || submitting}
              onclick={submit}>
        {submitting ? '…' : (_mode === 'draft' ? 'Save draft' : `Place ${_side.toLowerCase()}`)}
      </button>
    </div>
  </div>
</div>

<style>
  .ot-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
    padding: 1rem;
  }
  .ot-modal {
    background: linear-gradient(180deg, #273552 0%, #1d2a44 100%);
    border: 1px solid rgba(251,191,36,0.35);
    border-radius: 8px;
    padding: 0.85rem 1rem;
    width: min(28rem, calc(100vw - 2rem));
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    color: #c8d8f0;
    font-family: ui-monospace, monospace;
    box-shadow: 0 12px 32px rgba(0,0,0,0.6);
  }

  .ot-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
    padding-bottom: 0.55rem;
    border-bottom: 1px solid rgba(251,191,36,0.15);
    margin-bottom: 0.6rem;
  }
  .ot-symbol-text {
    font-size: 0.9rem;
    font-weight: 700;
    color: #e2e8f0;
    display: block;
  }
  .ot-symbol-meta {
    font-size: 0.6rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .ot-close {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.15);
    color: #c8d8f0;
    width: 1.55rem;
    height: 1.55rem;
    border-radius: 3px;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
  }
  .ot-close:hover { border-color: #f87171; color: #f87171; }

  .ot-row {
    display: flex;
    gap: 0.6rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
  }
  .ot-label-block { flex: 1 1 0; min-width: 0; }
  .ot-label {
    display: block;
    font-size: 0.55rem;
    color: #7e97b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.18rem;
  }

  /* Side toggle (BUY / SELL) */
  .ot-side-toggle {
    display: flex;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 3px;
    overflow: hidden;
  }
  .ot-side-btn {
    padding: 0.4rem 0.75rem;
    background: transparent;
    border: 0;
    color: #7e97b8;
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
    flex: 1 1 0;
  }
  .ot-side-buy.on  { background: rgba(34,197,94,0.18);  color: #4ade80; }
  .ot-side-sell.on { background: rgba(248,113,113,0.18); color: #f87171; }

  .ot-qty-block { display: flex; align-items: flex-end; gap: 0.4rem; flex: 1 1 0; }
  .ot-qty-block .ot-label { margin: 0 0 0.18rem; }
  .ot-qty-block .ot-meta { font-size: 0.55rem; color: #7e97b8; padding-bottom: 0.5rem; }

  .ot-input {
    width: 100%;
    background: #1d2a44;
    border: 1px solid rgba(251,191,36,0.25);
    border-radius: 3px;
    padding: 0.3rem 0.45rem;
    color: #e2e8f0;
    font-size: 0.7rem;
    font-family: monospace;
  }
  .ot-input:focus { outline: none; border-color: #fbbf24; }
  .ot-num { text-align: right; }

  /* Pill toggles (Type, Product, Variety) */
  .ot-pills { display: flex; gap: 0.2rem; flex-wrap: wrap; }
  .ot-pill {
    padding: 0.25rem 0.55rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 3px;
    color: #7e97b8;
    font-size: 0.6rem;
    font-weight: 600;
    cursor: pointer;
  }
  .ot-pill.on {
    background: rgba(251,191,36,0.18);
    border-color: rgba(251,191,36,0.55);
    color: #fbbf24;
  }

  /* Mode row */
  .ot-mode-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.7rem 0;
    padding-top: 0.5rem;
    border-top: 1px solid rgba(255,255,255,0.08);
  }
  .ot-mode-pills { display: flex; gap: 0.25rem; }
  .ot-mode-pill {
    padding: 0.2rem 0.55rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 3px;
    color: #7e97b8;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    cursor: pointer;
  }
  .ot-mode-pill:disabled { opacity: 0.4; cursor: not-allowed; }
  .ot-mode-draft.on { background: rgba(192,132,252,0.18); border-color: rgba(192,132,252,0.55); color: #c084fc; }
  .ot-mode-paper.on { background: rgba(125,211,252,0.18); border-color: rgba(125,211,252,0.55); color: #7dd3fc; }
  .ot-mode-live.on  { background: rgba(34,197,94,0.18);  border-color: rgba(34,197,94,0.55);  color: #4ade80; }

  .ot-err {
    background: rgba(248,113,113,0.10);
    border: 1px solid rgba(248,113,113,0.4);
    color: #fca5a5;
    padding: 0.35rem 0.55rem;
    border-radius: 3px;
    font-size: 0.62rem;
    margin: 0.4rem 0;
  }

  .ot-footer {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    padding-top: 0.6rem;
    border-top: 1px solid rgba(255,255,255,0.08);
  }
  .ot-cancel,
  .ot-submit {
    padding: 0.45rem 1rem;
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 700;
    cursor: pointer;
    border: 1px solid transparent;
  }
  .ot-cancel {
    background: transparent;
    border-color: rgba(255,255,255,0.18);
    color: #c8d8f0;
  }
  .ot-cancel:hover { border-color: rgba(255,255,255,0.35); }
  .ot-submit {
    background: #fbbf24;
    color: #0c1830;
  }
  .ot-submit-buy  { background: #4ade80; }
  .ot-submit-sell { background: #f87171; }
  .ot-submit:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
