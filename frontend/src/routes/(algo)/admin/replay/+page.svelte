<script>
  // Replay / Backtest page (/admin/replay).
  //
  // Feeds historical Kite OHLCV candles through the agent engine at an
  // accelerated playback rate. Available on both dev and prod branches.

  import { onMount, onDestroy } from 'svelte';
  import { authStore, clientTimestamp, visibleInterval, branchLabel } from '$lib/stores';
  import {
    fetchReplayStatus, startReplay, stopReplay,
    fetchReplayResults, fetchReplayOrders, clearReplayData,
  } from '$lib/api';
  import InfoHint from '$lib/InfoHint.svelte';

  let status       = $state(/** @type {any} */ ({}));
  let results      = $state(/** @type {any[]} */ ([]));
  let orders       = $state(/** @type {any[]} */ ([]));
  let error        = $state('');
  let loading      = $state(true);
  let starting     = $state(false);
  let refreshTeardown;

  // Form state
  let symbols    = $state('');
  let dateFrom   = $state('');
  let dateTo     = $state('');
  let interval   = $state('5minute');
  let rateMs     = $state(100);
  let agentIds   = $state('');
  let spreadPct  = $state(0.10);

  async function load() {
    try {
      const [stat, res, ord] = await Promise.all([
        fetchReplayStatus(),
        fetchReplayResults().catch(() => []),
        fetchReplayOrders(50).catch(() => []),
      ]);
      status  = stat;
      results = res || [];
      orders  = ord || [];
      error   = '';
    } catch (e) {
      if (!status?.branch) error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    load();
    refreshTeardown = visibleInterval(load, 3000);
  });
  onDestroy(() => refreshTeardown?.());

  async function handleStart() {
    error = '';
    starting = true;
    try {
      const symList = symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
      const aidList = agentIds.trim()
        ? agentIds.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n))
        : undefined;
      await startReplay({
        symbols: symList,
        date_from: dateFrom,
        date_to: dateTo,
        interval,
        rate_ms: rateMs,
        agent_ids: aidList,
        spread_pct: spreadPct,
      });
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      starting = false;
    }
  }

  async function handleStop() {
    try {
      await stopReplay();
      await load();
    } catch (e) {
      error = e.message;
    }
  }

  async function handleClear() {
    if (!confirm('Delete all replay orders and events?')) return;
    try {
      await clearReplayData();
      await load();
    } catch (e) {
      error = e.message;
    }
  }

  const enabled = $derived(status?.enabled !== false);
  const branch  = $derived(branchLabel(status?.branch || ''));
</script>

<svelte:head><title>Replay / Backtest — RamboQuant</title></svelte:head>

<div class="sim-page">
  <header class="sim-header">
    <h2>
      Replay / Backtest
      <InfoHint popup text="Feed historical market data through the agent engine at accelerated speed. Test whether agents would have fired on past dates without waiting for the market." />
    </h2>
    {#if status?.active}
      <span class="badge badge-replay">REPLAYING</span>
    {/if}
  </header>

  {#if !enabled}
    <div class="sim-banner sim-banner-warn">
      Replay is disabled on <strong>{branch}</strong>. Enable <code>cap_in_{branch === 'prod' ? 'prod' : 'dev'}.replay</code> in backend_config.yaml.
    </div>
  {/if}

  {#if error}
    <div class="sim-banner sim-banner-error">{error}</div>
  {/if}

  <!-- Control panel -->
  <div class="sim-controls">
    <div class="sim-form-row">
      <label>
        <span class="sim-label">Symbols (comma-sep)</span>
        <input type="text" bind:value={symbols} placeholder="NIFTY25MAYFUT, BANKNIFTY25MAYFUT" class="sim-input" />
      </label>
    </div>
    <div class="sim-form-row">
      <label>
        <span class="sim-label">From</span>
        <input type="date" bind:value={dateFrom} class="sim-input" />
      </label>
      <label>
        <span class="sim-label">To</span>
        <input type="date" bind:value={dateTo} class="sim-input" />
      </label>
      <label>
        <span class="sim-label">Interval</span>
        <select bind:value={interval} class="sim-input">
          <option value="minute">1 min</option>
          <option value="5minute">5 min</option>
          <option value="15minute">15 min</option>
          <option value="day">Day</option>
        </select>
      </label>
    </div>
    <div class="sim-form-row">
      <label>
        <span class="sim-label">Playback rate (ms)</span>
        <input type="number" bind:value={rateMs} min="10" max="5000" step="10" class="sim-input sim-input-sm" />
      </label>
      <label>
        <span class="sim-label">Spread %</span>
        <input type="number" bind:value={spreadPct} min="0" max="5" step="0.01" class="sim-input sim-input-sm" />
      </label>
      <label>
        <span class="sim-label">Agent IDs (opt)</span>
        <input type="text" bind:value={agentIds} placeholder="1, 3, 7" class="sim-input sim-input-sm" />
      </label>
    </div>
    <div class="sim-btn-row">
      {#if !status?.active}
        <button class="sim-btn sim-btn-start" onclick={handleStart} disabled={!enabled || starting || !symbols.trim() || !dateFrom || !dateTo}>
          {starting ? 'Starting…' : 'Start Replay'}
        </button>
      {:else}
        <button class="sim-btn sim-btn-stop" onclick={handleStop}>Stop</button>
      {/if}
      <button class="sim-btn sim-btn-clear" onclick={handleClear} disabled={status?.active}>Clear</button>
    </div>
  </div>

  <!-- Progress -->
  {#if status?.active}
    <div class="sim-progress">
      <div class="sim-progress-bar">
        <div class="sim-progress-fill" style="width: {status.total_ticks ? (status.tick_index / status.total_ticks * 100) : 0}%"></div>
      </div>
      <span class="sim-progress-label">
        Tick {status.tick_index} / {status.total_ticks}
        {#if status.date_from && status.date_to}
          &nbsp;·&nbsp; {status.date_from} → {status.date_to}
        {/if}
      </span>
    </div>
  {/if}

  <!-- Results -->
  {#if results.length > 0}
    <section class="sim-section">
      <h3>Agent Fires ({results.length})</h3>
      <div class="sim-table-wrap">
        <table class="sim-table">
          <thead>
            <tr><th>Tick</th><th>Time</th><th>Agent</th><th>Event</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {#each results as r}
              <tr>
                <td>{r.tick_index}</td>
                <td class="sim-td-mono">{r.timestamp || '—'}</td>
                <td>{r.agent_slug}</td>
                <td>{r.event_type}</td>
                <td class="sim-td-detail">{r.detail || '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  <!-- Recent orders -->
  {#if orders.length > 0}
    <section class="sim-section">
      <h3>Replay Orders ({orders.length})</h3>
      <div class="sim-table-wrap">
        <table class="sim-table">
          <thead>
            <tr><th>ID</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Status</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {#each orders as o}
              <tr>
                <td>{o.id}</td>
                <td>{o.symbol}</td>
                <td class={o.side === 'BUY' ? 'sim-buy' : 'sim-sell'}>{o.side}</td>
                <td>{o.quantity}</td>
                <td class="sim-td-mono">{o.initial_price != null ? `₹${o.initial_price.toLocaleString()}` : '—'}</td>
                <td><span class="sim-pill sim-pill-replay">{o.status}</span></td>
                <td class="sim-td-detail">{o.detail || '—'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}
</div>

<style>
  /* Reuse the simulator page's design tokens */
  .sim-page          { max-width: 72rem; margin: 0 auto; padding: 1.5rem 1rem; }
  .sim-header        { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .sim-header h2     { font-size: 1.25rem; font-weight: 700; color: #e2e8f0; margin: 0; }
  .badge-replay      { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em;
                        padding: 0.15rem 0.5rem; border-radius: 9999px;
                        color: #4ade80; background: rgba(74,222,128,0.12); border: 1px solid rgba(74,222,128,0.25); }

  .sim-banner        { padding: 0.5rem 0.75rem; border-radius: 0.375rem; font-size: 0.75rem; margin-bottom: 0.75rem; }
  .sim-banner-warn   { background: rgba(251,191,36,0.10); color: #fbbf24; border: 1px solid rgba(251,191,36,0.20); }
  .sim-banner-error  { background: rgba(239,68,68,0.10); color: #f87171; border: 1px solid rgba(239,68,68,0.20); }

  .sim-controls      { background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.12);
                        border-radius: 0.5rem; padding: 1rem; margin-bottom: 1rem; }
  .sim-form-row      { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.75rem; }
  .sim-label         { display: block; font-size: 0.65rem; color: #94a3b8; margin-bottom: 0.2rem; text-transform: uppercase; letter-spacing: 0.04em; }
  .sim-input         { background: rgba(15,23,42,0.8); border: 1px solid rgba(148,163,184,0.20);
                        border-radius: 0.375rem; padding: 0.35rem 0.5rem; color: #e2e8f0;
                        font-size: 0.8rem; min-width: 10rem; }
  .sim-input-sm      { min-width: 6rem; }
  .sim-input:focus   { outline: none; border-color: rgba(74,222,128,0.5); }

  .sim-btn-row       { display: flex; gap: 0.5rem; margin-top: 0.25rem; }
  .sim-btn           { padding: 0.4rem 1rem; border-radius: 0.375rem; font-size: 0.75rem; font-weight: 600;
                        cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
  .sim-btn:disabled  { opacity: 0.4; cursor: not-allowed; }
  .sim-btn-start     { background: rgba(74,222,128,0.15); color: #4ade80; border-color: rgba(74,222,128,0.3); }
  .sim-btn-start:hover:not(:disabled) { background: rgba(74,222,128,0.25); }
  .sim-btn-stop      { background: rgba(239,68,68,0.15); color: #f87171; border-color: rgba(239,68,68,0.3); }
  .sim-btn-clear     { background: rgba(148,163,184,0.10); color: #94a3b8; border-color: rgba(148,163,184,0.2); }

  .sim-progress      { margin-bottom: 1rem; }
  .sim-progress-bar  { height: 6px; background: rgba(148,163,184,0.15); border-radius: 3px; overflow: hidden; }
  .sim-progress-fill { height: 100%; background: #4ade80; border-radius: 3px; transition: width 0.3s; }
  .sim-progress-label { font-size: 0.65rem; color: #94a3b8; margin-top: 0.25rem; display: block; }

  .sim-section       { margin-bottom: 1.5rem; }
  .sim-section h3    { font-size: 0.85rem; font-weight: 600; color: #cbd5e1; margin-bottom: 0.5rem; }
  .sim-table-wrap    { overflow-x: auto; }
  .sim-table         { width: 100%; border-collapse: collapse; font-size: 0.72rem; }
  .sim-table th      { text-align: left; padding: 0.35rem 0.5rem; color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,0.15); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.6rem; }
  .sim-table td      { padding: 0.3rem 0.5rem; color: #e2e8f0; border-bottom: 1px solid rgba(148,163,184,0.06); }
  .sim-td-mono       { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; }
  .sim-td-detail     { max-width: 24rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sim-buy           { color: #38bdf8; }
  .sim-sell          { color: #fb923c; }
  .sim-pill          { font-size: 0.6rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 9999px; }
  .sim-pill-replay   { color: #4ade80; background: rgba(74,222,128,0.12); }
</style>
