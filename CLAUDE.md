# CLAUDE.md — RamboQuant Project Reference

This file is for Claude Code. It provides project context, file map, patterns, and refactoring notes to avoid re-exploring the codebase from scratch each session.

---

## Project Overview

**RamboQuant** is a production web app for RamboQuant Analytics LLP at [ramboq.com](https://ramboq.com). It provides portfolio performance tracking, market updates (via Gemini AI), user onboarding, and investment information.

- **Architecture**: Litestar API + SvelteKit frontend
- **Single codebase**, two deployment targets: prod (`main`), dev (non-main branches)
- **Database**: PostgreSQL 17 via SQLAlchemy 2.x async + asyncpg; `ramboq` (prod) / `ramboq_dev` (dev) selected by `deploy_branch`
- **Broker data** comes from Zerodha Kite API; no DB storage for market data
- **Auth**: JWT (HS256) with PBKDF2-SHA256 password hashing; users in SQLAlchemy DB; stub mode when DB is empty

---

## Deployment Architecture

| Environment | Branch | Server path | Port | Domain | Runtime |
|---|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8502 | ramboq.com | Python venv |
| Development | any other non-main | `/opt/ramboq_dev` | 8503 | dev.ramboq.com | Python venv |

- GitHub push → webhook at `webhook.ramboq.com/hooks/update` → `dispatch.sh` → `deploy.sh <ENV> <REF>` → venv+pip → systemctl restart
- `webhook.ramboq.com` and `dev.ramboq.com` must be **grey cloud (DNS only)** in Cloudflare

### Branch Strategy
Both branches (`main`, `dev`) are kept in sync — every feature is developed on `dev`, then merged to `main`. After merging:
- `dev` is fast-forwarded to match `main` so both branches stay at the same commit
- Branches are **never deleted** from GitHub — both are permanent
- Webhook deploys each branch to its own environment automatically on push

---

## Key File Map

### Helpers (`backend/shared/helpers/`)
- **`broker_apis.py`** — `fetch_holdings()`, `fetch_positions()`, `fetch_margins()` — each decorated with `@for_all_accounts`; returns a list (one DataFrame per account). `fetch_holidays(exchange)` — calls `kite.holidays(exchange)`, returns set of holiday dates for the current year; used by background refresh for NSE and MCX calendars.
- **`connections.py`** — `Connections` singleton (extends `SingletonBase`) holds one `KiteConnection` per account; handles Kite 2FA login, TOTP, and access token refresh. Re-authenticates after 23 hours (`conn_reset_hours` in `backend_config.yaml`). Supports per-account `source_ip` binding (IPv6) to work around Kite's one-IP-per-app restriction — see Multi-Account IP Binding section below.
- **`decorators.py`** — `@for_all_accounts` iterates all accounts or a single one; `@retry_kite_conn()` retries with `test_conn=True` from attempt 2; `@track_it()` logs execution time; `@lock_it_for_update` / `@update_lock` for thread safety
- **`singleton_base.py`** — Thread-safe singleton via double-checked locking; `_instances` dict keyed by class
- **`utils.py`** — YAML loaders (run at module import), `get_image_bin_file()`, `get_path()`, `get_nearest_time()`, `add_comma_to_df_numbers()`, validators (email, phone, password, PIN, captcha), `CustomDict`
- **`genai_api.py`** — Gemini 2.5 Flash via `google-genai` with Google Search grounding; falls back to `frontend_config['market']` static content when `genai: False` in `backend_config.yaml` or when Gemini returns empty/None response (rate limiting)
- **`mail_utils.py`** — SMTP via Hostinger; respects `cap_in_dev` and `mail` flags in `backend_config.yaml` before sending. `send_email(name, email_id, subject, html_body)`
- **`date_time_utils.py`** — Indian/EST timezone utilities using `zoneinfo`. `is_market_open(now, holiday_set, market_start, market_end)` — returns True if not in holiday_set, not a weekend, and within time window. Weekends (Sat/Sun) are rejected. Special trading sessions (Muhurat etc.) need an explicit override when reintroduced.
- **`ramboq_logger.py`** — Rotating file handlers (5MB), line-limited handlers (50 lines), queue-based async logging
- **`summarise.py`** — Summary/alert helper functions extracted for use by the API background tasks (open/close summary + loss alert check).
- **`alert_utils.py`** — Market-summary notifier + delivery helpers shared with the agent engine. Public: `send_summary(sum_holdings, sum_positions, ist_display, msg_type, label, df_margins)` — sends open/close summary (Holdings / Positions / Funds tables) via Telegram + SMTP. Internal (imported by the v2 agent engine): `_tg_alert_body`, `_email_alert_body`, `_dispatch`. Message prefixes: Telegram `Open|Agent|Close`, email subject `RamboQuant Open:|RamboQuant Agent:|RamboQuant Close:`. Non-main branches show `[branch]` tag + ⚠ banner. The former `check_and_alert` loss engine has been retired; all loss / fund-negative rules are now v2 agents (see Agent Framework section).

### Webhook / Deployment (`webhook/`)
- **`deploy.sh`** — Unified deploy script. Called as `deploy.sh <ENV> <REF>` where ENV is `prod|dev`. Common section handles git update, config merge, writing `deploy_branch` into `backend_config.yaml`, service restart, and `notify_deploy.py`. Env-specific sections: nginx sync (prod only), `pip install` + `npm run build` (prod/dev).
- **`notify_deploy.py`** — Standalone deploy notification script; sends Telegram + email immediately after each deploy without importing app modules (avoids log file permission conflict with running service). Reads `backend_config.yaml` and `secrets.yaml` directly. Gated by `cap_in_dev` and `notify_on_startup` flags
- **`initial_deploy.sh`** — One-time setup script; run once on a fresh server before first push. Accepts `--env prod|dev|both`, `--ssh-key-prod`, `--ssh-key-dev`, `--branch-dev`. Automates everything except secrets, certbot, Cloudflare DNS, and GitHub webhook
- **`hooks.json`** — Single `ramboq-deploy` hook; validates push event, repo name, and HMAC-SHA256 signature; passes `ref` to `dispatch.sh`. **Deployed to `/etc/webhook/hooks.json`** (independent of all deployment directories). Copy manually after changes: `sudo cp /opt/ramboq/webhook/hooks.json /etc/webhook/hooks.json && sudo systemctl restart ramboq_hook.service`
- **`dispatch.sh`** — Thin router at `/etc/webhook/dispatch.sh`; reads branch from `ref`, calls `deploy.sh` with the right ENV arg (`prod` for `main`, `dev` for everything else). Copy after changes: `sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh`
- **`ramboq_hook.service`** — Webhook listener, port 9001; shared service handles all branches; all output (stdout+stderr) goes to `hook.log`
- **`log-request.sh`** — Logs raw incoming webhook requests

---

## Config Files (`backend/config/`)

| File | Tracked | Contents |
|---|---|---|
| `backend_config.yaml` | **Yes — tracked** | `retry_count`, `conn_reset_hours`, relative log paths, log levels, `enforce_password_standard`/`cap_in_dev`/`genai`/`mail`/`telegram`/`notify_on_startup` flags, alert thresholds, market segment definitions; deploy scripts merge new repo config with server's preserved flags |
| `frontend_config.yaml` | Yes | All page content, nav labels, Gemini prompts/params, Mermaid diagrams, fallback market report |
| `constants.yaml` | Yes | 250+ ISD country codes, profile section keys |
| `secrets.yaml` | **No — gitignored** | SMTP creds, Kite API keys/TOTP per account, `cookie_secret`, `kite_login_url`, `kite_twofa_url`, `gemini_api_key`, `telegram_bot_token`, `telegram_chat_id`, `alert_emails` |
| `grammars/orders.yaml` | Yes — tracked | Language-agnostic command grammar for order entry (tokens declared by role/kind/values/parse/required-when). Source of truth for both frontend console autocomplete and future backend agent-builder/admin-shell. Python and JS each plug in their own suggester functions keyed by `kind`. |

### Reusable Command Grammars (`backend/config/grammars/`)
- **`orders.yaml`** — declarative token grammar for order-entry commands; loadable from Python for backend agent/admin-shell use
- **Frontend bridge:** [frontend/src/lib/command/grammars/orders.yaml](frontend/src/lib/command/grammars/orders.yaml) is a symlink into `backend/config/grammars/`; [frontend/src/lib/command/grammars/orders.js](frontend/src/lib/command/grammars/orders.js) loads it via Vite `?raw` import + `js-yaml` (added to `frontend/package.json`) and wires JS suggesters

`secrets.yaml` must be **hand-placed on the server** — never in git. `initial_deploy.sh` creates `backend_config.yaml`; subsequent deploys merge: repo config is the base (picks up new fields), only `enforce_password_standard`/`cap_in_dev`/`genai`/`telegram`/`mail`/`notify_on_startup` are overlaid from the server's saved copy. `deploy_branch` is always set fresh by the deploy script — never preserved.

### Production capabilities — `cap_in_dev` is a dict, not a scalar

`cap_in_dev` in `backend_config.yaml` is now a nested dict of per-capability flags. On **prod** (`deploy_branch == 'main'`) every capability is always on regardless of these flags. On **dev / any non-main branch** each flag independently toggles its capability.

```yaml
cap_in_dev:
  genai:            True   # GenAI market update (Gemini)
  telegram:         True   # Telegram notifications
  mail:             True   # Email notifications (SMTP)
  notify_on_deploy: True   # Deploy-OK ping on restart
  market_feed:      True   # Google News RSS feed for /api/news
```

**Gate helper**: `is_enabled('<cap>')` in `backend/shared/helpers/utils.py` returns `True` on the `main` branch unconditionally, otherwise reads `cap_in_dev.<cap>`.

**`is_prod_capable()`** is kept as a back-compat shim (True on prod or when any flag is truthy on dev). New code should prefer `is_enabled('<cap>')`.

**Adding a new production capability**:
1. Append `new_cap: True` under `cap_in_dev` in `backend_config.yaml`.
2. Gate usage with `is_enabled('new_cap')`.
3. No `deploy.sh` edit — the preserve loop uses a pattern match on `startswith("alert_")` for alert keys AND copies the entire `cap_in_dev` dict across deploys.

**Historical rename**: `notify_on_startup → notify_on_deploy`. No `news_in_dev` top-level flag — it's `cap_in_dev.market_feed` now.

---

## Alert and Notification System

### Message Types and Prefixes

| Event | Telegram prefix | Email subject prefix |
|---|---|---|
| Market open summary | `Open` | `RamboQuant Open: ` |
| Intra-day agent fire | `Agent` | `RamboQuant Agent: ` |
| Market close summary | `Close` | `RamboQuant Close: ` |
| Deploy notification | `Deploy OK` | `RamboQuant Deploy OK: ` |

User-facing vocabulary: **Agent** (rule) → **Alert** (runtime event) → **Notify** (delivery) → **Action** (side-effect). Subjects use "Agent" so the UI label, Telegram prefix, and email subject line all match.

### Timestamp Format
All alerts, summaries, and deploy notifications use dual-timezone format generated by `timestamp_display()` in `date_time_utils.py`:
`Mon, March 30, 2026, 09:30 AM IST | Mon, March 30, 2026, 10:00 PM EDT`
The EST side uses `%Z` so it correctly shows `EST` in winter and `EDT` in summer.

### Open/Close Summary Format
Sent per segment (Equity and Commodity independently):
- **Telegram**: `Open [branch] — Equity — <timestamp>` + `⚠ Branch: <name>` line (non-main only) + `<code>` monospace block
- **Email subject**: `RamboQuant Open: [branch]Equity — <timestamp>` (branch tag omitted on main)
- **Email body**: yellow banner for non-main + HTML `<table>` sections for Holdings, Positions, and Funds
- Holdings table: Account | Cur Val | P&L | P&L% | Day Loss | Day Loss%
- Positions table: Account | P&L
- Funds table: Account | Cash | Avail Margin | Used Margin | Collateral
- Accounts shown as masked values (ZG#### / ZJ####)

### Agent Alert Format
One row per breached threshold (abs, pct, and fund checks fire separate rows):
- Columns: Type | Account | Kind | Value | Detail | Abs Thr | Pct Thr
- Type ∈ `Holdings`, `Positions`, `Funds`
- Kind tags the rule that fired (`Static %`, `Static ₹`, `Rate ₹/min`, `Rate %/min`, `Cash < 0`, `Margin < 0`)
- Funds rows fired when `cash < 0` or `avail margin < 0` for any account (subject to cooldown)
- `—` shown for columns not applicable to that rule
- Email uses HTML `<table>` with per-kind row colour (yellow = static, red = rate, grey = funds); Telegram uses `<code>` monospace block in the narrow 2-line-per-row format
- Rows sorted `Holdings → Positions → Funds`, per-account before `TOTAL` — every agent that fires on the same tick consolidates into one message

### Intra-day loss rules — now v2 agents

Every loss / fund-negative rule ships as a `loss-*` Agent row (grammar tree
of metric/scope/op/value leaves). See `_LOSS_AGENTS` in
`backend/api/algo/agent_engine.py` for the 14 seeded rules. Default floors
(editable live from the /agents page, per agent):

| Scope (scope token) | Holdings % | Positions % | Positions ₹ |
|---|---|---|---|
| Per account (`holdings.any_acct` / `positions.any_acct`) | −3.0 % | −2.0 % | −₹30,000 |
| Total (`.total`)                                         | −5.0 % | −2.0 % | −₹50,000 |

Rate rules use the `day_rate_abs` / `day_rate_pct` / `pnl_rate_abs` /
`pnl_rate_pct` metrics; defaults are −₹2k/min (acct) and −₹4k/min (total)
for holdings, −₹3k/min (acct) and −₹6k/min (total) for positions, and
−0.15 %/min (holdings) / −0.25 %/min (positions) scope-agnostic. Two fund
agents (`loss-funds-cash-negative` / `loss-funds-margin-negative`) fire on
`cash < 0` and `avail_margin < 0`.

**Global gates** (engine-wide; `alert_*` keys in `backend_config.yaml`):

- **Market hours**: run_cycle skips `schedule: market_hours` agents outside segment-open hours.
- **Baseline offset**: `alert_baseline_offset_min` (15). Rate agents stay silent for this long after session start.
- **Rate window**: `alert_rate_window_min` (10) — minutes of P&L history used to compute ΔP&L/Δmin.
- **Cooldown**: `alert_cooldown_minutes` (30). After a fire, re-fire requires the cooldown AND (|Δpnl| ≥ `alert_suppress_delta_abs` (₹15k) OR |Δpct| ≥ `alert_suppress_delta_pct` (0.5 %)). Flat loss ⇒ silent for the rest of the session.
- **Session rollover**: in-memory suppression state wipes on date change.

`deploy.sh` preserves every `alert_*` key across deploys.

### Telegram Setup
- Bot token and group chat_id stored in `secrets.yaml` as `telegram_bot_token` and `telegram_chat_id`
- Group: **RamboQuant Alerts** (`-5227999198`)
- Bot: **@RamboQuantBot**

### Email Recipients
```yaml
# secrets.yaml
alert_emails:
  - "rambo@ramboq.com"
```

---

## Market Segments and Hours

Defined in `backend_config.yaml` under `market_segments`. Background thread handles each segment independently.

| Segment | Config key | Exchanges | Hours (IST) | Holiday source |
|---|---|---|---|---|
| Equity | `equity` | NSE, BSE, NFO, CDS | 09:15–15:30 | `kite.holidays("NSE")` |
| Commodity | `commodity` | MCX | 09:00–23:30 | `kite.holidays("MCX")` |

- Open summary sent `open_summary_offset_minutes` (default 15) after segment open; close summary sent `close_summary_offset_minutes` (default 15) after segment close
- Holiday calendars loaded at startup, refreshed on new year
- Weekends (Sat/Sun) are treated as closed across all paths: `is_market_open()` and `_task_close()` in `backend/api/background.py`. Special Saturday sessions (Muhurat etc.) need an explicit override
- Holdings always belong to equity segment; positions are filtered by `exchange` column

---

## Background Tasks (`backend/api/background.py`)

| Action | Timing |
|---|---|
| Market update cache warm | Immediately at app startup |
| Market update pre-fetch | Once per day at `market_refresh_time` (08:30 IST) |
| Performance data pre-fetch | Every `performance_refresh_interval` (5 min) during market hours |
| Open summary (per segment) | `open_summary_offset_minutes` (15) after segment open, once per day |
| Close summary (per segment) | `close_summary_offset_minutes` (15) after segment close, once per day |
| Loss alert check | Every performance fetch during market hours |
| Agent engine `run_cycle()` | Every performance fetch; skips `schedule: market_hours` agents when no segment is open |

---

## Multi-Account Kite IP Binding

Kite Connect restricts one IP per app. Each Zerodha account uses a separate Kite app (different API key), so multiple accounts on the same server need different source IPs.

**Solution:** All accounts use IPv6 addresses from the server's `/48` subnet (`2a02:4780:12:9e1d::/48`). Each account binds to a unique IPv6 via `source_ip` in `secrets.yaml`. Every account **must** have `source_ip` set — without it, the OS may choose IPv4 or IPv6 unpredictably.

| Account | Source IP | Kite Whitelist |
|---|---|---|
| ZG0790 | `2a02:4780:12:9e1d::2` | `2a02:4780:12:9e1d::2` |
| ZJ6294 | `2a02:4780:12:9e1d::3` | `2a02:4780:12:9e1d::3` |
| (future) | `2a02:4780:12:9e1d::4` | `2a02:4780:12:9e1d::4` |

Server IPv4 (`69.62.78.136`) is **not used** for Kite — only for web traffic. `::1` is reserved as the server's primary IPv6. Account IPs start from `::2`.

### Adding a new account

1. Choose the next IPv6: `2a02:4780:12:9e1d::N` (N starts at 4 for the next account)
2. Add it to the server: `sudo ip -6 addr add 2a02:4780:12:9e1d::N/48 dev eth0`
3. Make persistent: add to `/etc/netplan/50-cloud-init.yaml` under `addresses:`
4. Add to `secrets.yaml` on **both** server paths (`/opt/ramboq/` and `/opt/ramboq_dev/`):
   ```yaml
   kite_accounts:
     NEW_ACCT:
       source_ip: "2a02:4780:12:9e1d::N"
       api_key: ...
       api_secret: ...
       password: ...
       totp_token: ...
   ```
5. Whitelist `2a02:4780:12:9e1d::N` in the new account's Kite developer console
6. Clear token cache: `rm /opt/ramboq/.log/kite_tokens.json /opt/ramboq_dev/.log/kite_tokens.json`
7. Restart both API services

### Token caching

Access tokens are cached in `.log/kite_tokens.json` (per-environment, gitignored). On startup, cached tokens are restored without login/2FA. Full login only on cache miss or token expiry (23h). Clear the cache file when changing `source_ip` or API credentials.

### Implementation

`_SourceIPAdapter` (in `connections.py`) extends `requests.HTTPAdapter` to set `source_address` on the urllib3 pool manager. Both KiteConnect's internal `reqsession` and the login `session` are patched with this adapter. The adapter is applied to every account that has `source_ip` configured.

---

## Key Patterns

### Caching
In-process TTL cache in `backend/api/cache.py` with per-key locking. `get_nearest_time()` rounds down to the nearest N-minute interval — use it as a cache key when aligning requests to fixed intervals. Background tasks pre-warm the cache before users hit the page.

### Multi-Account Broker Calls
`@for_all_accounts` in `decorators.py` wraps broker functions to iterate all accounts. Each call returns a **list of DataFrames** (one per account). Callers use `pd.concat(..., ignore_index=True)` to merge them.

### Account Masking
`mask_column(col)` in `utils.py` replaces all digits with `#` — `ZG0790` → `ZG####`. Applied in `fetch_holdings` and `fetch_positions` cache functions. All alert and summary messages use masked account values.

### Singleton Connections
`Connections` is a thread-safe singleton. Access it as `connections.Connections()` — never instantiate `KiteConnection` directly. The singleton is initialised once at app startup and reused across requests.

---

## Things to Avoid

- **Do not mock broker API calls in tests** — the `@for_all_accounts` decorator and `Connections` singleton behaviour differs significantly from mocks
- **Do not commit `secrets.yaml`** — it is gitignored; contains API keys, SMTP credentials, cookie secrets, Telegram token. Changes must be applied via SSH `sed` on both server paths (`/opt/ramboq`, `/opt/ramboq_dev`) individually
- **Do not add branch filter rules to hooks.json** — branch routing is handled in `dispatch.sh`, not in `hooks.json`; `hooks.json` only validates the event, repo, and HMAC
- **Do not use `2>>&1` in systemd ExecStart** — use `2>&1`; the `>>` append variant causes bash syntax errors in service files
- **Always `chown www-data` after manual server operations** — any file created or modified on the server via SSH (git commands, scp, manual edits) must be owned by `www-data` or deploy scripts will fail silently. After any manual work run: `sudo chown -R www-data:www-data /opt/ramboq/.git /opt/ramboq/.log /opt/ramboq_dev/.git /opt/ramboq_dev/.log`
- **Weekends are hardcoded as closed** in `is_market_open()` and `_task_close()` — all alert/summary paths skip Sat/Sun. Special Saturday trading sessions need an explicit override

---

## API Architecture (Litestar + SvelteKit)

### Key Technologies
- **API framework**: Litestar 2.x with msgspec.Struct schemas (~10× faster than pydantic)
- **DataFrame**: Polars for API route aggregation; pandas in broker/alert layer
- **Database**: PostgreSQL 17 via SQLAlchemy 2.x async + asyncpg. `ramboq` (prod/main) and `ramboq_dev` (dev/non-main). Selected by `deploy_branch`.
- **Background**: Four asyncio tasks: market warm, performance refresh, close summaries, expiry auto-close
- **Auth**: JWT HS256 (24h TTL), PBKDF2-SHA256 passwords, admin approval for partners
- **Algo**: Adaptive limit-order chase engine for expiry auto-close (no market orders)
- **Holidays**: NSE official API (`nseindia.com/api/holiday-master`) for NSE/NFO/MCX/CDS
- **SEO**: OG/Twitter cards, JSON-LD, sitemap.xml, robots.txt, per-page titles

### Database
- **PostgreSQL** on server, port 5432
- Credentials in `secrets.yaml`: `db_user`, `db_password`
- `deploy_branch == 'main'` → `ramboq`; any other → `ramboq_dev`
- Tables: `users` (32 cols), `algo_orders`, `algo_events` — auto-created on startup

### API File Map
- **`backend/api/app.py`** — Litestar app; startup: init_db + background tasks; serves SvelteKit build
- **`backend/api/database.py`** — PostgreSQL via asyncpg; DB selected by deploy_branch
- **`backend/api/models.py`** — User (32 cols), AlgoOrder, AlgoEvent
- **`backend/api/background.py`** — Four tasks: market, performance (sends open summary + loss alerts directly), close (sends close summary directly), expiry check (09:20 IST daily)
- **`backend/api/algo/chase.py`** — Reusable adaptive limit-order chase engine
- **`backend/api/algo/expiry.py`** — Expiry-day auto-close: scan ITM/NTM, chase-close positions
- **`backend/api/algo/agent_engine.py`** — Declarative agent runner. `run_cycle()` enforces each agent's `schedule` field — agents with `schedule: market_hours` are skipped when no market segment is open, preventing stale NSE equity P&L alerts from firing during MCX-only hours (15:30–23:30). `seed_agents()` syncs the `schedule` field on existing DB rows and forces built-in agents to `inactive` when the YAML definition marks them so; user-customized conditions/cooldown/events/actions are preserved.
- **`backend/api/routes/algo.py`** — Agents API + WebSocket `/ws/algo` + `POST /grammar/reload`
- **`backend/api/routes/grammar.py`** — Admin token CRUD (`/api/admin/grammar/tokens*`); the UI for this lives at `/admin/tokens` (page title "Tokens")
- **`backend/api/routes/simulator.py`** — Market simulator control plane (`/api/simulator/*`); pairs with `backend/api/algo/sim/driver.py`
- **`backend/api/routes/auth.py`** — Login (24h JWT), register (pending approval), me, logout
- **`backend/api/routes/admin.py`** — Create/approve/reject/update users, logs, exec

### Built-in Agents (seeded from YAML)
Summary agents (`nse_open_summary`, `nse_close_summary`, `mcx_open_summary`, `mcx_close_summary`) are **`status: "inactive"` by default** — `_task_performance` and `_task_close` in `backend/api/background.py` already send open/close summaries directly, so enabling the agents would cause duplicate alerts. `seed_agents()` force-resets these four to inactive on every startup.

**Loss agents** (prefix `loss-`) cover the 14 static + rate loss rules plus 2 fund negatives. They now ship **active** by default — `alert_utils.check_and_alert` is retired. Toggle individually from the `/agents` page.

### SvelteKit Pages (routes under `frontend/src/routes/(algo)/`)
- **`+layout.svelte`** — algo-site top nav: Dashboard · Terminal · Agents · Orders · Users · Tokens · Simulator; polls `/api/simulator/status` and renders the sticky red **SIMULATOR ACTIVE** banner on every algo page while a sim is running.
- **`performance/`** (public) and **`dashboard/`** (admin, same `PerformancePage.svelte` component) — timestamp + Refresh · account dropdown + Positions/Holdings tabs in one row · Fund Balances · active-tab Summary + table. Performance page **always** shows real Kite data; the background refresh keeps going even while the simulator is active.
- **`market/`** — AI market report with timestamp
- **`signin/`** — Sign In / Register (name, email, phone)
- **`admin/`** — User management with full partner fields
- **`admin/tokens/`** — Agent Tokens page (Condition / Notify / Action tabs), create/edit custom tokens, Reload Registry. UI label is "Tokens"; the DB table and Python class keep their legacy names (`grammar_tokens`, `GrammarRegistry`) because the data model IS a grammar in the compiler-theory sense. Route: `/admin/tokens`.
- **`admin/simulator/`** — Market simulator control plane. Scenario dropdown · Seed (Scripted / Live / Live+scenario) · Rate · Load live book · Start / Stop / Step / Run cycle / Clear sim. Shared `LogPanel` embedded at the bottom, defaulted to the Simulator tab (streams per-symbol LTP diffs in real time). See **Simulator** section below.
- **`agents/`** (formerly `/algo`) — Agents page: grouped compact rows (Loss & Risk / Summaries / Automation / Other), click-to-expand, Edit with live condition validation, per-row "Run in Simulator" button that deep-links to `/admin/simulator?agent_id=<id>`. The Agent-events panel auto-scopes: real events when sim is idle, sim events when a sim is running.
- **`console/`** — Terminal: command textarea + output + live log (equal panels)
- **`orders/`** — Order management

---

## Agent Framework

Ramboq's risk + automation engine is built around four words:

| Word | Meaning |
|---|---|
| **Agent** | A rule row (DB: `agents`) with `condition + notify + actions + metadata`. Seeded from `BUILTIN_AGENTS` in `agent_engine.py` (14 loss rules + 2 fund negatives ship active by default) and extensible via the `/agents` UI. |
| **Alert** | The runtime event an agent emits when its condition fires. Persisted to `agent_events` with a `sim_mode` flag so real fires can be separated from simulated ones. |
| **Notify** | A delivery channel (`telegram / email / websocket / log`). |
| **Action** | A side-effect the alert invokes (order placement, monitoring, modify, cancel, close, flag-set, …). Handlers in `actions.py`; real broker wiring lands per-action as each is promoted out of stub mode. |

### End-to-end flow on a real tick

```
_task_performance (background.py, every 5 min during market hours)
  └─ fetch_holdings / fetch_positions / fetch_margins  ← live Kite data
     └─ summarise_holdings / summarise_positions       ← per-account + TOTAL
        └─ run_cycle(ctx)                              ← agent_engine.py
           └─ for each active agent:
              1. schedule gate  — skip market_hours agents outside session
              2. cooldown gate  — skip if last fire was within cooldown_minutes
              3. baseline gate  — skip rate-metric agents for first 15 min
              4. evaluate()     — walk condition tree (agent_evaluator.py)
              5. suppress gate  — refire only if |Δpnl| or |Δpct| is material
              6. if matches: dispatch (telegram/email/ws/log) + execute(actions)
              7. write agent_events row, update last_triggered_at / status
```

Tokens referenced in a condition (metric `pnl`, scope `positions.any_acct`,
operator `<=`, value `-30000`) are resolved lazily via `GrammarRegistry`, so
adding a new metric is one DB row plus one resolver function — no engine
change.

### Tokens (condition / notify / action) — extensible via DB

The **Tokens page** (`/admin/tokens`) is the UI over the `grammar_tokens`
table. The engine ships with a full set of system tokens, seeded on every
boot from `backend/api/algo/grammar.py`; operators can toggle those on/off
and add custom tokens via the page. Each row:

| Column | Purpose |
|---|---|
| `grammar_kind` | `condition` / `notify` / `action` |
| `token_kind` | `metric` / `scope` / `operator` (condition), `channel` / `format` / `template` (notify), `action_type` (action) |
| `token` | The identifier authors write into an agent (e.g. `pnl`, `positions.any_acct`, `<=`, `telegram`, `place_order`). |
| `value_type`, `units` | Typing so the admin UI can render + validate. |
| `resolver` | Python dotted path to the function that implements the token (metric resolver, scope selector, action handler). |
| `params_schema` | JSON schema for `action_type` params (account, symbol, side, qty, …). |
| `enum_values`, `template_body` | For enum value types and notify templates. |
| `is_system`, `is_active` | System tokens ship with code and are seeded on every boot; operators can toggle but not delete. Custom tokens have full CRUD. |

`GrammarRegistry` (in `backend/api/algo/grammar_registry.py`) is a singleton that loads the catalog into an in-memory dispatch table at startup and on `/api/admin/grammar/reload`. Adding a new capability is one DB row plus one Python function — no engine or schema change.

### Condition tree schema (v2 grammar)

```
condition  ::=  leaf
             |  { "all": [condition, ...] }      AND
             |  { "any": [condition, ...] }      OR
             |  { "not": condition }             NOT

leaf       ::=  { "metric": <metric-token>,
                  "scope":  <scope-token>,
                  "op":     <op-token>,
                  "value":  <literal> }
```

`backend/api/algo/agent_evaluator.py`:
- `evaluate(cond, ctx) -> list[match]` — tree walker; empty list means no fire.
- `validate(cond) -> list[str]` — dry-check; every referenced token must exist in the registry. Used by `POST /api/agents/validate-condition` and surfaced in the `/agents` editor's Validate button.
- `Context` — bundles `sum_holdings`, `sum_positions`, `df_margins`, `alert_state` (for rate history), `now`, `segments`, `rate_window_min`, `agent`.

The v1 `field/operator/rules` evaluator has been retired; every agent must use the grammar tree above. `run_cycle` calls `agent_evaluator.evaluate` directly.

### Action grammar

Action tokens (seeded): `place_order`, `modify_order`, `cancel_order`, `cancel_all_orders`, `chase_close_positions`, `monitor_order`, `deactivate_agent`, `set_flag`, `emit_log`. Every token carries a typed `params_schema` with `required` / `enum` / `default` / `token_ref_ok` fields so the admin UI and the runtime agree on the shape. Handlers live in `backend/api/algo/actions.py` — currently stubs that log the invocation; real broker wiring lands as each action type is promoted out of stub mode.

### Admin endpoints

| Route | Purpose |
|---|---|
| `GET /api/admin/grammar/tokens[?grammar=<kind>]` | List catalog, optional filter |
| `GET /api/admin/grammar/tokens/{id}` | Read one |
| `POST /api/admin/grammar/tokens` | Create custom token |
| `PATCH /api/admin/grammar/tokens/{id}` | Update. System tokens restrict to `is_active` toggle. |
| `DELETE /api/admin/grammar/tokens/{id}` | Custom only; system returns 400. |
| `POST /api/admin/grammar/reload` | Hot-rebuild the registry after edits. |
| `POST /api/agents/validate-condition` | Dry-check a v2 condition tree against the live catalog. |

All gated by `admin_guard`. Every mutating endpoint calls `REGISTRY.reload()` automatically.

### Deploy automation
`deploy.sh` handles: git pull → pip install → npm build → restart API service → notify

### Logging
- API uses `RAMBOQ_LOG_PREFIX=api_` env var for log file naming
- 3 handlers: rotating log file (5MB × 5), rotating error file, console

---

## Simulator

The simulator feeds fabricated per-symbol **positions** + margins into
the **same** agent engine the real pipeline uses, so alerts, actions, and
event-logging are all exercised end-to-end without touching the broker.
**No code branches in the hot path** — the engine only sees a `sim_mode`
flag on the context dict and tags downstream artefacts with `[SIMULATOR]`
prefixes.

**Positions-only by design.** Holdings aren't simulated — intraday risk
lives in F&O positions + fund-negatives, and that's the scope. Agents
that check holdings metrics (`day_pct`, `day_rate_abs`, `day_rate_pct`)
validate against live production data only. Running **Run in Simulator**
on such an agent returns a clear 400 explaining this.

### Architecture — Model B (per-symbol price driver)

```
scenario.yaml (moves)      ┌────────────────────────┐
        │                  │    Real background     │
        ▼                  │    _task_performance   │    
   SimDriver       ←─?──→  │   (stays live, only    │ ← Kite API
  (per-symbol state)       │    run_cycle gated)    │
        │ every rate_ms    └──────────┬─────────────┘
        ▼                             │
   _apply_moves (glob)                ▼
    last_price ← move               run_cycle(ctx)
    recompute pnl                   (shared — no sim branch)
        │                             │
        ▼                             ▼
   summarise_positions          dispatch · actions
   (sum_holdings empty)         → Telegram/email/ws/log
        │                       → agent_events (sim_mode=True)
        ▼                       → algo_orders (mode='sim')
   run_cycle(ctx,
     sim_mode=True,
     only_agent_ids=...,
     bypass_schedule=True)
```

Key files:

| Path | Purpose |
|---|---|
| `backend/api/algo/sim/driver.py` | `SimDriver` singleton — per-symbol state, tick loop, move primitives, glob scope matching, live-book seeding |
| `backend/api/algo/sim/scenarios.yaml` | Scenario catalog (slug, name, mode, optional `initial` per-symbol rows, `ticks` with move primitives) |
| `backend/api/routes/simulator.py` | `/api/simulator/*` endpoints (admin-guarded) |
| `frontend/src/routes/(algo)/admin/simulator/+page.svelte` | Control plane UI |

### State shape

`_positions_rows` is a list of per-symbol dicts matching what
`broker_apis.fetch_positions` returns (`tradingsymbol`, `quantity`,
`average_price`, `last_price`, `close_price`, …). When a move changes
`last_price`, `_recompute_position_row` derives `pnl`. `dataframes()`
calls the same `summarise_positions` helper the live background task uses,
producing per-account + TOTAL aggregates in the exact shape the evaluator
expects. `sum_holdings` is always an empty frame — holdings aren't
simulated.

### Move primitives (in scenario `ticks`)

```yaml
- at: 0
  moves:
    - {type: pct,         scope: "positions.**",         value: -0.03}   # -3% LTP
    - {type: abs,         scope: "positions.ZG*.NIFTY*", value: -25}     # ₹-25/share
    - {type: random_walk, scope: "positions.**", drift: -0.001, vol: 0.005}
    - {type: target_pnl,  scope: "positions.ZG*.*",      value: -50000}  # solve ΔLTP
    - {type: set_margin,  scope: "margins.ZG####",
        fields: {avail opening_balance: -1500, net: -2500}}
```

- **`pct`** / **`abs`** — LTP × (1+v) or LTP + v.
- **`random_walk`** — `LTP ← LTP × (1 + drift + vol·N(0,1))`; seedable via scenario-level `seed:`.
- **`target_pnl`** — solves `ΔLTP × Σqty = target − currentPnl` uniformly; refuses mixed long/short.
- **`set_margin`** — price-decoupled; real Kite margin math (SPAN/ELM/product type) is never simulated.

**Scope glob** is `section.account.tradingsymbol` with `*` (single-segment) and `**` (any remaining path). Examples: `positions.**`, `positions.ZG*.*`, `positions.*.NIFTY*`, `positions.ZG####.NIFTY25APRFUT`. `holdings.*` globs are silently ignored (positions-only sim).

### Shipped scenarios

`generic-crash` (−3% over 3 ticks), `generic-euphoria` (+3%), `extreme-crash` (−19% over 3 ticks), `extreme-euphoria` (+19%), `random-walk` (seeded GBM). All work against any seeded book. The synthesizer covers per-agent tests; scenarios.yaml holds only these 5 book-wide stress tests.

### Seeding modes

| `seed_mode` | Initial state |
|---|---|
| `scripted` | Scenario's `initial.positions / margins` blocks (fails loudly if empty) |
| `live` | Fresh broker fetch via `SimDriver.seed_live()` — positions + margins snapshotted (holdings skipped) |
| `live+scenario` | Live book first, scripted `initial` rows layered on top |

Scenarios with no `initial:` (all 5 shipped ones, plus synthesized scenarios from Run-in-Simulator on holdings-agnostic agents) require `seed_mode=live` or `live+scenario`; attempting `scripted` start raises a clear error.

### Gates disabled during a sim

For a sim run, `run_cycle` is called with `bypass_schedule=True` **and** optionally `only_agent_ids=[...]`. That skips:

- the schedule gate (`market_hours` agents run even at 3 AM IST),
- the cooldown gate (repeated "Run in Simulator" clicks always fire),
- the baseline gate (rate agents fire immediately, not after 15 min),
- the suppression gate,
- and — critically — does **not** mutate the agent row (no cooldown / trigger count leak into real-market state).

The simulator owns its own `_sim_alert_state` dict, so rate history and suppression state never cross with the real pipeline.

### Interaction with the real background task

`_task_performance` keeps running while a sim is active: it fetches live Kite data, refreshes the performance cache, and sends open/close summaries. Only the live `run_cycle` call is skipped (`sim_active` short-circuit at `background.py` ~line 319) — that way `/performance` stays fresh with real data and the only thing that stops firing is the live agent engine.

### `sim_mode` = `True` effects

| Surface | Tag |
|---|---|
| Telegram message | `SIMULATOR` prefix + red "SIMULATOR RUN — fabricated market data" line |
| Email subject | `RamboQuant SIMULATOR Agent: …` |
| Email body | Red banner `🚨 SIMULATOR RUN — fabricated market data, not a real alert` |
| `agent_events.sim_mode` | `TRUE` |
| `algo_orders.mode` | `'sim'` (and `engine='sim'`) |
| Log prefix | `[SIMULATOR]` |
| WebSocket `agent_alert` payload | `sim_mode: true` |

### Simulator API — `/api/simulator/*`

| Route | Purpose |
|---|---|
| `GET /scenarios` | List available scenarios (slug / name / mode / has_initial / tick count) |
| `GET /status` | Driver snapshot (active, scenario, seed_mode, tick_index, counts, only_agent_ids) |
| `POST /start` | Body: `{scenario, rate_ms, seed_mode, agent_ids?}` |
| `POST /stop` | Halt |
| `POST /step` | Apply one tick (deterministic debug) |
| `POST /seed-live` | Snapshot live positions + margins into `_live_snapshot` (holdings skipped — positions-only sim) |
| `POST /run-cycle` | Immediately run the agent engine against current sim state |
| `POST /clear` | Delete every sim-mode row from `agent_events` + `algo_orders` |
| `GET /events/recent?limit=N` | Recent `sim_mode=True` agent events |
| `GET /orders/recent?limit=N` | Recent `mode='sim'` algo orders |
| `GET /ticks/recent?limit=N` | Rolling driver tick log (oldest-first) with per-symbol diffs |

Gated by `admin_guard` + the per-branch `cap_in_<branch>.simulator` flag in `backend_config.yaml` (dev default: on, prod default: off).

### Running the simulator

- **Default path**: pick a scripted scenario (e.g. `crash-open`) → Start.
- **Stress-test your real book**: press **Load live book** → switch Seed to **Live + scenario** → pick `generic-crash` or `random-walk` → Start.
- **Dry-fire one agent**: on `/agents`, click **Run in Simulator** on a row → arrives at `/admin/simulator?agent_id=<id>` with the agent armed → pick a scenario → Start. The agent fires regardless of its `status`, `schedule`, cooldown, or baseline gate; no real agent state is mutated.

Auto-stops after 30 minutes so a forgotten sim can't bleed forever.

---

## Refactoring Notes

| Area | Note |
|---|---|
| Regex validators | `validate_email()`, `validate_phone()` etc. in `utils.py` recompile regex on every call. Worth precompiling to module-level constants if form submissions become a bottleneck |
| Parallel broker calls | `fetch_holdings`, `fetch_positions`, `fetch_margins` broker calls run concurrently via `ThreadPoolExecutor` in the API background tasks |

---

## Log Files (on server)

Prod and dev logs are fully separated. The webhook listener is a shared service so its logs stay under prod.

**Prod `/opt/ramboq/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy.sh prod` | Prod deploy output (main branch) |
| `hook.log` | `ramboq_hook.service` | All webhook listener output (stdout+stderr combined) |
| `incoming_requests.log` | `log-request.sh` | Raw webhook requests |
| `api_error_file` | `ramboq_api.service` tee | All API stdout+stderr |
| `api_short_error_file` | `ramboq_logger.py` | Last 50 Python error lines |
| `api_log_file` | `ramboq_logger.py` | Full API app log (5MB rotating) |
| `api_short_log_file` | `ramboq_logger.py` | Last 50 API app log lines |

**Dev `/opt/ramboq_dev/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy.sh dev` | Dev deploy output (non-main branches) |
| `api_error_file` | `ramboq_dev_api.service` tee | All API stdout+stderr |
| `api_short_error_file` | `ramboq_logger.py` | Last 50 Python error lines |
| `api_log_file` | `ramboq_logger.py` | Full API app log (5MB rotating) |
| `api_short_log_file` | `ramboq_logger.py` | Last 50 API app log lines |

> Both environments use the same relative `.log/` paths — no per-environment config changes needed. `notify_on_startup` differs per environment (`True` on dev, `False` on prod) and is preserved across deploys.

---

## Common Tasks — Where to Make Changes

| Task | Files to edit |
|---|---|
| Add a new page | Create SvelteKit route under `frontend/src/routes/<newpage>/` and add nav entry in `+layout.svelte` |
| Change page content (text, FAQs, etc.) | `backend/config/frontend_config.yaml` |
| Change AI market report prompt | `backend/config/frontend_config.yaml` — `genai_system_msg`, `genai_user_msg`, `genai_temperature`, `genai_max_tokens`, `genai_model` |
| Change connection retry behaviour | `backend/config/backend_config.yaml` — `retry_count`, `conn_reset_hours` |
| Change log verbosity | `backend/config/backend_config.yaml` — `file_log_level`, `error_log_level`, `console_log_level` |
| Add a new broker account | `backend/config/secrets.yaml` — add entry under `kite_accounts` |
| Change deploy branch routing | `webhook/dispatch.sh` — the `if/elif/else`; copy to server after changes: `sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh` |
| Change browser tab title or SEO meta tags | `frontend/src/app.html` and per-route `<svelte:head>` sections |
| Change footer text | `backend/config/frontend_config.yaml` — `footer_name`, `footer_text2`, `footer_mobile_text3`, `footer_desktop_text3` |
| Change a loss threshold | Edit the corresponding `loss-*` agent from the `/agents` page (its condition tree's `value` is the threshold). Engine-wide knobs stay in `backend/config/backend_config.yaml` under `alert_cooldown_minutes`, `alert_rate_window_min`, `alert_baseline_offset_min`, `alert_suppress_delta_abs/_pct`. |
| Change alert recipients | `backend/config/secrets.yaml` on server — `alert_emails`, `telegram_chat_id` |
| Enable/disable deploy notification | `backend/config/backend_config.yaml` on server — `notify_on_startup` (True=dev, False=prod) |
| Add/change market segment hours | `backend/config/backend_config.yaml` — `market_segments` block |
| Change open/close summary timing | `backend/config/backend_config.yaml` — `open_summary_offset_minutes`, `close_summary_offset_minutes` |
| Add/change order-entry command tokens | `backend/config/grammars/orders.yaml` (shared source; frontend picks it up via symlink + `?raw` import) |
| Toggle a built-in agent's default status | `backend/config/agents.yaml` — `seed_agents()` will force built-in agents to match YAML `status` on startup; user-edited conditions/cooldown/events/actions are preserved |
