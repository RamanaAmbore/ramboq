<script>
  // Live execution dashboard (/admin/live).
  //
  // Surfaces the execution.live.* flag toggles prominently — previously
  // buried in /admin/settings. Shows the effective execution state and
  // gives the operator a clear view of which actions hit the broker.

  import { onMount, onDestroy } from 'svelte';
  import { authStore, visibleInterval, branchLabel } from '$lib/stores';
  import { fetchLiveStatus, fetchAlgoOrdersRecent } from '$lib/api';
  import InfoHint from '$lib/InfoHint.svelte';

  let status   = $state(/** @type {any} */ ({}));
  let orders   = $state(/** @type {any[]} */ ([]));
  let error    = $state('');
  let loading  = $state(true);
  let refreshTeardown;

  async function load() {
    try {
      const [stat, ord] = await Promise.all([
        fetchLiveStatus(),
        fetchAlgoOrdersRecent(50, 'live').catch(() => []),
      ]);
      status = stat;
      orders = ord || [];
      error  = '';
    } catch (e) {
      if (!status?.branch) error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    load();
    refreshTeardown = visibleInterval(load, 5000);
  });
  onDestroy(() => refreshTeardown?.());

  const enabled = $derived(status?.enabled !== false);
  const branch  = $derived(branchLabel(status?.branch || ''));

  const effectiveLabel = $derived({
    dev_paper: 'DEV PAPER',
    paper:     'PAPER',
    shadow:    'SHADOW',
    live:      'LIVE',
    mixed:     'MIXED',
  }[status?.effective] || 'UNKNOWN');

  const effectiveColor = $derived({
    dev_paper: '#94a3b8',
    paper:     '#38bdf8',
    shadow:    '#fb923c',
    live:      '#ef4444',
    mixed:     '#fbbf24',
  }[status?.effective] || '#94a3b8');

  const flagNames = {
    cancel_order:           'Cancel Order',
    cancel_all_orders:      'Cancel All Orders',
    modify_order:           'Modify Order',
    place_order:            'Place Order',
    close_position:         'Close Position',
    chase_close_positions:  'Chase Close Positions',
  };
</script>

<svelte:head><title>Live Execution — RamboQuant</title></svelte:head>

<div class="sim-page">
  <header class="sim-header">
    <h2>
      Live Execution
      <InfoHint popup text="Controls which broker actions are live vs paper. Every action defaults to paper mode. Promote individual actions to live only after validating via Shadow mode." />
    </h2>
    <span class="badge-effective" style="color: {effectiveColor}; border-color: {effectiveColor}40; background: {effectiveColor}15">
      {effectiveLabel}
    </span>
  </header>

  {#if !enabled}
    <div class="sim-banner sim-banner-warn">
      Live execution is only available on <strong>prod</strong>. Current branch: <strong>{branch}</strong>. All actions are paper on dev.
    </div>
  {/if}

  {#if error}
    <div class="sim-banner sim-banner-error">{error}</div>
  {/if}

  <!-- Effective state summary -->
  <div class="sim-controls">
    <div class="live-grid">
      <div class="live-stat">
        <span class="sim-label">Branch</span>
        <span class="live-val">{branch}</span>
      </div>
      <div class="live-stat">
        <span class="sim-label">Paper trading mode</span>
        <span class="live-val" class:live-on={!status?.paper_trading_mode} class:live-off={status?.paper_trading_mode}>
          {status?.paper_trading_mode ? 'ON (all orders → paper)' : 'OFF'}
        </span>
      </div>
      <div class="live-stat">
        <span class="sim-label">Shadow mode</span>
        <span class="live-val" class:shadow-on={status?.shadow_mode}>
          {status?.shadow_mode ? 'ON (orders → shadow log)' : 'OFF'}
        </span>
      </div>
      <div class="live-stat">
        <span class="sim-label">Live actions</span>
        <span class="live-val" style="color: {status?.live_count > 0 ? '#ef4444' : '#94a3b8'}">
          {status?.live_count ?? 0} / {status?.total_flags ?? 6}
        </span>
      </div>
    </div>

    <!-- Per-action flags -->
    <h3 class="live-flags-title">Per-Action Flags</h3>
    <p class="live-flags-hint">
      Manage these in <a href="/admin/settings">Settings</a> → Execution section.
    </p>
    <div class="live-flags">
      {#if status?.live_flags}
        {#each Object.entries(status.live_flags) as [key, isLive]}
          <div class="live-flag-row">
            <span class="live-flag-name">{flagNames[key] || key}</span>
            <span class="live-flag-pill" class:flag-live={isLive} class:flag-paper={!isLive}>
              {isLive ? 'LIVE' : 'PAPER'}
            </span>
          </div>
        {/each}
      {/if}
    </div>
  </div>

  <!-- Recent live orders -->
  {#if orders.length > 0}
    <section class="sim-section">
      <h3>Recent Live Orders ({orders.length})</h3>
      <div class="sim-table-wrap">
        <table class="sim-table">
          <thead>
            <tr><th>ID</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Status</th><th>Broker ID</th><th>Time</th></tr>
          </thead>
          <tbody>
            {#each orders as o}
              <tr>
                <td>{o.id}</td>
                <td>{o.symbol}</td>
                <td class={o.transaction_type === 'BUY' ? 'sim-buy' : 'sim-sell'}>{o.transaction_type}</td>
                <td>{o.quantity}</td>
                <td class="sim-td-mono">{o.initial_price != null ? `₹${o.initial_price.toLocaleString()}` : '—'}</td>
                <td><span class="sim-pill sim-pill-live">{o.status}</span></td>
                <td class="sim-td-mono">{o.broker_order_id || '—'}</td>
                <td class="sim-td-mono">{o.created_at ? new Date(o.created_at).toLocaleTimeString() : '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {:else if !loading}
    <p class="sim-empty">No live orders yet.</p>
  {/if}
</div>

<style>
  .sim-page          { max-width: 72rem; margin: 0 auto; padding: 1.5rem 1rem; }
  .sim-header        { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .sim-header h2     { font-size: 1.25rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .badge-effective   { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em;
                        padding: 0.15rem 0.5rem; border-radius: 9999px; border: 1px solid; }

  .sim-banner        { padding: 0.5rem 0.75rem; border-radius: 0.375rem; font-size: 0.75rem; margin-bottom: 0.75rem; }
  .sim-banner-warn   { background: rgba(251,191,36,0.10); color: #fbbf24; border: 1px solid rgba(251,191,36,0.20); }
  .sim-banner-error  { background: rgba(239,68,68,0.10); color: #f87171; border: 1px solid rgba(239,68,68,0.20); }

  .sim-controls      { background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.12);
                        border-radius: 0.5rem; padding: 1rem; margin-bottom: 1rem; }

  .live-grid         { display: flex; gap: 2rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .live-stat         { display: flex; flex-direction: column; gap: 0.15rem; }
  .sim-label         { font-size: 0.6rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; }
  .live-val          { font-size: 0.85rem; color: #e2e8f0; font-weight: 600; }
  .live-on           { color: #4ade80; }
  .live-off          { color: #f87171; }
  .shadow-on         { color: #fb923c; }

  .live-flags-title  { font-size: 0.75rem; font-weight: 600; color: #cbd5e1; margin-bottom: 0.25rem; }
  .live-flags-hint   { font-size: 0.65rem; color: #64748b; margin-bottom: 0.5rem; }
  .live-flags-hint a { color: #38bdf8; text-decoration: underline; }
  .live-flags        { display: flex; flex-direction: column; gap: 0.35rem; }
  .live-flag-row     { display: flex; align-items: center; justify-content: space-between;
                        padding: 0.35rem 0.6rem; background: rgba(15,23,42,0.4);
                        border-radius: 0.375rem; border: 1px solid rgba(148,163,184,0.08); }
  .live-flag-name    { font-size: 0.72rem; color: #cbd5e1; }
  .live-flag-pill    { font-size: 0.6rem; font-weight: 700; padding: 0.1rem 0.45rem; border-radius: 9999px; }
  .flag-live         { color: #ef4444; background: rgba(239,68,68,0.12); }
  .flag-paper        { color: #38bdf8; background: rgba(56,189,248,0.10); }

  .sim-section       { margin-bottom: 1.5rem; }
  .sim-section h3    { font-size: 0.85rem; font-weight: 600; color: #cbd5e1; margin-bottom: 0.5rem; }
  .sim-table-wrap    { overflow-x: auto; }
  .sim-table         { width: 100%; border-collapse: collapse; font-size: 0.72rem; }
  .sim-table th      { text-align: left; padding: 0.35rem 0.5rem; color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,0.15); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.6rem; }
  .sim-table td      { padding: 0.3rem 0.5rem; color: #e2e8f0; border-bottom: 1px solid rgba(148,163,184,0.06); }
  .sim-td-mono       { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; }
  .sim-buy           { color: #38bdf8; }
  .sim-sell          { color: #fb923c; }
  .sim-pill          { font-size: 0.6rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 9999px; }
  .sim-pill-live     { color: #4ade80; background: rgba(74,222,128,0.12); }
  .sim-empty         { font-size: 0.75rem; color: #64748b; text-align: center; padding: 2rem; }
</style>
