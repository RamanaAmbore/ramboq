# RamboQuant User Guide

Plain-language walkthrough of how RamboQuant works, written for someone who just got admin access and isn't a software engineer or quant. If a sentence ever sounds like jargon, that's a bug — please report it.

> **What this guide is vs [ADMIN_GUIDE.md](ADMIN_GUIDE.md):**
> - **USER_GUIDE** (this file) — explains *concepts*: what an agent is, what the chase loop does, why we have a simulator, what Greeks mean. Aimed at someone learning the platform for the first time.
> - **ADMIN_GUIDE** — operational reference: exact buttons / forms / API endpoints / config files. Aimed at someone running the system day-to-day. Read this first; reach for ADMIN_GUIDE when you need step-by-step instructions on a specific task.

---

## The mental model in 60 seconds

RamboQuant is a **rule-based assistant for an Indian options trader**. You define rules ("if my NIFTY positions lose more than ₹50,000 in a day, sell them"); the platform watches the live market, fires the rules when conditions are met, and (if you've authorised it) places the trades. It logs everything, it sends Telegram + email alerts, and it has multiple safety nets so a misconfigured rule can't destroy your book.

The four words that come up everywhere:

| Word | Plain meaning |
|---|---|
| **Agent** | A rule. "If X, do Y." Lives as a row on the **Agents** page. |
| **Alert** | The moment an agent's rule triggered. Goes to your Telegram + email + the live log. |
| **Action** | What the agent does in response to firing — place an order, close a position, send a notification, etc. |
| **Notify** | The delivery channel for the alert (Telegram / email / browser). Independent from Action. |

Read every agent as a sentence: *"When **condition** is true, **notify** me through these channels and **do** these actions."*

---

## The big picture — three modes you'll work in

Whenever an agent fires an action that wants to hit your broker, the platform has to decide: is this real, fake, or in-between? It uses three modes:

### Mode 1 — Simulator (testing only, dev only)

Fabricated price moves driven by a script you choose ("NIFTY drops 3% over three minutes"). Your real broker is never contacted. Useful for: *"if my book actually saw this move, would my agent fire? Would the auto-close trade make sense?"*

You'll spend most of your time here when adding a new agent or strategy.

### Mode 2 — Paper trade (default on production)

Real Kite quotes feeding a fake order book. Your agents see real prices, real bid/ask. When they fire a "place order" action, the order goes into a paper ledger — Kite's `basket_margin` API confirms the order *would* be valid, but no real order ever leaves the platform. You see what would have happened.

### Mode 3 — Live (per-action opt-in)

A real broker order. Only happens when you've explicitly flipped a flag in **Settings** for the specific action type (e.g. `execution.live.cancel_order = true`). Default is everything stays in paper.

You promote actions one at a time as you build trust:

1. `cancel_order` (most reversible — cancelling a stale order can't lose money)
2. `cancel_all_orders`
3. `modify_order`
4. `close_position`
5. `chase_close_positions` (auto-loss-cut)
6. `place_order` (opens new exposure — promote last)

Every alert gets a tag in its Telegram subject:
- (no tag) — every action ran live
- `[PAPER]` — every action was paper
- `[MIXED]` — some live, some paper

---

## Agents — the rules layer

Open `/agents`. Every row is a rule. Click to expand and read it in plain English.

### Anatomy of a rule

Four parts:

1. **Condition** — what to check. Example in operator-friendly form: *"any account's positions lose ≥ ₹30,000."*
2. **Notify** — where to alert (Telegram / email / browser).
3. **Actions** — what to do (often empty; the alert *is* the response).
4. **Metadata** — when this should run (market hours / always), how long to wait between two fires (cooldown).

### When an agent re-fires

To stop you from getting 100 emails when you've crossed a threshold once:

- **Static thresholds** ("pnl ≤ −₹50k") fire **once** when crossed, then go quiet. They re-arm when you recover above the threshold.
- **Rate thresholds** ("losing ≥ ₹3k/min") keep alerting while the bleed is *accelerating*. Bounded by cooldown (default 30 min) and a "must have moved meaningfully since last fire" gate.
- **Session rollover** (new trading day) resets all latches.

So the first email when things go bad is the static agent. Subsequent emails are rate agents telling you it's getting worse faster.

### Built-in agents

The platform ships with 14 loss / risk agents pre-seeded and active:

| Slug pattern | What it watches |
|---|---|
| `loss-pos-*` | Position P&L (intraday F&O exposure) |
| `loss-hold-*` | Holdings P&L (long-term equity) |
| `loss-funds-cash-negative` | Cash balance below zero |
| `loss-funds-margin-negative` | Available margin below zero |

Edit them from `/agents` — change a threshold, add Telegram-only notification, or attach a `chase_close_positions` action that auto-cuts losses. The conditions are JSON trees you can read like a sentence.

### Adding your own agent

Easiest path: copy an existing rule that's close to what you want, change the threshold or the action. The platform validates your edits before saving — you'll see a green check or a red error before the save button works.

---

## Simulator — the safe-test space

The Simulator (`/admin/simulator`) is where you ask: *"if the market did X, what would my agents do?"*

You pick:
- A **scenario** — pre-canned price moves like `nifty-down-3pct` (NIFTY drops 1% / 2% / 3% over three ticks, every option re-prices via Black-Scholes)
- A **seed** — where the positions come from:
  - **Scripted** — fake account / fake symbols, fully deterministic
  - **Live** — your real Kite book at this moment
  - **Live + scenario** — real book + scripted extras layered on top
- A **rate** — how fast ticks advance (default 2 seconds = readable but not glacial)

Then press **Start**. Every alert, Telegram message, email, and paper-traded order fires *as if it were real*, but every artefact is tagged `SIMULATOR` so nobody confuses it with a real fire. Auto-stops after 30 minutes.

### What you'll see while it runs

- **Position pills** at the top — each open contract with side / qty / LTP / P&L. Watch them shrink as fills close out positions.
- **Chart panel** — one mini chart per symbol showing the price move + markers where orders were placed / filled / unfilled. **Mouse-wheel zooms in around the cursor; click-and-drag pans; "reset" button restores the full range.**
- **Log panel** at the bottom — Simulator tab streams every tick + price diff; Order tab shows the paper-traded `AlgoOrder` rows; Agent tab shows `sim_mode=true` events.

### Custom positions

If you want to test a position you don't actually have, add it manually: scroll to **Custom positions** below the controls, click **+ Add row**, type a symbol / quantity / last price. Mix it with your real book or use it standalone. F&O symbols re-price coherently when an `underlying_*` move fires (Black-Scholes with calibrated IV); cash equities track simple percentage moves.

### Run-in-Simulator on a specific agent

Every row on `/agents` has a **Run in Simulator** button. Click it, and the simulator builds a one-off scenario *targeted at that agent's condition tree* — no manual scenario picking. Useful for: *"does this new agent I just wrote actually fire when I think it should?"*

---

## The chase / fill / order engine — what happens when an agent says "place order"

Real-world option orders rarely fill at exactly the price you asked. The platform uses an **adaptive limit-order chase** — the same logic for sim, paper, and live:

1. **Place a LIMIT order** at the current bid (if you're SELLing) or ask (if you're BUYing).
2. **Each tick** (every 5 s on prod, every scenario tick in sim):
   - Walk every open order
   - Ask the quote source for the current bid/ask
   - **Fillable?** — bid ≥ limit (SELL) or ask ≤ limit (BUY) → mark `FILLED`, write the fill price
   - **Not fillable?** — bump the limit one step toward the opposite side ("chase"), increment attempt counter
3. **Cap at `simulator.chase_max_attempts`** (default 5). After the cap, mark `UNFILLED` and stop.

You see this in the Order tab as live updates: `chase #2 limit=₹180.00`, then `chase #3 limit=₹181.50`, then `FILLED @₹181.50 after 3 chase(s)`. The chase engine is the same code path for paper and live — just the quote source differs.

### Where the chase engine matters

- **Auto-close on loss** (`chase_close_positions` action) — when a loss agent fires, it tries to close positions by chasing. You see exactly how aggressive the chase was before it filled.
- **Expiry-day cleanup** — every weekly expiry day the platform automatically chase-closes ITM options before the broker takes them to delivery.
- **Manual orders from Terminal** — when you type `buy NIFTY25APR22000CE 50 @180` on `/console`, the chase engine handles it just like an agent-driven order.

---

## Charts — making sense of the moves

Two chart types, both with the same zoom + pan behaviour:

### Price charts (sim / paper / live)

Live tick streams of last-traded price + bid/ask spread + order-event markers. Find them on:

- `/admin/simulator` — one chart per symbol with captured ticks while a sim runs
- `/admin/paper` — same but for the prod paper engine
- `/agents` and `/orders` — same charts surface in the Log panel's "Chart" tab

Symbols are classified as:
- **SPOT** (sky-blue tag) — an underlying like NIFTY itself
- **F&O** (amber tag) — an option or future, with the underlying drawn as a faint dashed sky-blue line on the same chart for context

Order events appear as colored dots on the line:
- **Amber** — order placed
- **Emerald** — filled
- **Red** — chase gave up (unfilled)

Hover over any dot to see what side / quantity / price.

### Options analytics — the payoff diagram

`/admin/options` is the dedicated options-research page. For any single option (live position, sim position, or hypothetical you typed in), you get:

- **Payoff diagram** — your P&L as a function of where the underlying ends up. Two curves on the same chart: today's value (Black-Scholes with current IV) and expiry value (intrinsic only). Profit zone shaded green, loss zone red. Vertical markers show current spot, strike, breakeven.
- **Side panel** — Greeks (Δ Γ Θ V ρ) per share AND scaled by your position size, plus theoretical-vs-market discrepancy and risk metrics (max profit, max loss, breakeven, probability of profit).
- **Historical chart** below — last 30 days of OHLC bars from Kite.

The chart x-axis is **always ±2.5 standard deviations from current spot** at expiry — so a 7-DTE option charts a tighter range (~5%) than a 60-DTE option (~15%). You see exactly the "where it could plausibly land" zone, not arbitrary fixed percentages. Wheel to zoom further into the money / out of the money; reset to come back.

### Multi-leg strategy mode

Source dropdown → **Strategy (multi-leg)**. Two ways to build a basket:

1. **Add leg from book** — picks any open live or sim position, captures avg cost + LTP at click time.
2. **+ Add row** — a blank line for a hypothetical leg.

Then **Analyze** — the page renders the aggregate payoff curve with every leg's strike marked, every breakeven (iron condors have 2!), and aggregated Greeks. Use this **before** you put on a complex trade — see the breakevens, see the POP, *then* hit the broker.

Constraint for v1: all legs share the same underlying and same expiry (calendar / diagonal spreads need different math).

### When prices look "stale"

If the broker has no live last-trade for a contract (illiquid, off-hours, weekend), the chart still draws — the platform falls back through:

1. live last-traded price
2. previous-day close
3. midpoint of bid/ask
4. your own average cost
5. estimated theoretical price at default 15% IV

You see this as a yellow `stale: <source>` chip on the pricing block, and a `·source` tag next to each price. Treat the absolute rupee numbers with care when the chip is yellow; the *shape* of the payoff is still right.

---

## Paper trading dashboard — `/admin/paper`

The visual surface for what mode 2 is doing on prod. Same layout as the simulator but reading from the live paper engine. You'll see:

- **Status banner** — green when there are open paper chases, amber when idle, grey on dev (paper only runs on `main`)
- **Open chase pills** — one per in-flight order with side / qty / current limit / attempt count
- **Mini charts** — per symbol with markers
- **Log panel** with a Charts tab + Orders tab

The most useful page during the soak phase: when you've flipped one `execution.live.<action>` to true and want to watch the chase against the live market without an order touching the broker.

---

## Settings — the runtime knobs

`/admin/settings` is where you tune anything that changes more often than a deploy cycle. Categories:

- **Execution** — the per-action live/paper flags. Top of the list because it's the highest-stakes decision.
- **Alerts** — cooldown, rate window, suppression deltas
- **Algo** — chase cadence, attempt cap, expiry rules
- **Performance** — refresh intervals
- **Simulator** — sim defaults
- **Notifications** — telegram / email toggles
- **Logging** — verbosity per handler

Each row is one parameter. Click the small `(i)` chip next to the key to see what it does, what its valid range is, and what default it shipped with. Edit, **Save**, and the next agent tick picks up the change. **Reset** restores the code default.

The **execution-mode banner** at the top is loud on purpose: green = "every broker action is in PAPER mode"; red = "⚠ N of 6 actions are LIVE — real orders will hit the broker".

---

## Brokers — managing accounts

`/admin/brokers` is the CRUD UI for broker credentials. Add a new Kite account with API key / secret / password / TOTP seed; encrypts secrets at rest with a key derived from `cookie_secret`; never returns the secrets back through the API. Every save reloads the platform's connection map so the next broker call uses the new credentials — no service restart.

Each row has a **Test** button that hits `broker.profile()` to verify the credentials authenticate. ✓ next to the button means it's working; ✗ shows the broker's error in the tooltip.

---

## Day-to-day workflow — what you'll actually do

A typical session for an active operator:

1. **Open `/dashboard`** — quick check: holdings, positions, P&L per account.
2. **Watch `/agents`** — any fires today? Any in cooldown?
3. **If a new strategy is being considered**: `/admin/options` → Strategy mode → build the legs → eyeball the breakevens, max loss, POP → if it looks good, place the trade through the Terminal or your usual flow.
4. **If thresholds need adjusting**: `/admin/settings` or edit the relevant agent on `/agents`.
5. **Before adding a new agent**: write the rule → `Run in Simulator` → confirm it fires on the right conditions and the auto-close action does what you expect → flip it ON.
6. **Once a week or so**: glance at `/admin/paper` to see what mode-2 paper trades fired since you last looked. Compare against what you'd have done manually.

---

## Glossary

- **Agent** — a rule row on `/agents`.
- **Alert** — the moment an agent fired.
- **Action** — what the agent did (place order / close position / etc).
- **Bid** — the highest price someone is willing to pay right now.
- **Ask** — the lowest price someone is willing to sell at right now.
- **Spread** — bid minus ask. Tight spread = liquid contract; wide spread = illiquid.
- **LTP** — last-traded price. The most recent trade.
- **Strike** — the contracted price for an option. NIFTY 22000 CE has strike 22000.
- **DTE** — days to expiry.
- **IV** — implied volatility, expressed as an annualized percentage.
- **Greeks** — sensitivities of option price: Delta (to spot), Gamma (to delta), Theta (to time), Vega (to vol), Rho (to interest rate).
- **POP** — probability of profit. The chance the position ends profitable at expiry.
- **Underlying** — the asset the option is on. NIFTY for NIFTY25APR22000CE.
- **Spot** — the current price of the underlying.
- **Chase engine** — the loop that re-quotes a stale limit order each tick to follow the market.
- **Paper trade** — a real-data dry-run that writes order rows to the database but never sends them to the broker.
- **Sim** — simulator. Fully fabricated prices, used for testing.

---

## When things go wrong

| Symptom | Where to look |
|---|---|
| Agent didn't fire when I expected it to | `/agents` → expand the row → check "Last fire" timestamp + "Count" + cooldown. Also try **Run in Simulator** to confirm. |
| Telegram / email not arriving | `/admin/settings` → notifications block. Make sure `cap_in_<branch>.telegram` and `mail` are on. |
| Options page shows yellow "stale" chips | The broker has no fresh quote. Likely because: market closed, contract illiquid, weekend. Fallback values are still useful for the *shape* of the payoff, just not absolute P&L. |
| Brokers page shows "PENDING" status pill | The DB row exists but the platform's connection map hasn't picked it up yet. Wait 15 s — the page polls. Or click **Test** to force a load. |
| Sim won't start | Check `cap_in_<branch>.simulator` in `backend_config.yaml` — defaults to ON on dev, OFF on prod. |
| "Mode 2 IS LIVE" panic | Check `/admin/settings` → execution block. Flip every `execution.live.<action>` to false. Saves are immediate; no service restart needed. |

---

## Where to learn more

- **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** — exact button labels, JSON conditions, API endpoints. The operations reference.
- **[CLAUDE.md](CLAUDE.md)** — architectural notes for engineers + AI assistants. Covers the code structure, data flow, and design decisions.
- **`/admin/tokens`** — explore the agent grammar (every metric / scope / operator the platform knows about).
- **`/admin/simulator`** — the safest place to learn by experimentation. Nothing you do there touches your real money.
