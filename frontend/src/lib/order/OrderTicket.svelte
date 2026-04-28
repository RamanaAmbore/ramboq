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

  import { onMount, untrack } from 'svelte';
  import OrderDepth from './OrderDepth.svelte';
  import { placeTicketOrder, fetchAccounts, modifyOrder } from '$lib/api';

  /** @type {{
   *   symbol:    string,
   *   exchange?: string,
   *   side?:     'BUY' | 'SELL',
   *   action?:   'open' | 'close' | 'modify' | 'repeat' | 'cancel',
   *   qty?:      number,
   *   product?:  'CNC' | 'MIS' | 'NRML',
   *   orderType?:'MARKET' | 'LIMIT' | 'SL' | 'SL-M',
   *   variety?:  'regular' | 'co' | 'bo' | 'amo' | 'iceberg',
   *   price?:    number,
   *   trigger?:  number,
   *   lotSize?:  number,
   *   accounts?: string[],
   *   account?:  string,
   *   orderId?:  string,
   *   defaultMode?:    'draft' | 'paper' | 'live',
   *   availableModes?: Array<'draft' | 'paper' | 'live'>,
   *   onSubmit:  (payload: any) => void | Promise<void>,
   *   onClose:   () => void,
   * }} */
  let {
    symbol,
    exchange  = '',
    side      = /** @type {'BUY' | 'SELL'} */ ('BUY'),
    action    = /** @type {'open' | 'close' | 'modify' | 'repeat' | 'cancel'} */ ('open'),
    qty       = 0,
    product   = /** @type {'CNC' | 'MIS' | 'NRML' | undefined} */ (undefined),
    orderType = /** @type {'MARKET' | 'LIMIT' | 'SL' | 'SL-M'} */ ('LIMIT'),
    variety   = /** @type {'regular' | 'co' | 'bo' | 'amo' | 'iceberg'} */ ('regular'),
    price     = /** @type {number | undefined} */ (undefined),
    trigger   = /** @type {number | undefined} */ (undefined),
    lotSize   = 0,
    accounts  = /** @type {string[]} */ ([]),
    account   = '',
    // Existing-order id — required for action='modify'/'cancel' so
    // the submit path knows which order to mutate. Ignored for
    // action='open'.
    orderId   = '',
    // Initial mode pill the ticket opens on. Surfaces with no drafts
    // concept (PerformancePage row click) typically pass 'paper';
    // surfaces with a drafts panel (admin/options) keep 'draft'.
    defaultMode    = /** @type {'draft' | 'paper' | 'live'} */ ('draft'),
    // Which mode pills the operator can see. Pass ['paper','live']
    // to suppress DRAFT on surfaces where it has no meaning.
    availableModes = /** @type {Array<'draft'|'paper'|'live'>} */ (['draft', 'paper', 'live']),
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
  // Initial mode comes from `defaultMode` prop; if the caller's
  // chosen default isn't in `availableModes`, fall back to the
  // first allowed mode so a misconfigured caller doesn't open the
  // ticket on a hidden pill.
  let _mode    = $state(/** @type {'draft' | 'paper' | 'live'} */ (
    untrack(() => availableModes.includes(defaultMode)
      ? defaultMode
      : (availableModes[0] || 'draft'))
  ));
  // Chase toggle — when on, the backend's paper engine re-quotes
  // the limit each tick until the order fills (or hits the chase-
  // attempt cap). Default ON: industry-standard "fire and forget"
  // workflow. When off, the order rests at the initial limit and
  // only fills if the market naturally crosses it. MARKET / SL-M
  // ignore the toggle (no limit to chase).
  let _chase    = $state(true);
  // Chase aggressiveness — analogous to IBKR Adaptive Algo's
  // Patient / Normal / Urgent. 'high' = cross the spread (current
  // default behaviour); 'med' = midpoint peg; 'low' = passive,
  // sit on your own side and wait. Ignored when chase is off.
  let _chaseAgg = $state(/** @type {'low'|'med'|'high'} */ ('high'));

  // Auto-fill plumbing — the OrderDepth child polls the quote
  // every 1.2 s and bubbles each fresh response here via
  // onDepthQuote. We pre-fill the limit price with the marketable
  // side (BUY → ask, SELL → bid) so the operator doesn't have to
  // type a price every time. Once the operator types into the
  // field, `_priceTouched` flips true and we stop overwriting
  // their input. Flipping side resets to the new marketable side
  // unless they've typed.
  // Caller can pre-supply `price` to suppress auto-fill (e.g. a
  // close-position flow that wants the operator's last limit).
  // Untrack the read so we capture the initial value once — this
  // is intentional, the operator's edits flip the flag from there.
  let _priceTouched = $state(untrack(() => typeof price === 'number' && price > 0));
  /** @type {{ bid: number|null, ask: number|null, ltp: number|null } | null} */
  let _lastQuote = $state(null);

  function _autoFillFromQuote() {
    if (_priceTouched) return;
    if (_type !== 'LIMIT' && _type !== 'SL') return;
    if (!_lastQuote) return;
    const px = _side === 'BUY' ? _lastQuote.ask : _lastQuote.bid;
    // Fall back to LTP when the corresponding side has no depth
    // (off-hours, illiquid contracts) so the operator isn't left
    // with a blank field.
    const fallback = (px && px > 0) ? px : _lastQuote.ltp;
    if (fallback && fallback > 0) _price = fallback;
  }
  function onDepthQuote(/** @type {any} */ q) {
    _lastQuote = q ? {
      bid: q.bid ?? null,
      ask: q.ask ?? null,
      ltp: q.ltp ?? null,
    } : null;
    _autoFillFromQuote();
  }
  // Re-fill when the operator flips BUY ⇄ SELL or changes order
  // type (LIMIT ⇄ MARKET ⇄ SL — only LIMIT/SL show the price
  // field, but the helper guards that).
  $effect(() => {
    void _side; void _type;
    _autoFillFromQuote();
  });

  // Self-fetched real account list — backstop for when the caller
  // didn't (or couldn't) supply one. /api/accounts/ is jwt-guarded
  // but doesn't mask, so any signed-in user gets real account_ids
  // even if the page's positions came back masked.
  /** @type {string[]} */
  let _selfAccounts = $state([]);

  // Account list shown by the picker — caller's `accounts` prop
  // wins when populated; otherwise we use whatever we self-fetched.
  // A masked-only list (e.g. ZG####) is treated as empty so we
  // don't pre-pick an unroutable value.
  function _isRealAcct(/** @type {string|null|undefined} */ a) {
    return !!(a && !String(a).includes('#'));
  }
  const _accounts = $derived.by(() => {
    const fromProp = (accounts || []).filter(_isRealAcct);
    if (fromProp.length) return fromProp;
    return _selfAccounts.filter(_isRealAcct);
  });

  // Account — explicit operator choice for which Kite handle the
  // order routes through. Required for PAPER and LIVE; ignored in
  // DRAFT. Initialized empty and reactively seeded from the prop /
  // picker via the effect below — this lets a late-arriving caller
  // account list (the common race: /api/accounts/ resolves AFTER
  // the operator clicks +) auto-select once it lands. A masked
  // ZG#### is unroutable so we never seed it as a default.
  let _account = $state('');

  // Reactive seed:
  //   1. Caller-supplied `account` prop wins when it's a real value.
  //   2. Otherwise, single real account in the picker → pre-pick it.
  //   3. If the seeded value disappears from the picker (caller
  //      flips symbol / picker reloads), reset.
  $effect(() => {
    const propPick = _isRealAcct(account) ? String(account) : '';
    if (!_account && propPick && _accounts.includes(propPick)) {
      _account = propPick;
      return;
    }
    if (!_account && _accounts.length === 1) {
      _account = _accounts[0];
      return;
    }
    if (_account && _accounts.length && !_accounts.includes(_account)) {
      _account = _accounts.length === 1 ? _accounts[0] : '';
    }
  });

  // Field visibility derived from order type + variety.
  const showLimit   = $derived(_type === 'LIMIT' || _type === 'SL');
  const showTrigger = $derived(_type === 'SL' || _type === 'SL-M');

  // Validation — applied client-side; backend validates again before
  // hitting the broker. Lot-size check protects against rejections
  // for non-multiple quantities (NIFTY lot 50, BANKNIFTY 15, etc.).
  const validationErr = $derived.by(() => {
    if (!Number(_qty)) return 'Qty required';
    if (Number(_qty) <= 0) return 'Qty must be positive';
    if (lotSize > 0 && Number(_qty) % lotSize !== 0) {
      return `Qty must be a multiple of lot ${lotSize}`;
    }
    if (showLimit   && !Number(_price))   return 'Limit price required';
    if (showTrigger && !Number(_trigger)) return 'Trigger price required';
    if (Number(_price) < 0)   return 'Price must be ≥ 0';
    if (Number(_trigger) < 0) return 'Trigger must be ≥ 0';
    if ((_mode === 'paper' || _mode === 'live') && !_account) {
      return 'Pick an account';
    }
    return '';
  });

  let submitting = $state(false);
  /** @type {string} */ let submitErr = $state('');
  // Inline success state — shown briefly inside the modal after a
  // successful PAPER / LIVE submit so the operator sees confirmation
  // before the modal closes. Without it the modal disappears silently
  // and the operator has no idea whether the order actually landed.
  /** @type {string} */ let submitOk = $state('');

  async function submit() {
    if (validationErr) return;
    // ── action='modify' branch ─────────────────────────────────
    // Modifying an existing working order — bypass the
    // place/ticket pipeline entirely. Calls PUT /api/orders/{id}
    // with whatever fields the operator changed (price, qty,
    // order_type, trigger). Mode pills + chase + L/M/H don't
    // apply (those are place-time concerns). Account, symbol,
    // and side are locked in the UI.
    if (action === 'modify') {
      if (!orderId) {
        submitErr = 'Modify path requires an order id.';
        return;
      }
      submitting = true; submitErr = ''; submitOk = '';
      try {
        const payload = {
          account:       _account,
          quantity:      Number(_qty) || undefined,
          price:         showLimit   ? Number(_price)   : null,
          trigger_price: showTrigger ? Number(_trigger) : null,
          order_type:    _type,
          variety:       _variety,
        };
        await modifyOrder(orderId, payload);
        submitOk = `Order #${orderId} modified`;
        // Surface the diff to the caller so the page can refresh
        // its order list / log the change.
        await onSubmit({ action: 'modify', orderId, ...payload });
        setTimeout(onClose, 1200);
      } catch (e) {
        submitErr = /** @type {any} */ (e)?.message || String(e);
      } finally {
        submitting = false;
      }
      return;
    }

    // LIVE confirmation — surfaces a hard-stop browser confirm so an
    // accidental click doesn't put real money on the wire. The
    // backend separately gates by branch + the
    // execution.live.place_order setting flag, but that's silent;
    // this dialog is the loud one. Account is included so the
    // operator can verify the right Kite handle BEFORE confirming.
    if (_mode === 'live') {
      const px = showLimit ? `@₹${_price} LIMIT` : '@MARKET';
      const ok = typeof window !== 'undefined' && window.confirm(
        `Place LIVE broker order?\n\n` +
        `  ${_side} ${_qty} ${symbol}\n` +
        `  ${px}\n` +
        `  Account: ${_account}\n` +
        `  Product: ${_product}\n\n` +
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
      account:        _account,
      // Chase only carries on price-bearing order types; MARKET /
      // SL-M ignore it on the backend, but we still ship the flag
      // so the AlgoOrder row records the intent for replay.
      chase:               showLimit ? _chase : false,
      chase_aggressiveness: showLimit && _chase ? _chaseAgg : 'high',
    };
    submitting = true; submitErr = ''; submitOk = '';
    try {
      // PAPER + LIVE both route through the backend. DRAFT hands off
      // to the caller's onSubmit only (no API call).
      if (_mode === 'paper' || _mode === 'live') {
        const resp = await placeTicketOrder({
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
          account:          _account,
          chase:                showLimit ? _chase : false,
          chase_aggressiveness: showLimit && _chase ? _chaseAgg : 'high',
        });
        // Show inline confirmation so the operator sees the order
        // landed before the modal closes. Backend returns
        // {order_id, mode, status, detail} — surface order_id +
        // mode for clarity.
        const oid = resp?.order_id || '?';
        submitOk = `${(_mode || '').toUpperCase()} order placed · #${oid}`;
      }
      // Notify the caller — DRAFT mode appends to drafts[]; PAPER /
      // LIVE let the caller refresh its local view if it wants to.
      await onSubmit(payload);
      // DRAFT closes immediately; PAPER / LIVE pause briefly so the
      // operator reads the success line before the modal disappears.
      if (_mode === 'draft') {
        onClose();
      } else {
        setTimeout(onClose, 1400);
      }
    } catch (e) {
      submitErr = /** @type {any} */ (e)?.message || String(e);
    } finally {
      submitting = false;
    }
  }

  // Esc to close + backstop /api/accounts/ self-fetch. Runs when
  // the caller didn't supply real accounts (the chain picker pre-
  // /accounts/ load, the per-row buttons before the page poll
  // landed, generic order surfaces that don't know about Kite at
  // all). /accounts is jwt-guarded but doesn't mask, so we get the
  // real account_ids for any signed-in operator. 401 / 403 leaves
  // _selfAccounts empty and the picker collapses gracefully.
  onMount(() => {
    const onKey = (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const propRealCount = (accounts || []).filter(_isRealAcct).length;
    if (!propRealCount) {
      fetchAccounts()
        .then(/** @param {any} r */ (r) => {
          const list = (r?.accounts || [])
            .map(/** @param {any} a */ (a) => String(a?.account_id || ''))
            .filter(Boolean);
          _selfAccounts = list;
        })
        .catch(() => { /* silent — picker just stays empty */ });
    }
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

    <!-- Side toggle — locked when modifying an existing order
         (Kite doesn't support flipping side on a working order;
         the operator has to cancel + re-place). Click is a no-op
         in that case + the button visibly reads as disabled. -->
    <div class="ot-row">
      <div class="ot-side-toggle" class:ot-locked={action === 'modify'}>
        <button type="button" class="ot-side-btn ot-side-buy"  class:on={_side === 'BUY'}
                disabled={action === 'modify'}
                onclick={() => action !== 'modify' && (_side = 'BUY')}>BUY</button>
        <button type="button" class="ot-side-btn ot-side-sell" class:on={_side === 'SELL'}
                disabled={action === 'modify'}
                onclick={() => action !== 'modify' && (_side = 'SELL')}>SELL</button>
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

    <!-- Account selector — required for PAPER + LIVE so the operator
         picks WHICH Kite handle the order routes to. Reads from the
         derived `_accounts` list so a late-arriving caller account
         list (or the self-fetch backstop) auto-populates without
         remounting the ticket. -->
    {#if _accounts.length}
      <div class="ot-row">
        <div class="ot-label-block">
          <label class="ot-label" for="ot-account">Account</label>
          {#if _accounts.length === 1}
            <input id="ot-account" type="text" class="ot-input ot-account-readonly"
                   value={_account} readonly />
          {:else}
            <select id="ot-account" class="ot-input ot-account-select"
                    bind:value={_account}>
              <option value="" disabled>Pick an account…</option>
              {#each _accounts as a}
                <option value={a}>{a}</option>
              {/each}
            </select>
          {/if}
        </div>
      </div>
    {/if}

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
            <label class="ot-label" for="ot-price">
              Limit price
              {#if !_priceTouched && _price !== '' && _price != null}
                <span class="ot-price-auto" title="Pre-filled from {_side === 'BUY' ? 'top ask' : 'top bid'} on the depth ladder. Edit to override; click ↺ to re-arm auto-fill.">auto</span>
              {/if}
              {#if _priceTouched && _lastQuote}
                <button type="button" class="ot-price-reset"
                        title="Re-arm auto-fill — restore {_side === 'BUY' ? 'top ask' : 'top bid'}"
                        aria-label="Reset price to depth"
                        onclick={() => { _priceTouched = false; _autoFillFromQuote(); }}>↺</button>
              {/if}
            </label>
            <input id="ot-price" type="number" class="ot-input ot-num"
                   step="0.05"
                   bind:value={_price}
                   oninput={() => { _priceTouched = true; }} />
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

    <!-- Depth — also bubbles its quote tick up via `onQuote` so the
         ticket can keep the limit price aligned with the marketable
         side (BUY → top ask, SELL → top bid). Operator edits to the
         price field freeze the auto-fill until they hit the ↺ button
         next to the field label. -->
    <OrderDepth {symbol} {exchange} onQuote={onDepthQuote} />

    <!-- Mode selector + chase — only relevant when *placing* a new
         order. action='modify' bypasses the place-pipeline entirely
         (PUT /api/orders/{id} hits the broker directly), so neither
         mode nor chase apply there; the whole row is hidden. -->
    {#if action !== 'modify'}
    <div class="ot-mode-row">
      <span class="ot-label">Mode</span>
      <div class="ot-mode-pills">
        {#if availableModes.includes('draft')}
          <button type="button" class="ot-mode-pill ot-mode-draft" class:on={_mode === 'draft'}
                  onclick={() => _mode = 'draft'}>DRAFT</button>
        {/if}
        {#if availableModes.includes('paper')}
          <button type="button" class="ot-mode-pill ot-mode-paper" class:on={_mode === 'paper'}
                  title="Routes through the prod paper engine — real bid/ask, no broker hit"
                  onclick={() => _mode = 'paper'}>PAPER</button>
        {/if}
        {#if availableModes.includes('live')}
          <button type="button" class="ot-mode-pill ot-mode-live" class:on={_mode === 'live'}
                  title="Real broker order — gated by branch (prod only) + execution.live.place_order setting"
                  onclick={() => _mode = 'live'}>LIVE</button>
        {/if}
      </div>

      <!-- Chase toggle — only meaningful for limit-bearing orders.
           When ON, the engine re-quotes the limit each tick until
           the order fills. The aggressiveness pills below set HOW
           it re-quotes:
             L (patient) — sit on your own side, wait for the market
             M (balanced) — peg to the midpoint
             H (urgent) — cross the spread to take liquidity
           Mirrors IBKR's Adaptive Algo Patient / Normal / Urgent. -->
      {#if showLimit}
        <label class="ot-chase-toggle"
               title={_chase
                 ? 'Chase ON — re-quote the limit each tick until filled'
                 : 'Chase OFF — order rests at the initial limit; fills only if the market crosses'}>
          <input type="checkbox" bind:checked={_chase} />
          <span class="ot-chase-label" class:on={_chase}>CHASE</span>
        </label>
        {#if _chase}
          <div class="ot-chase-agg" role="group" aria-label="Chase aggressiveness">
            <button type="button"
                    class="ot-chase-agg-pill ot-chase-agg-low"
                    class:on={_chaseAgg === 'low'}
                    title="Low — patient. SELL pegs to ASK, BUY pegs to BID. Order rests on your own side; fills only if the market lifts it."
                    onclick={() => _chaseAgg = 'low'}>L</button>
            <button type="button"
                    class="ot-chase-agg-pill ot-chase-agg-med"
                    class:on={_chaseAgg === 'med'}
                    title="Medium — peg to midpoint of bid+ask. Fills when the inside moves halfway in your favour."
                    onclick={() => _chaseAgg = 'med'}>M</button>
            <button type="button"
                    class="ot-chase-agg-pill ot-chase-agg-high"
                    class:on={_chaseAgg === 'high'}
                    title="High — urgent. SELL pegs to BID, BUY pegs to ASK. Crosses the spread to take liquidity on the next tick."
                    onclick={() => _chaseAgg = 'high'}>H</button>
          </div>
        {/if}
      {/if}
    </div>
    {/if}

    {#if validationErr}
      <div class="ot-err">{validationErr}</div>
    {/if}
    {#if submitErr}
      <div class="ot-err">{submitErr}</div>
    {/if}
    {#if submitOk}
      <div class="ot-ok">✓ {submitOk}</div>
    {/if}

    <div class="ot-footer">
      <button type="button" class="ot-cancel" onclick={onClose}>Cancel</button>
      <button type="button" class="ot-submit"
              class:ot-submit-buy={_side === 'BUY'}
              class:ot-submit-sell={_side === 'SELL'}
              disabled={!!validationErr || submitting}
              onclick={submit}>
        {#if submitting}…{:else if action === 'modify'}Modify{orderId ? ' · #' + orderId : ''}{:else if _mode === 'draft'}Save draft{:else if action === 'close'}Close · {_side.toLowerCase()}{:else}Place {_side.toLowerCase()}{/if}
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

  /* "auto" chip next to the Limit price label — flags that the
     value is being fed from the depth ladder and the operator
     hasn't typed anything yet. Tiny pill so it doesn't compete
     with the input below. */
  .ot-price-auto {
    display: inline-block;
    margin-left: 0.4rem;
    padding: 0 0.3rem;
    border-radius: 2px;
    background: rgba(74,222,128,0.15);
    border: 1px solid rgba(74,222,128,0.45);
    color: #4ade80;
    font-size: 0.5rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    vertical-align: 1px;
  }
  /* Re-arm-auto button — visible only after the operator has
     touched the price field. Click → reset _priceTouched and
     re-fill from the latest quote. */
  .ot-price-reset {
    margin-left: 0.4rem;
    padding: 0 0.35rem;
    height: 0.95rem;
    line-height: 1;
    border-radius: 2px;
    border: 1px solid rgba(125,211,252,0.55);
    background: rgba(125,211,252,0.10);
    color: #7dd3fc;
    font-size: 0.6rem;
    font-weight: 700;
    cursor: pointer;
    vertical-align: 1px;
  }
  .ot-price-reset:hover {
    background: rgba(125,211,252,0.22);
    border-color: rgba(125,211,252,0.85);
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
  /* Locked side toggle (action='modify') — Kite doesn't support
     flipping side on a working order; the button visibly reads as
     disabled and the click is a no-op. */
  .ot-side-toggle.ot-locked .ot-side-btn:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

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

  /* Chase toggle — pushed to the row's far right (margin-left: auto)
     so it sits opposite the mode pills. Native checkbox + label
     pill; the label tints amber when ON to match the rest of the
     ticket's "active state" treatment. */
  .ot-chase-toggle {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    cursor: pointer;
    user-select: none;
  }
  .ot-chase-toggle input[type="checkbox"] {
    accent-color: #fbbf24;
    width: 0.85rem;
    height: 0.85rem;
    cursor: pointer;
  }
  .ot-chase-label {
    font-family: monospace;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    border: 1px solid rgba(255,255,255,0.12);
    color: #7e97b8;
    background: rgba(255,255,255,0.04);
  }
  .ot-chase-label.on {
    background: rgba(251,191,36,0.18);
    border-color: rgba(251,191,36,0.55);
    color: #fbbf24;
  }

  /* Aggressiveness segment — three square pills (L · M · H) sitting
     immediately right of the CHASE checkbox. Color graduates from
     sky-blue (low/patient) → amber (med) → red (high/urgent) so
     the operator's eye lands on the urgency level without reading
     the glyph. Only the active pill carries the filled bg. */
  .ot-chase-agg {
    display: inline-flex;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 3px;
    overflow: hidden;
    margin-left: 0.3rem;
  }
  .ot-chase-agg-pill {
    width: 1.4rem;
    height: 1.1rem;
    padding: 0;
    border: 0;
    border-right: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.04);
    color: #7e97b8;
    font-family: monospace;
    font-size: 0.6rem;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.1s, color 0.1s, border-color 0.1s;
  }
  .ot-chase-agg-pill:last-child { border-right: 0; }
  .ot-chase-agg-pill:hover { color: #c8d8f0; background: rgba(255,255,255,0.08); }
  .ot-chase-agg-low.on  { background: rgba(125,211,252,0.20); color: #7dd3fc; }
  .ot-chase-agg-med.on  { background: rgba(251,191,36,0.20);  color: #fbbf24; }
  .ot-chase-agg-high.on { background: rgba(248,113,113,0.20); color: #f87171; }

  .ot-err {
    background: rgba(248,113,113,0.10);
    border: 1px solid rgba(248,113,113,0.4);
    color: #fca5a5;
    padding: 0.35rem 0.55rem;
    border-radius: 3px;
    font-size: 0.62rem;
    margin: 0.4rem 0;
  }
  .ot-ok {
    background: rgba(34,197,94,0.10);
    border: 1px solid rgba(34,197,94,0.45);
    color: #4ade80;
    padding: 0.35rem 0.55rem;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 700;
    margin: 0.4rem 0;
  }
  .ot-account-readonly {
    color: #c8d8f0;
    background: rgba(255,255,255,0.04);
    cursor: default;
  }
  .ot-account-select {
    appearance: none;
    -webkit-appearance: none;
    cursor: pointer;
    background-image:
      linear-gradient(45deg, transparent 50%, #7e97b8 50%),
      linear-gradient(135deg, #7e97b8 50%, transparent 50%);
    background-position:
      calc(100% - 12px) 50%,
      calc(100% - 8px)  50%;
    background-size: 4px 4px, 4px 4px;
    background-repeat: no-repeat;
    padding-right: 1.4rem;
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
