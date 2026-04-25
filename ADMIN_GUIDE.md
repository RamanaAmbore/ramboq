# RamboQuant Admin Guide

A walkthrough of the four things an admin cares about on this site:

1. **Agents** — rules that watch the portfolio and fire when something worth knowing happens.
2. **Tokens** — the vocabulary agents are written in.
3. **The Simulator** — lets you safely test what an agent would do under a hypothetical market.
4. **Settings** — runtime-editable thresholds and toggles you tune from the UI.

No code reading required. If you can use a dropdown and a form, you can use all of this.

> **TL;DR for the impatient:** want to see a loss-threshold rule auto-close your positions safely before you turn it on?
> 1. `/agents` → find `loss-pos-total-auto-close` → expand it. Condition is `pnl ≤ −₹50k on positions.total`; action is `chase_close_positions`; ships **inactive**.
> 2. Click **Run in Simulator** on that row. The sim synthesises a scenario that trips exactly this condition, auto-loads your live book, and dry-fires the agent.
> 3. Watch the bottom **Log** panel. The **Simulator** tab streams per-symbol price ticks; the **Order** tab shows the paper-traded `SELL N <symbol> @₹price · acct=…` lines for each position the action would have closed, one per position, all tagged `SIM`.
> 4. When you're confident the thresholds and actions match your risk tolerance, flip the agent **ON** from the row — it will do the real thing next time conditions fire.

---

## The four words

Everything on the admin site revolves around four ideas:

| Word | Plain English |
|---|---|
| **Agent** | A rule — "if X happens, tell me (and maybe do something)". Lives as a row on the **Agents** page. |
| **Alert** | The moment an agent's rule became true. Sent through Telegram, email, and the live log. |
| **Notify** | *How* an alert reaches you — telegram / email / browser / log. |
| **Action** | *What* the system does in response — e.g. place an order, close a position, deactivate a flag. |

Think of an agent as a sentence: **"When _condition_ is true, _notify_ me through these channels and _do_ these actions."**

### When agents re-fire (latching semantic)

To avoid spamming you when a drawdown persists, agents follow a two-tier rule:

- **Static agents** (absolute ₹ floor or % floor — e.g. "pnl ≤ −₹30k", "day loss ≥ 3%") fire **once** the first time the threshold is crossed, then **latch silent** as long as the condition keeps matching. They re-arm automatically when the value recovers above the threshold. This means a loss that sits flat at −₹40k won't fire the static agent every tick — you get one notification at the crossing, not a stream.
- **Rate-of-change agents** ("pnl bleeding ≥ ₹3k/min") keep re-firing while the bleed is accelerating, gated by cooldown (default 30 min) and a material-change threshold (default ₹15k move between fires). The whole point of these agents is to wake you up when the situation is getting materially worse.
- **Session rollover** (new trading day, detected automatically) clears every latch.

Put together: the first alert when things go bad is the static agent. After that, it's rate agents telling you if it's getting worse faster. When things recover, everything re-arms silently.

---

## How agents work — end to end

Here's what happens every 5 minutes during market hours:

```
Kite broker  ──►  holdings / positions / margins  ──►  summarise per account + total
                                                        │
                                                        ▼
                         ┌──────────────── run_cycle ────────────────┐
                         │  for each ACTIVE agent:                    │
                         │    1. is the market open?                  │
                         │    2. is the cooldown finished?            │
                         │    3. does the condition match?            │
                         │    4. has something material changed since │
                         │       the last alert?                      │
                         │    5. if yes: send alerts + run actions    │
                         └────────────────────┬───────────────────────┘
                                              ▼
           Telegram + email + browser live log + agent-events row in the DB
                                              │
                                              ▼
                       (if the agent has actions:  place_order / chase_close / …)
```

Each of those numbered gates exists to keep noise down. Cooldowns prevent spam. The baseline gate prevents opening-bell panic alerts. The suppression gate prevents re-alerting when the loss hasn't changed much.

---

## Anatomy of an agent

Every row on the **Agents** page (`/agents`) has four moving parts:

### 1. Conditions — the rule itself

Conditions are a tree you can read left-to-right. Three shapes are allowed:

| Shape | Meaning |
|---|---|
| **leaf** | A single test: `metric` + `scope` + `operator` + `value` |
| **all** | AND of children — every child must be true |
| **any** | OR of children — at least one child must be true |
| **not** | NEGATION — true when the child is false |

A leaf looks like this in JSON:

```json
{
  "metric": "pnl",
  "scope":  "positions.any_acct",
  "op":     "<=",
  "value":  -30000
}
```

Read it in English:
> "The **pnl** (metric) of **any account's positions** (scope) is **≤** (operator) **₹-30,000** (value)."

A composite tree:

```json
{
  "any": [
    { "metric": "day_pct", "scope": "holdings.any_acct", "op": "<=", "value": -3.0 },
    { "metric": "day_pct", "scope": "holdings.total",    "op": "<=", "value": -5.0 }
  ]
}
```

> "Either any account's day loss is at least 3 %, or the total day loss is at least 5 %."

### 2. Notify channels

A list like:

```json
[
  { "channel": "telegram", "enabled": true },
  { "channel": "email",    "enabled": true },
  { "channel": "log",      "enabled": true }
]
```

You can mix and match `telegram` / `email` / `websocket` / `log`. Disable one by flipping `enabled` to `false`.

### 3. Actions

Empty list `[]` means "alert only — don't do anything." Otherwise the list describes what to *do* when the alert fires:

```json
[
  { "type": "chase_close_positions",
    "params": { "account": "ZG0790", "exchange": "NFO" } }
]
```

The action shapes (place order, modify, cancel, close, log, deactivate, etc.) all come from the **Tokens** page — more on that next.

### 4. Metadata

- **Scope** — `total` or `per_account` (display grouping)
- **Schedule** — `market_hours` (default) or `always`
- **Cooldown (minutes)** — minimum time between two fires of this agent. Default 30.
- **Status** — `active` / `inactive` / `cooldown`. Toggle with the ON/OFF button on the agent row.

---

## Tokens — the vocabulary agents are written in

You can't invent words out of thin air when writing a condition. Every `metric`, `scope`, `op`, `channel`, and `action type` must be a **registered token**. The Tokens page (`/admin/tokens`) is where those words live.

### Three categories

The Tokens page has three tabs — three *kinds* of tokens, each playing a different role:

| Category | Tokens inside | Answers the question… |
|---|---|---|
| **Condition** | `metric`, `scope`, `operator` | *What can agents check?* |
| **Notify**    | `channel`, `format`, `template` | *How can agents alert?* |
| **Action**    | `action_type` | *What can agents do?* |

### System tokens vs custom tokens

- **System** tokens ship with the application. They have the orange "system" badge. You can **enable/disable** them (is_active toggle) but you cannot rename or delete them. Built-in metrics like `pnl`, `day_pct`, `cash`, built-in scopes like `holdings.any_acct`, `positions.total`, and built-in action types like `place_order`, `chase_close_positions` all live here.
- **Custom** tokens are ones you create on this page. Full CRUD — you can edit, delete, and change anything about them.

### What one token row looks like

Each row carries more than just a name. The fields you'll see when editing:

| Field | Meaning |
|---|---|
| **Category** | `condition`, `notify`, or `action` |
| **Token kind** | Sub-type. For condition: `metric` / `scope` / `operator`. For notify: `channel` / `format` / `template`. For action: `action_type`. |
| **Token** | The word itself — what authors type into an agent (e.g. `pnl`, `<=`, `telegram`). Must be unique within its (category, kind). |
| **Value type** | What kind of value this token produces or accepts — `number`, `string`, `boolean`, `enum`, `array`, `object`, `void`. |
| **Units** | Human-readable label for numeric metrics: `₹`, `%`, `₹/min`, `%/min`, `min`. |
| **Description** | One line explaining what it means. Shows in the Agents-page editor as tooltip-like help. |
| **Resolver** | Python dotted path to the function that implements the token. Required for system-integrated tokens; omit for simple enum/string tokens that the engine doesn't need to call into. |
| **Params schema** | For action tokens — what arguments the action expects (account, symbol, quantity, side, …). JSON schema. |
| **Enum values** | For enum value types — the allowed strings. |
| **Template body** | For notify template tokens — the message body with `${placeholder}` syntax. |

### Creating a token

1. Go to `/admin/tokens` → click **+ New token** (emerald button, top right).
2. Pick a **Category** (condition / notify / action).
3. Pick a **Token kind** — the form adapts. A condition `metric` needs a `resolver` (Python function that returns a number for a given row); a `scope` needs a resolver that returns a list of rows; an `operator` is usually a built-in comparator.
4. Fill in the token string, description, value type, optional units.
5. For action tokens, define the `params_schema` (JSON) — this is what the Agents page uses to render the action's sub-form.
6. Save → the row appears in the list.
7. **Click "Reload registry"** (yellow button, top right). Tokens are loaded into an in-memory dispatch table at startup; the reload button rebuilds that table so your new token is usable *without* restarting the server.

That's it. The new token is now a word agents can use.

### How tokens help agent creation

Every dropdown in the Agents editor is populated from the Tokens table:

- The condition editor autocompletes metric/scope/operator names from whatever's in the catalog.
- The "validate" button (on the Agents editor) checks every token referenced in your condition against the live registry — typos fail here, not at runtime.
- The actions editor renders its form using the action token's `params_schema`, so you only see fields relevant to the action you picked.

In short: **the Tokens page is the one place you extend the system.** Adding a new kind of check or a new kind of action is "one token row + one Python function," no deploy, no code change in the engine.

---

## Creating an agent — step by step

Open `/agents`. Agents are grouped by category (Loss & Risk, Summaries, Automation, Other) so existing ones are easy to find.

To create or edit:

1. Click a row to expand it and read the current condition tree in plain English.
2. Click **Edit** on the row. The inline form appears:
   - **Name** / **Description** — human-readable
   - **Scope** — `total` / `per_account`
   - **Schedule** — `market_hours` / `always`
   - **Cooldown (minutes)** — 30 is a reasonable default
   - **Conditions (JSON)** — the condition tree (see above)
   - **Events (JSON)** — notify channels list
   - **Actions (JSON)** — action list, or `[]` for alert-only
3. **Click Validate** (cyan button). The server dry-checks your condition tree against the live token registry and returns any unknown tokens. You'll get a green banner or an error list.
4. Click **Save** once validation passes.

A freshly-saved agent is `inactive` by default. Click the OFF pill to flip it to ON. It will start evaluating on the next tick.

### Copy-an-existing pattern (recommended)

The easiest way to build your first custom agent is to click into any `loss-*` row, look at its condition tree, and clone-edit a new agent with slightly different thresholds. The 14 seeded loss agents cover static `%`, static `₹`, rate `₹/min`, and rate `%/min` variants at both per-account and total scope — between them they exercise almost every condition-grammar feature.

---

## The Simulator — try it before you trust it

The Simulator (`/admin/simulator`) answers the question:

> "If the market did X, what would my agents do?"

It feeds fabricated holdings / positions / margins into the **same** agent engine the real pipeline uses. Alerts, Telegram messages, email sends, paper-traded orders — all of them fire, but every one is tagged `SIMULATOR` so nobody confuses them with real alerts.

### What you see on the page

- **Status bar** — `RUNNING` / `idle`, active scenario, seed mode, tick number.
- **Controls row** — scenario dropdown, seed mode, rate, plus buttons:
  - **Load live book** — snapshots your real Kite positions into the sim.
  - **Start / Stop / Step** — run continuously, halt, or apply one tick manually.
  - **Run cycle** — run the agent engine against the current sim state right now.
  - **Clear sim** — delete every past SIMULATOR event and order row from the DB.
- **Recent SIMULATOR agent events** — table of fires since the last Clear.
- **Recent SIMULATOR orders** — paper-traded orders from sim actions.
- **Log panel** (shared across the admin pages) — the **Simulator** tab streams one line per tick with per-symbol price diffs in real time.

### Simulated market clock

Time-aware agents (rate rules with a baseline gate, anything that checks `minutes_until_close`, expiry-day auto-close rules) need a realistic clock. The simulator provides one via **market-state presets**:

| Preset | What it simulates |
|---|---|
| `pre_open`     | Before the session (no segment flags open) |
| `at_open`      | Market just opened (1 min into session) |
| `mid_session`  | Default — 3 hours into the session |
| `pre_close`    | 6 hours in, close not yet passed |
| `at_close`     | Just after equity close, MCX still running |
| `post_close`   | Both segments done |
| `expiry_day`   | Mid-session on an expiry day — flips `is_expiry_day=true` so expiry agents engage |

Three places to set it (most specific wins): **Market dropdown** on the Simulator page → **scenario YAML** (`market_state: {preset: pre_close}`) → default `mid_session`. The Run-in-Simulator button on the Agents page picks a sensible preset from the agent's metric (`expiry_day` for expiry-slug agents, `mid_session` otherwise) so per-agent tests just work.

The running sim's status bar shows `market: <preset>` next to the tick counter.

### Tick cadence — positions only

The simulator is **positions-only**. Holdings aren't simulated at all because intraday risk lives in F&O positions + fund negatives; holdings-based agents (`day_pct`, `day_rate_abs`, `day_rate_pct`) validate against live production data only. If you press **Run in Simulator** on a holdings agent, you'll get a clear error telling you so.

Positions refresh every tick by default (cadence = 1). Three places to override, most specific wins:

1. **Pos / N** input on the Simulator page — blank = use scenario / DB default.
2. **Scenario YAML** — top-level `positions_every_n_ticks: <N>`.
3. **DB setting** — `simulator.positions_every_n_ticks` on `/admin/settings`.

Margin patches via `set_margin` are cadence-independent — they fire on whatever tick the scenario schedules them on. Tick 0 always refreshes (matches how a live session feels at market open).

### Three seeding modes

Scenarios decide what moves; seeding decides what moves them.

| Mode | Starting state | Use it when… |
|---|---|---|
| **Scripted** | The scenario's built-in `initial` block (fake accounts + symbols) | Deterministic regression test — same inputs every run |
| **Live** | Snapshot of your real Kite positions | You want to see what your *actual* book would look like after a hypothetical move |
| **Live + scenario** | Live snapshot, then the scenario's scripted extras layered on top | You want a real-book stress test (e.g. `generic-crash` scenario with your real positions) |

For Live / Live+scenario: you can press **Load live book** to snapshot now, or just pick Live / Live+scenario and hit **Start** — the driver auto-snapshots if you haven't already. Load live book manually when you want a *fresh* snapshot right before starting (e.g. after placing real orders).

### Running it

1. Go to `/admin/simulator`.
2. Pick a scenario. All five (`generic-crash`, `generic-euphoria`, `extreme-crash`, `extreme-euphoria`, `random-walk`) are positions-only and work with Live or Live+scenario. Start with a generic one; move to extreme variants when you want to trip every threshold at once.
3. Pick seed mode and (optionally) press **Load live book** — the driver auto-snapshots if you pick Live / Live+scenario and haven't already.
4. Set **Rate (ms)** — how fast to advance ticks. 2000 ms = 1 tick every 2 seconds is fine.
5. Press **Start**.
6. Switch to the **Simulator** tab at the bottom. Every tick shows up with per-symbol price moves:

   ```
   [12:34:56] SIMULATOR tick 3 · generic-crash
     holdings.ZG####.RELIANCE:  4822.03→4725.59 (Δ -96.44)
     holdings.ZG####.ACMESOLAR: 298.90→292.92   (Δ -5.98)
     ...
   ```

7. Sim auto-stops at 30 minutes. Stop early with the red **Stop** button.

### Testing one specific agent

On the `/agents` page, every row has a **Run in Simulator** button. Click it:

- Navigates to `/admin/simulator?agent_id=<id>`
- Pre-arms the page to run *only that agent*, bypassing schedule / cooldown / baseline gates
- Pick a scenario and Start → the chosen agent fires as often as its condition is true, without affecting any real state

This is the safest way to test a new agent before activating it.

### What gets tagged

Because `sim_mode=True` flows through the pipeline, every artefact is marked:

| Surface | Tag |
|---|---|
| Telegram | `SIMULATOR` prefix + red "SIMULATOR RUN — fabricated market data" line |
| Email subject | `RamboQuant SIMULATOR Agent: …` |
| Email body | Red banner at the top |
| agent_events row | `sim_mode = true` |
| algo_orders row | `mode = 'sim'` |
| Log line | `[SIM] …` (short prefix to conserve log width) |

So real alerts and simulated alerts are never in the same bucket.

### While the sim runs

- The red **SIMULATOR ACTIVE** banner pins to the top of every admin page.
- The `/agents` page's event table auto-switches to showing only sim events.
- The `/performance` page keeps showing **real** data — the live Kite refresh continues even during a sim, only the live agent engine is paused.

---

## Settings — runtime tunables

The Settings page (`/admin/settings`) is where you tune the knobs that change more often than a deploy cycle: alert thresholds, refresh cadences, simulator defaults, and the **execution mode** flags that decide whether an action hits the broker or stays in paper. Edits take effect on the **next agent tick / sim run** — no service restart, no redeploy.

### Page layout

Each parameter is a single row:

```
[i]   alerts.cooldown_minutes  [mod]      [   30   ] min   [ Save ]  [ Reset ]
```

- **(i)** — click the amber chip to expand a panel showing the description, default, range, and units. Click again to collapse. Use it when you don't recognise a key.
- **`[mod]` badge** — appears when the live value differs from the code-shipped default.
- **Value field** — input adapts to the type: text for strings, number with min/max for ints/floats, dropdown for booleans / enums.
- **Save** — disabled until you change the value. Writes the new value and refreshes the row.
- **Reset** — disabled until the row is modified. Restores the code-shipped default.

A **filter box** at the top searches both keys and descriptions — useful when you know roughly what you want but not the exact key.

Categories are rendered in deliberate order — **execution → alerts → algo → performance → simulator → notifications → logging → misc** — so the things you'll actually touch sit at the top of the page.

### Settings vs YAML

Settings are for runtime knobs an operator changes without thinking about a deploy. **Infrastructure parameters stay in YAML deliberately**:

| In Settings (DB) | In `backend_config.yaml` |
|---|---|
| Alert thresholds, cooldowns | DB credentials |
| Refresh cadences | Market hours |
| Sim defaults | Kite URLs |
| Execution mode flags | IPv6 source addresses |
| Notification toggles | Capability flags (`cap_in_<branch>`) |
| Log levels | Log file paths |

The seeder behaves well across deploys: it inserts new keys, refreshes descriptions / schemas / defaults, **preserves your overrides**, and auto-prunes keys that have been retired in code.

### Execution mode banner

The first thing you see on the page is the execution mode banner:

- **Green — `Every broker action is in PAPER mode`** — every fired agent that wants to hit Kite will instead write a paper `AlgoOrder` row. Real positions don't change. This is the prod default.
- **Red — `⚠ N of 6 actions are LIVE`** — at least one `execution.live.<action>` flag is true; agents firing those actions will place real broker orders.

Below the banner, the **execution** section lists six per-action flags (`execution.live.cancel_order`, `execution.live.cancel_all_orders`, `execution.live.modify_order`, `execution.live.place_order`, `execution.live.close_position`, `execution.live.chase_close_positions`). Flip them one by one — no all-or-nothing switch — to promote actions from paper to live.

### The three execution modes

Every agent fire that touches the broker gets routed by mode:

| Mode | Where it runs | Quote source | Trade engine |
|---|---|---|---|
| **1 — Simulator** | Dev only | Fabricated (scenario-driven) | `PaperTradeEngine` against fabricated bid/ask |
| **2 — Real-data + paper** | Prod default for every action | Real Kite quote API (batched) | `PaperTradeEngine` against live bid/ask, validated by Kite's `basket_margin` |
| **3 — Real broker** | Prod, per-action opt-in | Real Kite | Real `place_order` / `modify_order` / `cancel_order` |

The `main` branch is a **hard outer gate**: on dev (any non-main branch), every broker-hitting action is forced to paper regardless of these flags — the `execution.live.*` toggles only matter on prod.

Every alert email + Telegram message gets a tag so you can tell at a glance what mode the actions ran in:

| Tag | Meaning |
|---|---|
| (no tag) | Every broker action in this fire ran live |
| `[PAPER]` | Every broker action in this fire was paper |
| `[MIXED]` | Some live, some paper (you have a mix of `execution.live.*` flags on) |

### Recommended promotion order

When you finally trust the engine enough to go live, promote actions in this order — most reversible first:

1. `execution.live.cancel_order` — cancelling a stale order can't lose money
2. `execution.live.cancel_all_orders`
3. `execution.live.modify_order` — modifying an existing order is bounded by your existing position
4. `execution.live.close_position`
5. `execution.live.chase_close_positions` — automatic loss-cut
6. `execution.live.place_order` — opens new exposure; promote last

After each flip, watch the next live agent fire end-to-end. If anything looks off, set the flag back to `false` — the next tick reverts that action to paper.

### How edits take effect

Most settings update on the next agent tick (5-minute cadence). A few are special-cased:

- **`logging.*_log_level`** — handlers reapply the new level the moment you Save.
- **`performance.refresh_interval`** / **`performance.market_refresh_time`** — picked up live by the background loop.
- **`alerts.*`** — applied next time `run_cycle` fires.
- **`execution.live.*`** — applied at the action handler the next time an agent fires.

You don't have to memorise this — the **(i)** info chip on each row tells you what the setting governs.

---

## Recipes

**A) "Add a custom loss rule for one specific account"**
1. Go to `/agents` → Copy the condition from `loss-pos-acct-static-abs`.
2. Edit a new agent slug like `loss-zg0790-positions`.
3. In the condition, replace `"scope": "positions.any_acct"` with a scope that matches only the account you care about (e.g. a new custom scope token you create on the Tokens page).
4. Validate → Save → **Run in Simulator** on the agent row → confirm it fires (the synthesizer builds a scenario targeting this specific agent's condition; no need to pick one manually).
5. Flip it to ON.

**B) "Add a new metric the engine doesn't have yet"**
1. Write a Python function somewhere under `backend/api/algo/` that takes `(ctx, row)` and returns a number.
2. Go to `/admin/tokens` → **+ New token** → Category `condition`, kind `metric`, resolver set to the dotted path of your function.
3. Save → Reload registry.
4. Your metric is now usable in any agent's condition leaf.

**C) "Find out what would happen if the market drops 6% right now"**
1. `/admin/simulator` → Scenario `generic-crash` → Load live book → Seed `Live + scenario` → Start.
2. Watch the Simulator log tab for price moves; watch the events table for which agents would fire.
3. Stop when you've seen enough. Hit **Clear sim** to wipe the test rows.

**D) "Auto-close on severe loss — but safely"**
1. `/agents` → `loss-pos-total-auto-close`. Ships inactive with a `chase_close_positions` action on `pnl ≤ −₹50k`.
2. Open the row → "Actions" section shows the action type + params (scope=total, timeout 10 min, adjust_pct 0.1).
3. Click **Run in Simulator** — the synthesizer targets this agent's condition; the sim seeds your live book automatically.
4. Flip the bottom panel to the **Order** tab. You'll see one `SIM ◆ SELL N <symbol> @₹price · acct=…` line per open position the chase engine would try to close.
5. Flip to **Simulator** tab — the same lines appear interleaved with price ticks, so you can see the sequence: price move → threshold cross → orders placed.
6. When the output matches your risk tolerance, flip the agent **ON**. Next time conditions fire for real, the chase engine runs against the broker.

**E) "Add a close-position action to an existing loss agent"**
1. `/agents` → pick a loss agent → **Edit**.
2. Next to the **Actions (JSON)** textarea, click the `+ close_position` pill — a skeleton action lands in the textarea.
3. Tune the params: set `account`, `symbol`, `quantity`. (For scope-level auto-close on any matching position, use `+ chase_close` instead — it doesn't need a specific symbol.)
4. **Validate** → **Save** → **Run in Simulator** to confirm → flip **ON**.

**F) "Tune a threshold without redeploying"**
1. `/admin/settings` → type the keyword in the filter box (e.g. `cooldown`, `rate`, `baseline`).
2. Click the **(i)** chip on the row to read what the setting does, its default, and its valid range.
3. Edit the value → **Save**. The next agent tick (within 5 min) picks up the new value.
4. If you change your mind, click **Reset** to restore the code default.

**G) "Promote one action from paper to live"**
1. `/admin/settings` → check the banner — green means everything is paper.
2. Find the **execution** section. Pick the most reversible action that you trust (start with `execution.live.cancel_order`).
3. Toggle the dropdown to `true` → **Save**. Banner flips to red `⚠ 1 of 6`.
4. Wait for the next live agent fire that uses that action. The Telegram subject loses its `[PAPER]` tag (or shows `[MIXED]`) — that tells you the action went to the broker.
5. Inspect `/orders` for the new live `AlgoOrder` row (mode = `live`).
6. If something looks wrong, toggle the flag back to `false` — the next tick reverts to paper.

---

## Safety checklist before flipping a new agent to ON

- [ ] Description explains what it does and why.
- [ ] Condition tree passes **Validate** on the Agents editor.
- [ ] Cooldown is at least a few minutes (prevents spam).
- [ ] Schedule is `market_hours` unless you actually want it firing overnight.
- [ ] Ran in the Simulator with a representative scenario and got the expected fires.
- [ ] If the agent has **actions** (not just alerts): the action's params are correct and the action is safe to run against your book.

---

## Where to go when something looks wrong

| Problem | Look here |
|---|---|
| Agent didn't fire when it should have | `/agents` → Last fire timestamp + Count on the row; also the Simulator tab in the log panel |
| Sim shows ticks but no price changes | You probably picked a scenario with no scripted initial in Scripted mode — switch to Live+scenario and Load live book first |
| Custom token won't appear in the Agents editor | Did you press **Reload registry** after saving? Is the token's `is_active` on? |
| Alerts not reaching Telegram/email | Check `cap_in_<branch>.telegram` and `cap_in_<branch>.mail` in `backend_config.yaml`; dev may have these off by default |
| Settings change didn't take effect | Most apply on the next agent tick (≤ 5 min). `logging.*` apply at Save. If you flipped an `execution.live.*` flag on dev, note that the branch gate forces every action back to paper regardless. |
| Live agent fired but no real broker order | Check `/admin/settings` → **execution** section. If the relevant `execution.live.<action>` is `false`, the action wrote a paper `AlgoOrder` row instead. Telegram subject would have shown `[PAPER]`. |
| "Invalid username or password" on sign-in | Ask the server admin to reset your password — there's no forgot-password flow yet |

---

## Glossary

- **Branch**: `main` = production (`ramboq.com`), everything else = dev (`dev.ramboq.com`). Agents, tokens, and sims on dev don't affect production.
- **Capability flag**: `cap_in_dev.<feature>` / `cap_in_prod.<feature>` in `backend_config.yaml`. Toggles whether a capability (simulator, telegram, mail, genai, market_feed) is live on that branch.
- **Dispatch registry**: The in-memory index that maps each token name to its implementation. Rebuilt from the Tokens table at startup and on **Reload registry**.
- **Execution mode**: Sim / paper / live, decided per agent fire. Sim = fabricated quotes + paper trade engine (dev only). Paper = real quotes + paper trade engine, validated by Kite's `basket_margin`. Live = real broker order. Per-action flags in **Settings** decide paper-vs-live on prod.
- **Masked account**: Accounts are rendered as `ZG####` / `ZJ####` in the UI and in alerts to avoid leaking numeric IDs. Internally the real IDs (`ZG0790`, `ZJ6294`) are used.
- **Tick**: One step of the simulator. Each tick applies a set of price moves and then invokes the agent engine once.
