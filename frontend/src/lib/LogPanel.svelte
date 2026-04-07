<script>
  import { logTime, parseLogLineTime } from '$lib/stores';

  /** @type {{
   *   heightClass?: string,
   *   cmdHistory?: Array<{cmd: string, result: string, time: string}>,
   *   orderLog?: Array<any>,
   *   agentLog?: Array<any>,
   *   systemLog?: string[],
   *   initialTab?: string,
   *   onTabChange?: (tab: string) => void,
   * }} */
  let {
    heightClass = 'flex-1 min-h-0',
    cmdHistory = [],
    orderLog = [],
    agentLog = [],
    systemLog = [],
    initialTab = 'order',
    onTabChange = () => {},
  } = $props();

  let logTab = $state(initialTab);

  const TABS = [
    ['order', 'Order Log'],
    ['terminal', 'Terminal'],
    ['agent', 'Agent Log'],
    ['system', 'System Log'],
  ];

  const ORDER_TYPES = new Set(['order_placed','order_cancelled','order_rejected','order_filled']);

  function orderClass(t) {
    return t?.includes('success') ? 'log-agent-success'
         : t?.includes('fail')    ? 'log-agent-failed'
         : 'log-agent-triggered';
  }

  function stripTs(l) {
    return l.replace(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*-?\s*/, '');
  }

  function sysClass(l) {
    return l.includes('ERROR') ? 'log-error' : l.includes('WARNING') ? 'log-warning' : 'log-info';
  }

  function filteredOrder() {
    return orderLog.filter(e =>
      ORDER_TYPES.has(e.event_type) ||
      (e.event_type?.startsWith('action_') && /place_order|chase_close/i.test(e.trigger_condition || '')));
  }

  function _orderLogHtml() {
    // Merge command history (order results) + agent order events, newest first
    const cmdLines = cmdHistory.map(h => {
      const cls = h.result.startsWith('✓') ? 'log-agent-success' : h.result.startsWith('✗') ? 'log-agent-failed' : 'log-info';
      return `<span class="${cls}"><span class="log-ts">[${h.time}]</span> ${h.cmd} → ${h.result}</span>`;
    });
    const evtLines = filteredOrder().map(e => {
      const t = logTime(e.timestamp);
      return `<span class="${orderClass(e.event_type)}"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
    });
    const all = [...cmdLines, ...evtLines];
    return all.length ? all.join('\n') : '<span class="log-debug">No order events.</span>';
  }

  function setTab(id) {
    logTab = id;
    onTabChange(id);
  }
</script>

<div class="flex gap-0.5 mb-2">
  {#each TABS as [id, label]}
    <button onclick={() => setTab(id)}
      class="px-3 py-1 text-xs font-medium border-b-2 transition-colors
        {logTab === id ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-text'}"
    >{label}</button>
  {/each}
</div>

<pre class="log-panel {heightClass}">{#if logTab === 'terminal'}{#if cmdHistory.length}{@html cmdHistory.map(h =>
  `<span class="log-info"><span class="text-green-400">$ ${h.cmd}</span></span>\n<span class="log-debug">${h.result}</span>`
).join('\n\n')}{:else}<span class="log-debug">Command results appear here.</span>{/if}{:else if logTab === 'order'}{@html _orderLogHtml()}{:else if logTab === 'agent'}{#if agentLog.length}{@html agentLog.map(e => {
  const t = logTime(e.timestamp);
  return `<span class="log-agent-default"><span class="log-ts">[${t}]</span> ${e.event_type||''} ${e.trigger_condition||''}</span>`;
}).join('\n')}{:else}<span class="log-debug">No agent events.</span>{/if}{:else}{#if systemLog.length}{@html systemLog.map(l => {
  const t = parseLogLineTime(l);
  const rest = t ? stripTs(l) : l;
  return `<span class="${sysClass(l)}">${t ? `<span class="log-ts">[${t}]</span> ` : ''}${rest}</span>`;
}).join('\n')}{:else}<span class="log-debug">No log entries.</span>{/if}{/if}</pre>
