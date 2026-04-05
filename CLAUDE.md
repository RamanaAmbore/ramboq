# CLAUDE.md — RamboQuant Project Reference

This file is for Claude Code. It provides project context, file map, patterns, and refactoring notes to avoid re-exploring the codebase from scratch each session.

---

## Project Overview

**RamboQuant** is a production web app for RamboQuant Analytics LLP at [ramboq.com](https://ramboq.com). It provides portfolio performance tracking, market updates (via Gemini AI), user onboarding, and investment information.

- **Dual architecture**: Streamlit (legacy) + Litestar API + SvelteKit frontend (migration in progress on `new` branch)
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

### Entry Point
- **`app.py`** — Sets page config, loads CSS/favicon, initialises session state, renders header, routes to page function, renders footer. Page routing is a dict `page_functions = {"about": about, "market": market, ...}` keyed on `st.session_state.active_nav`. On every startup, copies `setup/images/favicon.png` and `setup/streamlit/index.html` into the Streamlit static folder so they survive pip upgrades. Starts background refresh daemon thread.

### Pages (`src/`)
- **`about.py`** — Static content from `ramboq_config['about']`
- **`market.py`** — AI market report via `get_market_update()`; uses cycle date as cache key so it refreshes daily. Wrapped in `@st.fragment(run_every=300)` so browser auto-picks up background-warmed daily data without manual reload. No spinner.
- **`performance.py`** — Three tabs: Funds, Holdings, Positions. Each tab shows: summary (all accounts + TOTAL) first, then per-account detail dataframes, then all-accounts combined dataframe. URL param `?tab=funds|holdings|positions` synced via JS for direct sharing. Fetches broker data via `fetch_margins/holdings/positions(refresh_time)`. Use `refresh_time` consistently — do not call `get_nearest_time()` again mid-function or cache keys diverge. Wrapped in `@st.fragment(run_every=performance_refresh_interval * 60)` — auto-refreshes in sync with background data interval.
- **`profile.py`** — Profile view and update form with nested nominee fields
- **`user.py`** — Sign in / sign up / update password tabs with captcha and email notifications
- **`post.py`** — Investment insights from `ramboq_config['post']`
- **`contact.py`** — Contact form with SMTP notification
- **`faq.py`** — FAQ + Mermaid.js flow diagrams (nav/redemption/succession)
- **`header.py`** — Desktop and mobile nav bars; updates `st.query_params["page"]` and `st.session_state.active_nav`. Sets `?tab=funds` when navigating to performance; clears `tab` param on other pages.
- **`footer.py`** — Copyright, registration number, disclaimer; separate mobile/desktop layouts. Keys: `footer_name`, `footer_text2` (shown on both desktop and mobile), `footer_mobile_text3` (mobile only), `footer_desktop_text3` (desktop only)

### Shared UI (`src/`)
- **`components.py`** — `render_form()`, `write_section_heading()`, `disp_icon_text()`, `write_columns()`
- **`constants.py`** — Streamlit column configs (`holdings_config`, `positions_config`, `margins_config`) and HTML email templates
- **`utils_streamlit.py`** — `@st.cache_data` wrappers (no spinner — background thread handles pre-warming) for all broker data fetches and `get_market_update()`; `style_dataframe()` (right-aligns numeric columns); `reset_form_state_vars()`; `show_status_dialog()`

### Helpers (`src/helpers/`)
- **`broker_apis.py`** — `fetch_holdings()`, `fetch_positions()`, `fetch_margins()` — each decorated with `@for_all_accounts`; returns a list (one DataFrame per account). `fetch_holidays(exchange)` — calls `kite.holidays(exchange)`, returns set of holiday dates for the current year; used by background refresh for NSE and MCX calendars.
- **`connections.py`** — `Connections` singleton (extends `SingletonBase`) holds one `KiteConnection` per account; handles Kite 2FA login, TOTP, and access token refresh. Re-authenticates after 23 hours (`conn_reset_hours` in `backend_config.yaml`)
- **`decorators.py`** — `@for_all_accounts` iterates all accounts or a single one; `@retry_kite_conn()` retries with `test_conn=True` from attempt 2; `@track_it()` logs execution time; `@lock_it_for_update` / `@update_lock` for thread safety
- **`singleton_base.py`** — Thread-safe singleton via double-checked locking; `_instances` dict keyed by class
- **`utils.py`** — YAML loaders (run at module import), `get_image_bin_file()`, `get_path()`, `get_nearest_time()`, `add_comma_to_df_numbers()`, validators (email, phone, password, PIN, captcha), `CustomDict`
- **`genai_api.py`** — Gemini 2.5 Flash via `google-genai` with Google Search grounding; falls back to `ramboq_config['market']` static content when `genai: False` in `backend_config.yaml` or when Gemini returns empty/None response (rate limiting)
- **`mail_utils.py`** — SMTP via Hostinger; respects `cap_in_dev` and `mail` flags in `backend_config.yaml` before sending. `send_email(name, email_id, subject, html_body)`
- **`date_time_utils.py`** — Indian/EST timezone utilities using `zoneinfo`. `is_market_open(now, holiday_set, market_start, market_end)` — returns True if not in holiday_set, not a weekend, and within time window. Weekends (Sat/Sun) are rejected. Special trading sessions (Muhurat etc.) need an explicit override when reintroduced.
- **`ramboq_logger.py`** — Rotating file handlers (5MB), line-limited handlers (50 lines), queue-based async logging
- **`background_refresh.py`** — Daemon thread started once at app startup. Warms market update cache immediately at startup. During market hours: pre-fetches broker data at each interval boundary; sends open summary (15 min after segment open); fires loss alerts. After market close: sends close summary. Segment-aware — handles Equity (NSE/BSE/NFO/CDS) and Commodity (MCX) independently with separate holiday calendars and open/close times.
- **`alert_utils.py`** — Loss alert and market summary notifications. `send_summary(sum_holdings, sum_positions, ist_display, msg_type, label, df_margins)` — sends open/close summary including a Funds table (Account | Cash | Avail Margin | Used Margin | Collateral) when `df_margins` is provided. `check_and_alert(sum_holdings, sum_positions, alert_state, ist_display, df_margins)` — checks day P&L thresholds AND negative fund balances (cash < 0 or avail margin < 0), fires one row per breached threshold. Both send via Telegram Bot API and SMTP email. Message type prefixes: Telegram `Open|Alert|Close`, email subject `RamboQuant Open:|RamboQuant Alert:|RamboQuant Close:`. Email uses HTML `<table>` formatting; Telegram uses `<code>` monospace block. Non-main branches show `[branch]` tag in all subjects/headers plus `⚠ Branch: <name>` in Telegram and a yellow banner in email body.

### Static Assets (`setup/streamlit/`)
- **`index.html`** — Custom Streamlit entry HTML with RamboQuant Analytics meta tags, OG/Twitter cards, and favicon link. Copied into the Streamlit venv static folder on every deploy and app startup to survive pip upgrades.
- **`favicon.png`** — Reference copy of the Streamlit default favicon (not deployed — source favicon is `setup/images/favicon.png`)

### Webhook / Deployment (`webhook/`)
- **`deploy.sh`** — Unified deploy script. Called as `deploy.sh <ENV> <REF>` where ENV is `prod|dev`. Common section handles git update, config merge, writing `deploy_branch` into `backend_config.yaml`, service restart, and `notify_deploy.py`. Env-specific sections: nginx/static sync (prod only), `pip install` + favicon copy (prod/dev).
- **`notify_deploy.py`** — Standalone deploy notification script; sends Telegram + email immediately after each deploy without importing app modules (avoids log file permission conflict with running service). Reads `backend_config.yaml` and `secrets.yaml` directly. Gated by `cap_in_dev` and `notify_on_startup` flags
- **`initial_deploy.sh`** — One-time setup script; run once on a fresh server before first push. Accepts `--env prod|dev|both`, `--ssh-key-prod`, `--ssh-key-dev`, `--branch-dev`. Automates everything except secrets, certbot, Cloudflare DNS, and GitHub webhook
- **`hooks.json`** — Single `ramboq-deploy` hook; validates push event, repo name, and HMAC-SHA256 signature; passes `ref` to `dispatch.sh`. **Deployed to `/etc/webhook/hooks.json`** (independent of all deployment directories). Copy manually after changes: `sudo cp /opt/ramboq/webhook/hooks.json /etc/webhook/hooks.json && sudo systemctl restart ramboq_hook.service`
- **`dispatch.sh`** — Thin router at `/etc/webhook/dispatch.sh`; reads branch from `ref`, calls `deploy.sh` with the right ENV arg (`prod` for `main`, `dev` for everything else). Copy after changes: `sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh`
- **`ramboq.service`** — Prod systemd unit, port 8502; tee pipes Streamlit output to `error_file` only
- **`ramboq_dev.service`** — Dev systemd unit, port 8503; tee pipes Streamlit output to `error_file` only
- **`ramboq_hook.service`** — Webhook listener, port 9001; shared service handles all branches; all output (stdout+stderr) goes to `hook.log`
- **`log-request.sh`** — Logs raw incoming webhook requests

---

## Config Files (`setup/yaml/`)

| File | Tracked | Contents |
|---|---|---|
| `backend_config.yaml` | **Yes — tracked** | `retry_count`, `conn_reset_hours`, relative log paths, log levels, `enforce_password_standard`/`cap_in_dev`/`genai`/`mail`/`telegram`/`notify_on_startup` flags, alert thresholds, market segment definitions; deploy scripts merge new repo config with server's preserved flags |
| `frontend_config.yaml` | Yes | All page content, nav labels, Gemini prompts/params, Mermaid diagrams, fallback market report |
| `constants.yaml` | Yes | 250+ ISD country codes, profile section keys |
| `secrets.yaml` | **No — gitignored** | SMTP creds, Kite API keys/TOTP per account, `cookie_secret`, `kite_login_url`, `kite_twofa_url`, `gemini_api_key`, `telegram_bot_token`, `telegram_chat_id`, `alert_emails` |

`secrets.yaml` must be **hand-placed on the server** — never in git. `initial_deploy.sh` creates `backend_config.yaml`; subsequent deploys merge: repo config is the base (picks up new fields), only `enforce_password_standard`/`cap_in_dev`/`genai`/`telegram`/`mail`/`notify_on_startup` are overlaid from the server's saved copy. `deploy_branch` is always set fresh by the deploy script — never preserved.

### Production capabilities — `cap_in_dev` and individual flags

Production capabilities (GenAI, Telegram, email) are controlled by `cap_in_dev` (master switch) and individual flags — both must be True:

| Flag | Purpose | Prod | Dev |
|---|---|---|---|
| `cap_in_dev` | Environment master switch | `True` | `True` |
| `genai` | GenAI market update (Gemini) | `True` | `True`/`False` |
| `telegram` | Telegram alert notifications | `True` | `True`/`False` |
| `mail` | Email notifications (SMTP) | `True` | `True`/`False` |
| `notify_on_startup` | Send test Telegram+email on each deploy | `False` | `True` |

**Gate logic:** `is_prod_capable() AND config.get('<flag>')` where `is_prod_capable()` = `cap_in_dev`.

- `cap_in_dev: True` is the tracked default for all environments
- `notify_on_startup: True` on dev so every deploy immediately validates notifications; `False` on prod
- No code change ever needed — flip flags in `backend_config.yaml` on the server

**Adding a new production capability:** add its flag to `backend_config.yaml` (default `False`), gate it with `is_prod_capable() AND config.get('<flag>')` in the relevant module. Add the flag to the preserved keys list in `deploy.sh` (the `for key in ...` loop). Set it to `True` on prod server.

---

## Alert and Notification System

### Message Types and Prefixes

| Event | Telegram prefix | Email subject prefix |
|---|---|---|
| Market open summary | `Open` | `RamboQuant Open: ` |
| Intra-day loss alert | `Alert` | `RamboQuant Alert: ` |
| Market close summary | `Close` | `RamboQuant Close: ` |
| Deploy notification | `Deploy OK` | `RamboQuant Deploy OK: ` |

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

### Loss / Fund Alert Format
One row per breached threshold (abs, pct, and fund checks fire separate rows):
- Columns: Type | Account | Value | Detail | Abs Thr | Pct Thr
- Type can be `Holdings`, `Positions`, or `Funds`
- Funds rows fired when `cash < 0` or `avail margin < 0` for any account (subject to cooldown)
- `—` shown for columns not applicable to that threshold
- Email uses HTML `<table>`; Telegram uses `<code>` monospace block

### Alert Thresholds (backend_config.yaml)
```yaml
alert_loss_abs: 10000          # ₹ absolute day loss threshold (0 = disabled)
alert_loss_pct: 2.0            # % day loss threshold (0 = disabled)
alert_cooldown_minutes: 30     # min between repeat alerts for same account+type
```

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
- Weekends (Sat/Sun) are treated as closed across all paths: `is_market_open()`, `_task_close()` in api/background.py, and legacy `background_refresh.py`. Special Saturday sessions (Muhurat etc.) need an explicit override
- Holdings always belong to equity segment; positions are filtered by `exchange` column

---

## Background Refresh Thread (`background_refresh.py`)

| Action | Timing |
|---|---|
| Market update cache warm | Immediately at app startup |
| Market update pre-fetch | Once per day at `market_refresh_time` (08:30 IST) |
| Performance data pre-fetch | Every `performance_refresh_interval` (5 min) during market hours |
| Open summary (per segment) | `open_summary_offset_minutes` (15) after segment open, once per day |
| Close summary (per segment) | `close_summary_offset_minutes` (15) after segment close, once per day |
| Loss alert check | Every performance fetch during market hours |

---

## Key Patterns

### Caching
`@st.cache_data` with a time-based `dt` parameter is the cache key. `get_nearest_time()` rounds down to the nearest N-minute interval — call it **once per page render** and reuse the value. Calling it multiple times risks different cache keys at interval boundaries. No `show_spinner` on cache decorators — background thread pre-warms cache before users hit the page.

```python
# Correct
refresh_time = get_nearest_time(interval=config.get('performance_refresh_interval', 5))
df_margins = fetch_margins(refresh_time)
df_holdings, sum_holdings = fetch_holdings(refresh_time, df_margins)
df_positions, sum_positions = fetch_positions(refresh_time)
```

### Multi-Account Broker Calls
`@for_all_accounts` in `decorators.py` wraps broker functions to iterate all accounts. Each call returns a **list of DataFrames** (one per account). Callers use `pd.concat(..., ignore_index=True)` to merge them.

### Account Masking
`mask_column(col)` in `utils.py` replaces all digits with `#` — `ZG0790` → `ZG####`. Applied in `fetch_holdings` and `fetch_positions` cache functions. All alert and summary messages use masked account values.

### Singleton Connections
`Connections` is a thread-safe singleton. Access it as `connections.Connections()` — never instantiate `KiteConnection` directly. The singleton is initialised once at app startup and reused across reruns.

### Session State
Key session state variables:
- `active_nav` — current page
- `signin_completed`, `signout_completed`, `user_validated`, `user_locked`
- `captcha_num1`, `captcha_num2`, `captcha_result` — regenerated each form render
- `form` — tracks which form is active to avoid resetting state across reruns

---

## Things to Avoid

- **Do not call `get_nearest_time()` more than once per page render** — use the returned value throughout
- **Do not touch `ramboq_ssh/`** — it is a frozen reference snapshot of prod server files, not actively maintained. All real work happens in `src/`
- **Do not mock broker API calls in tests** — the `@for_all_accounts` decorator and `Connections` singleton behaviour differs significantly from mocks
- **Do not commit `secrets.yaml`** — it is gitignored; contains API keys, SMTP credentials, cookie secrets, Telegram token. Changes must be applied via SSH `sed` on both server paths (`/opt/ramboq`, `/opt/ramboq_dev`) individually
- **Do not use `st.sidebar`** — sidebar navigation is disabled in `.streamlit/config.toml`; all navigation is via `header.py`
- **Do not add branch filter rules to hooks.json** — branch routing is handled in `dispatch.sh`, not in `hooks.json`; `hooks.json` only validates the event, repo, and HMAC
- **Do not use `2>>&1` in systemd ExecStart** — use `2>&1`; the `>>` append variant causes bash syntax errors in service files
- **Always `chown www-data` after manual server operations** — any file created or modified on the server via SSH (git commands, scp, manual edits) must be owned by `www-data` or deploy scripts will fail silently. After any manual work run: `sudo chown -R www-data:www-data /opt/ramboq/.git /opt/ramboq/.log /opt/ramboq_dev/.git /opt/ramboq_dev/.log`
- **Weekends are hardcoded as closed** in `is_market_open()`, `_task_close()`, and legacy `background_refresh.py` — all alert/summary paths skip Sat/Sun. Special Saturday trading sessions need an explicit override
- **Do not add `show_spinner` to `@st.cache_data` on broker/market fetch functions** — background thread pre-warms cache; spinners would show on first load after restart but are misleading since data is already warm

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
- **`api/app.py`** — Litestar app; startup: init_db + background tasks; serves SvelteKit build
- **`api/database.py`** — PostgreSQL via asyncpg; DB selected by deploy_branch
- **`api/models.py`** — User (32 cols), AlgoOrder, AlgoEvent
- **`api/background.py`** — Four tasks: market, performance, close, expiry check (09:20 IST daily)
- **`api/algo/chase.py`** — Reusable adaptive limit-order chase engine
- **`api/algo/expiry.py`** — Expiry-day auto-close: scan ITM/NTM, chase-close positions
- **`api/routes/algo.py`** — AI Agents API + WebSocket `/ws/algo`
- **`api/routes/auth.py`** — Login (24h JWT), register (pending approval), me, logout
- **`api/routes/admin.py`** — Create/approve/reject/update users, logs, exec

### SvelteKit Pages
- **`+layout.svelte`** — Nav with Admin ▾ dropdown (Terminal, AI Agents, Orders, Users); mobile hamburger
- **`performance/`** — AG Grid with color-coded P&L, per-account grids, URL ?tab= sync
- **`market/`** — AI market report with timestamp
- **`signin/`** — Sign In / Register (name, email, phone)
- **`admin/`** — User management with full partner fields
- **`algo/`** — AI Agents dashboard: status, positions to close, chase orders, live event log
- **`console/`** — Terminal: command textarea + output + live log (equal panels)
- **`orders/`** — Order management

### Deploy automation
`deploy.sh` handles: git pull → pip install → npm build → restart Streamlit + API services → notify

### Logging
- API uses `RAMBOQ_LOG_PREFIX=api_` env var for separate log files from Streamlit
- 3 handlers: rotating log file (5MB × 5), rotating error file, console

---

## Refactoring Notes

| Area | Note |
|---|---|
| `user.py` auth | Backend validation is stubbed — `validate_user()` always returns `(True, "nop")`. Real auth needs implementing before production user login |
| `ramboq_ssh/` | Entire codebase is duplicated here. Can be removed once dev deployment is stable and no longer needed as a reference |
| Regex validators | `validate_email()`, `validate_phone()` etc. in `utils.py` recompile regex on every call. Worth precompiling to module-level constants if form submissions become a bottleneck |
| `components.py` | `render_form()` has 9 nested `with` blocks — hard to follow. Candidate for breaking into smaller functions |
| Parallel broker calls | `fetch_holdings`, `fetch_positions`, `fetch_margins` are parallelised in `performance.py` via `ThreadPoolExecutor` |

---

## Log Files (on server)

Prod and dev logs are fully separated. The webhook listener is a shared service so its logs stay under prod.

**Prod `/opt/ramboq/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy.sh prod` | Prod deploy output (main branch) |
| `hook.log` | `ramboq_hook.service` | All webhook listener output (stdout+stderr combined) |
| `incoming_requests.log` | `log-request.sh` | Raw webhook requests |
| `error_file` | `ramboq.service` tee | All Streamlit stdout+stderr |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines (not written by service) |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

**Dev `/opt/ramboq_dev/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy.sh dev` | Dev deploy output (non-main branches) |
| `error_file` | `ramboq_dev.service` tee | All Streamlit stdout+stderr |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines (not written by service) |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

> Both environments use the same relative `.log/` paths — no per-environment config changes needed. `notify_on_startup` differs per environment (`True` on dev, `False` on prod) and is preserved across deploys.

---

## Common Tasks — Where to Make Changes

| Task | Files to edit |
|---|---|
| Add a new page | Create `src/newpage.py`, add to `page_functions` dict in `app.py`, add nav label to `frontend_config.yaml` |
| Change page content (text, FAQs, etc.) | `setup/yaml/frontend_config.yaml` |
| Change broker data columns shown | `src/constants.py` — update `holdings_config`, `positions_config`, or `margins_config` |
| Change AI market report prompt | `setup/yaml/frontend_config.yaml` — `genai_system_msg`, `genai_user_msg`, `genai_temperature`, `genai_max_tokens`, `genai_model` |
| Change email template | `src/constants.py` — HTML template strings |
| Change connection retry behaviour | `setup/yaml/backend_config.yaml` — `retry_count`, `conn_reset_hours` |
| Change log verbosity | `setup/yaml/backend_config.yaml` — `file_log_level`, `error_log_level`, `console_log_level` |
| Add a new broker account | `setup/yaml/secrets.yaml` — add entry under `kite_accounts` |
| Change deploy branch routing | `webhook/dispatch.sh` — the `if/elif/else`; copy to server after changes: `sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh` |
| Change browser tab title or SEO meta tags | `setup/streamlit/index.html` — update `<title>`, OG/Twitter meta tags |
| Change footer text | `setup/yaml/frontend_config.yaml` — `footer_name`, `footer_text2`, `footer_mobile_text3`, `footer_desktop_text3` |
| Change alert thresholds | `setup/yaml/backend_config.yaml` — `alert_loss_abs`, `alert_loss_pct`, `alert_cooldown_minutes` |
| Change alert recipients | `setup/yaml/secrets.yaml` on server — `alert_emails`, `telegram_chat_id` |
| Enable/disable deploy notification | `setup/yaml/backend_config.yaml` on server — `notify_on_startup` (True=dev, False=prod) |
| Add/change market segment hours | `setup/yaml/backend_config.yaml` — `market_segments` block |
| Change open/close summary timing | `setup/yaml/backend_config.yaml` — `open_summary_offset_minutes`, `close_summary_offset_minutes` |
