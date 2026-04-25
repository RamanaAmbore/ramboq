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

## Broker accounts (DB-backed CRUD)

Operators add / edit / delete broker accounts via `/admin/brokers` instead of editing `secrets.yaml` on the server. Credentials live in the `broker_accounts` table; the three secret columns (`api_secret_enc`, `password_enc`, `totp_token_enc`) are Fernet-encrypted at rest.

**Encryption** ([`backend/shared/helpers/broker_creds.py`](backend/shared/helpers/broker_creds.py))
- Fernet (cryptography stdlib).
- Key derived from existing `secrets.cookie_secret` via HKDF-SHA256 with info tag `b"ramboq-broker-creds-v1"`. No new master secret to provision.
- Rotating `cookie_secret` invalidates the encrypted columns — operator has to decrypt-then-re-encrypt before rotation (we don't auto-do that; rotations are rare + explicit).
- `encrypt(plaintext) -> str`, `decrypt(ciphertext) -> str`, plus `encrypt_dict(payload, fields)` / `decrypt_dict` for the route layer.

**Loading** ([`backend/shared/helpers/connections.py::Connections.rebuild_from_db`](backend/shared/helpers/connections.py))
- `Connections.__init__` still seeds synchronously from `secrets.yaml::kite_accounts` (works during module imports before any DB session exists).
- `_rebuild_broker_connections` runs in `app.on_startup` after `init_db`. It calls `Connections().rebuild_from_db()`:
  1. Query `broker_accounts` (active rows only).
  2. If empty AND `secrets.yaml` has `kite_accounts`: SEED the DB once (encrypts each YAML cred + writes a row) → re-query.
  3. Decrypt secrets in memory, rebuild `self.conn` map.
  4. If both DB and YAML are empty, `self.conn = {}` (the broker registry will then 502 on any market-data call until an account exists).
- Every CRUD mutation on `/api/admin/brokers/*` calls the same rebuild, so credential changes are picked up without a service restart.

**API** ([`backend/api/routes/brokers.py`](backend/api/routes/brokers.py), admin-guarded)

| Route | Purpose |
|---|---|
| `GET /api/admin/brokers` | List metadata for every account (no secrets ever returned). Each row includes a `loaded` boolean — true when the account is in the live `Connections` map. |
| `GET /api/admin/brokers/{account}` | Single-account metadata. |
| `POST /api/admin/brokers` | Create (full body: `account, broker_id, api_key, api_secret, password, totp_token, source_ip?, is_active?, notes?`). |
| `PATCH /api/admin/brokers/{account}` | Partial update. Empty / missing secret fields → "leave unchanged" so a partial form doesn't accidentally clear a TOTP seed the operator didn't intend to rotate. |
| `DELETE /api/admin/brokers/{account}` | Remove the row. |
| `POST /api/admin/brokers/{account}/test` | Reload Connections, then call `broker.profile()` to verify the credential pipeline. Reports the authenticated `user_name` on success or the broker error verbatim on failure. |

**UI** ([`frontend/src/routes/(algo)/admin/brokers/+page.svelte`](frontend/src/routes/(algo)/admin/brokers/+page.svelte))
- Account table — one row per broker account with code / broker / api_key / source_ip / status pill (LOADED / PENDING / DISABLED) / notes / Test button / Edit / Delete.
- Edit + Create form — same fields; Edit form's secret inputs default to blank with a `(blank = unchanged)` hint so the operator can update one credential without re-typing the rest.
- Test button hits `/test`, shows ✓ / ✗ inline next to the row with the broker's response in the tooltip.
- Polling: every 15 s so the LOADED status pill catches up after a save without a manual refresh.

**Migration path from secrets.yaml** — first deploy of this feature, the table is empty, the YAML has accounts, and the seed-from-YAML happens automatically on startup. The YAML rows stay (recovery backup). Subsequent edits go through the UI; the YAML diverges from the DB but is never overwritten (so there's a path back if the DB row gets corrupted: just clear the table and restart, the seeder runs again).

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
- **`+layout.svelte`** — algo-site top nav: Dashboard · Agents · Orders · Terminal · Simulator · Paper · Options · Tokens · Settings · Brokers · Users; polls `/api/simulator/status` and renders the sticky red **SIMULATOR ACTIVE** banner on every algo page while a sim is running.
- **`performance/`** (public) and **`dashboard/`** (admin, same `PerformancePage.svelte` component). The public page uses the default two-row header (timestamp + Refresh on top, tabs + account picker below). The admin dashboard passes `compactHeader={true}` to collapse into one toolbar row: `[Positions | Holdings] [Account ▼] [Refresh]`. Either way, selecting a specific account scopes **every** grid (Holdings summary + detail, Positions summary + detail, Funds) to that account — sibling accounts AND the TOTAL aggregate are filtered out, and the Account column hides across those grids since it would render identical values. Performance **always** shows real Kite data; the background refresh keeps going even while the simulator is active. The algo theme (`ag-theme-algo`) is the dark navy-gradient variant; long positions render a cyan row tint with a left accent border, short positions a warm-orange row tint.
- **`market/`** — AI market report with timestamp
- **`signin/`** — Sign In / Register (name, email, phone)
- **`admin/`** — User management with full partner fields
- **`admin/tokens/`** — Agent Tokens page (Condition / Notify / Action tabs), create/edit custom tokens, Reload Registry. UI label is "Tokens"; the DB table and Python class keep their legacy names (`grammar_tokens`, `GrammarRegistry`) because the data model IS a grammar in the compiler-theory sense. Route: `/admin/tokens`.
- **`admin/simulator/`** — Market simulator control plane. Scenario dropdown · Seed (Scripted / Live / Live+scenario) · Rate · Load live book · Start / Stop / Step / Run cycle / Clear sim. Shared `LogPanel` embedded at the bottom, defaulted to the Simulator tab (streams per-symbol LTP diffs in real time). See **Simulator** section below.
- **`agents/`** (formerly `/algo`) — Agents page: grouped compact rows (Loss & Risk / Summaries / Automation / Other), click-to-expand, Edit with live condition validation, per-row "Run in Simulator" button that deep-links to `/admin/simulator?agent_id=<id>`. The Agent-events panel auto-scopes: real events when sim is idle, sim events when a sim is running.
- **`console/`** — Terminal: command textarea + output + live log (equal panels)
- **`orders/`** — Order management

---

## Execution modes (mode 1 / 2 / 3)

The codebase distinguishes three orthogonal modes for an agent fire, and they're split between dev and prod:

| Mode | Quote source | Trade engine | Where it runs | Default |
|---|---|---|---|---|
| **1 — Simulator** | `SimQuoteSource` (fabricated, scenario-driven via [`SimDriver`](backend/api/algo/sim/driver.py)) | `PaperTradeEngine` fed by sim quotes — fills against fabricated bid/ask, removes positions on fill | Dev only (capped off in prod via `cap_in_prod.simulator: False`) | `cap_in_dev.simulator: True` |
| **2 — Real-data + paper** | `LiveQuoteSource` (broker.quote / broker.ltp via the `Broker` adapter, with bid/ask from depth or `simulator.default_spread_pct`) | `PaperTradeEngine` singleton (`get_prod_paper_engine()`), 5-second background tick. Validates each new order via Kite's `basket_margin` before marking OPEN; REJECTED rows carry Kite's exact error in `.detail`. Real positions are NOT updated; cooldown handles re-fire | Prod only (dev never runs the live agent engine) | All `execution.live.<action>` flags `False` ⇒ every broker-hitting action lands as paper |
| **3 — Real-data + real (live)** | `LiveQuoteSource` (read paths) | Real broker via [`chase.py`](backend/api/algo/chase.py) — actual Kite `place_order` / `modify_order` / `cancel_order` | Prod only, per-action toggle | Promoted by flipping `execution.live.<action>` to `True` in `/admin/settings` |

**The branch is the hard outer gate.** [`utils.is_prod_branch()`](backend/shared/helpers/utils.py) returns `True` only on `main`. On any other branch, every broker-hitting action is forced to paper regardless of the DB flags. On `main`, the per-action flag decides between paper and live for that specific action.

**Architectural pieces** (after the modes refactor):

- [`backend/api/algo/quote/`](backend/api/algo/quote/) — `QuoteSource` ABC + `SimQuoteSource` + `LiveQuoteSource`. Bid/ask supplier per open order. `on_fill` hook lets the source update its book on fill (sim drops the symbol; live is a no-op).
- [`backend/api/algo/paper.py`](backend/api/algo/paper.py) — `PaperTradeEngine` owns the open-order book and the chase / fill / modify / unfilled lifecycle. Constructor takes a `QuoteSource`, a `label` ("sim" / "paper"), and an optional event callback. Used by both `SimDriver` (mode 1, fed by `SimQuoteSource`) and `get_prod_paper_engine()` (mode 2, fed by `LiveQuoteSource`).
- [`actions.py::_resolve_mode`](backend/api/algo/actions.py) — single source of truth for "should this action go to sim, paper, or live?". Reads `context["sim_mode"]`, the branch, and the per-action `execution.live.<action>` flag.
- [`agent_engine._agent_execution_mode_tag`](backend/api/algo/agent_engine.py) — inspects the firing agent's actions and tags the alert as `[PAPER]` (all broker actions paper), `[MIXED]` (split), or empty (all live). The tag flows through `alert_utils._dispatch` into Telegram subjects + email subject prefixes so an operator on Telegram can tell at a glance what an alert caused.

**Per-action flags** (DB seeds, all default `False`):

| Setting | Action |
|---|---|
| `execution.live.cancel_order` | Most reversible — typically promoted first |
| `execution.live.cancel_all_orders` | |
| `execution.live.modify_order` | |
| `execution.live.place_order` | New-order placement — typically promoted last |
| `execution.live.close_position` | |
| `execution.live.chase_close_positions` | |

`/admin/settings` renders these in their own "execution" section and shows a top-of-page banner: green when all are `False` ("every broker action is in PAPER mode"), red when any is `True` ("⚠ N of 6 actions are LIVE").

**Order-log mode pills**: every `AlgoOrder` row carries `mode ∈ {sim, paper, live}`. The LogPanel Order tab shows three distinct pills:
- `SIM` — amber, fabricated data
- `PAPER` — sky-blue, real data + paper trade
- `LIVE` — emerald, real broker order

`/api/orders/algo/recent?mode=paper` filters the API to just paper rows; the UI surfaces it via the mode column on each row.

**What this means for the operator on prod**: every broker-hitting agent fire writes a paper `AlgoOrder` row with Kite's `basket_margin` verdict in `.detail`. REJECTED rows tell you "Kite would have kicked this back anyway"; OPEN rows transition to FILLED / UNFILLED via the chase loop. Real positions stay unchanged until you flip a flag to live.

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

## Settings — DB-backed tunables

`/admin/settings` exposes every parameter that changes more often than a deploy cycle. Values live in the `settings` table (`category / key / value_type / value / default_value / description / schema / units`). The reader chain is **DB cache → YAML fallback → in-code default**, so migrating a knob from YAML to DB is a one-line code change and zero-downtime.

Key files:

| Path | Purpose |
|---|---|
| `backend/api/models.py::Setting` | SQLAlchemy row |
| `backend/shared/helpers/settings.py` | `SEEDS` list + `get_int/get_float/get_bool/get_string` readers + `seed_settings()` seeder |
| `backend/api/routes/settings.py` | `/api/admin/settings/*` CRUD |
| `frontend/src/routes/(algo)/admin/settings/+page.svelte` | Grouped page (Alerts · Performance · Simulator · Notifications · Logging) |

Seeded buckets + sample keys:

- **alerts** — `alerts.cooldown_minutes`, `alerts.rate_window_min`, `alerts.baseline_offset_min`, `alerts.suppress_delta_abs`, `alerts.suppress_delta_pct`
- **performance** — `performance.refresh_interval`, `performance.open_summary_offset_min`, `performance.close_summary_offset_min`
- **simulator** — `simulator.positions_every_n_ticks`, `simulator.auto_stop_minutes`, `simulator.default_rate_ms`
- **notifications** — `notifications.telegram_enabled`, `notifications.email_enabled`, `notifications.notify_on_deploy`
- **logging** — `logging.file_log_level`, `logging.console_log_level`, `logging.error_log_level`

Seeder behaviour across deploys:
- Insert missing rows (from `SEEDS`) with the shipped `default_value`.
- Refresh `category / description / schema / units / default_value / value_type` on existing rows (code changes land through).
- **Preserve `value`** (the operator's live override).
- **Auto-prune** rows whose keys are no longer in `SEEDS` — retiring a knob requires no manual DB cleanup.

Per-PATCH, the in-process cache invalidates and reloads, so edits take effect on the next agent tick / sim run without a service restart.

---

## Simulator

The simulator feeds fabricated per-symbol **positions** + margins into
the **same** agent engine the real pipeline uses, so alerts, actions, and
event-logging are all exercised end-to-end without touching the broker.
**No code branches in the hot path** — the engine only sees a `sim_mode`
flag on the context dict and tags downstream artefacts: `[SIM]` for log
lines and detail strings, `SIMULATOR` for user-facing Telegram / email
surfaces.

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

### Run-in-Simulator + the synthesizer

Per-agent tests don't touch `scenarios.yaml` — they're built on demand from the agent's own condition tree by [`backend/api/algo/sim/synthesize.py`](backend/api/algo/sim/synthesize.py). The button on each `/agents` row hits `POST /api/simulator/start-for-agent/<id>`; the handler calls `synthesize_for_agent(agent)` which:

1. Walks the agent's condition tree, picks the "nearest-to-fire" leaf (`all` → tightest threshold; `any` → loosest; `not` logs a warning and targets the inner leaf).
2. Maps the leaf's metric to a canned ticks-shape:
   | metric | technique |
   |---|---|
   | `pnl` | `target_pnl` on positions scoped to match |
   | `pnl_pct` | `target_pnl` sized to cross `value% × util_margin` |
   | `pnl_rate_abs` | scheduled `target_pnl` decay over the rate window |
   | `pnl_rate_pct` | same, scaled to `value% × util_margin` |
   | `cash` | `set_margin` driving `avail opening_balance < 0` |
   | `avail_margin` | `set_margin` driving `net < 0` |
3. Holdings metrics (`day_pct`, `day_rate_abs`, `day_rate_pct`) are NOT synthesizable — the handler returns 400 with a message pointing operators at live data validation instead.
4. Returns an inline scenario dict (same shape as yaml entries). `SimDriver.start(inline_scenario=…)` accepts it without touching the yaml catalog.

Result: adding a new agent adds its own test for free. Adding a new metric is one grammar token + one synthesizer entry.

### Market-state presets

Agents that reference time (rate metrics with baseline gates, `minutes_until_close`, expiry rules) need a simulated clock — wall-clock time at 3 AM IST has every segment closed. Each scenario + each Start request can declare a `market_state` block:

```yaml
market_state: {preset: pre_close}
# — or —
market_state: {preset: expiry_day, is_expiry_day: true}
# — or explicit overrides —
market_state:
  nse_open: true
  mcx_open: false
  minutes_since_nse_open: 360
```

Seven presets shipped (see `MARKET_STATE_PRESETS` in `sim/driver.py`): `pre_open` / `at_open` / `mid_session` (default) / `pre_close` / `at_close` / `post_close` / `expiry_day`. `run_cycle` calls `_build_context(now, sim_overrides=…)` which merges overrides on top of the computed live values. Real path passes `None` and behaviour is unchanged.

### Paper-trade action expansion

When an agent fires in sim mode, `actions.execute()` routes to `_sim_paper_trade`. The writer now branches:

- **`close_position` / `place_order`** — params already specify `account + symbol`. Write ONE `AlgoOrder` with `initial_price = sim bid/ask (side-aware) for that symbol`.
- **`chase_close_positions` / `chase_close`** — scope-level actions. Look up every open position matching `scope ∈ {total, account}` in `SimDriver._positions_rows`, write ONE `AlgoOrder` per position, each with the real `account / symbol / qty` and side-appropriate price (SELL→bid, BUY→ask).
- **Non-order actions** (`emit_log`, `set_flag`, `monitor_order`, `deactivate_agent`, `cancel_*`, `send_summary`) don't get a paper row — just the `action_success` agent event that `execute()` already writes.

Each paper row carries the same print-style `detail` string in all three surfaces (logger, `AlgoOrder.detail`, tick_log `note`):

```
[SIM] loss-pos-total-auto-close → close_position: SELL 50 NIFTY25APRPE22000 @₹180.00 · acct=ZG####
```

### Chase engine (spread-aware)

Every position derives `bid` / `ask` from the simulator's `spread_pct` (default 0.10 %, tunable per Start). When an agent fires, the paper-trade writer persists the `AlgoOrder` with `status='OPEN'` and registers it with the driver's chase engine. Each subsequent tick, `_chase_open_orders`:

- **Fills** the order when the bid/ask crosses the limit (SELL fills if `bid ≥ limit`; BUY fills if `ask ≤ limit`). The position is removed from `_positions_rows`, the `AlgoOrder` row flips to `FILLED` with `fill_price` + `slippage` + `filled_at`, and the detail string is rewritten as `FILLED @₹X after N chase(s)`.
- **Modifies** the limit otherwise — re-quotes at the current opposite side, bumps `attempts` on the DB row, rewrites `detail` to `chase #N limit=₹X`. Capped at `simulator.chase_max_attempts` (default 5); after the cap the row flips to `UNFILLED`.
- **Auto-completes** the sim when `_positions_rows` is empty and no orders remain `OPEN`. A terminal `completed` entry lands in the tick log.

The status snapshot carries `positions` (per-row `{account, symbol, quantity, last_price, bid, ask, pnl}`) and `open_order_details` (per in-flight chase — `{symbol, side, qty, limit_price, attempts, status}`). The simulator page renders both as compact pill strips so operators watch the book shrink and the chase re-quote live.

### Order lifecycle status

`AlgoOrder.status` progression in sim mode: `OPEN` → (per tick) `OPEN` with `attempts++` → `FILLED` (or `UNFILLED` after cap). `AlgoOrderInfo` now exposes `attempts` + `fill_price`; the LogPanel Order tab colours each row by terminal state (FILLED green / UNFILLED red / OPEN amber) and adds a `chase: #N` chip.

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
| Log prefix | `[SIM]` (short form — Telegram/email surfaces keep the longer `SIMULATOR` form) |
| WebSocket `agent_alert` payload | `sim_mode: true` |

### Simulator API — `/api/simulator/*`

| Route | Purpose |
|---|---|
| `GET /scenarios` | List available scenarios (slug / name / mode / has_initial / tick count) |
| `GET /status` | Driver snapshot (active, scenario, seed_mode, tick_index, counts, only_agent_ids, `positions`, `open_order_details`, `spread_pct`, `enabled`, `branch`) |
| `POST /start` | Body: `{scenario, rate_ms, seed_mode, agent_ids?, positions_every_n_ticks?, market_state_preset?, pct_overrides?, symbols?, spread_pct?}` |
| `POST /start-for-agent/{id}` | Build a scenario from one agent's condition tree and start (no `scenarios.yaml` entry required) |
| `POST /stop` | Halt |
| `POST /step` | Apply one tick (deterministic debug) |
| `POST /seed-live` | Snapshot live positions + margins into `_live_snapshot` (holdings skipped — positions-only sim) |
| `POST /run-cycle` | Immediately run the agent engine against current sim state |
| `POST /clear` | Delete every sim-mode row from `agent_events` + `algo_orders` |
| `GET /events/recent?limit=N` | Recent `sim_mode=True` agent events |
| `GET /orders/recent?limit=N` | Recent `mode='sim'` algo orders |
| `GET /ticks/recent?limit=N` | Rolling driver tick log (oldest-first) with per-symbol diffs |

Gated by `admin_guard` + the per-branch `cap_in_<branch>.simulator` flag in `backend_config.yaml` (dev default: on, prod default: off). `GET /status` returns `enabled: false` when the cap is off for the active branch — the `/admin/simulator` page reads this and disables every form button with a banner explaining which branch is gated, so operators don't have to press Start to discover the gate.

### Running the simulator

- **Default path**: pick a scripted scenario (e.g. `crash-open`) → Start.
- **Stress-test your real book**: press **Load live book** → switch Seed to **Live + scenario** → pick `generic-crash` or `random-walk` → Start.
- **Dry-fire one agent**: on `/agents`, click **Run in Simulator** on a row → arrives at `/admin/simulator?agent_id=<id>` with the agent armed → pick a scenario → Start. The agent fires regardless of its `status`, `schedule`, cooldown, or baseline gate; no real agent state is mutated.

Auto-stops after 30 minutes so a forgotten sim can't bleed forever.

---

## Price-history charts (`/api/charts/*`)

In-memory rolling per-symbol price buffers + lifecycle markers from
`AlgoOrder` rows give the operator a chart of "what the price did and
where the chase fired" without any new persistent state.

**Capture points** (zero new schema, deque self-trims):

- [`SimDriver._price_history`](backend/api/algo/sim/driver.py): `dict[symbol, deque(maxlen=600)]`. `_capture_price_history()` runs at the end of every `_apply_next_tick`, snapshotting `(ts, ltp, bid, ask)` per row in `_positions_rows`. Wiped on every `start()`.
- [`PaperTradeEngine._price_history`](backend/api/algo/paper.py): same shape, populated in `step()` after `prefetch_for(open_now)` so the snapshot reflects the same quote the chase loop evaluated against. Wiped on `reset()`.
- Live mode currently shares the prod paper engine — both feed off `LiveQuoteSource`. A dedicated live engine can plug in here later if real-broker mode grows its own state.

**API** ([`backend/api/routes/charts.py`](backend/api/routes/charts.py), admin-guarded):

| Route | Purpose |
|---|---|
| `GET /api/charts/symbols?mode=sim\|paper\|live` | Symbols with at least one captured tick. Used by the chart panel's symbol picker / grid. |
| `GET /api/charts/price-history?mode=…&symbol=…&since=…&limit=600` | `{ticks: [...], events: [...]}` — ticks from the in-memory buffer, events derived from `algo_orders` rows for the same symbol+mode (placed at `created_at`/`initial_price`, terminal at `filled_at`/`fill_price` or fallback). |

**UI**:

- [`PriceChart.svelte`](frontend/src/lib/PriceChart.svelte) — hand-rolled SVG line + bid/ask shaded band + lifecycle markers (placed=amber / filled=emerald / unfilled=red). Polls `/api/charts/price-history` every 3 s. No chart library — keeps the bundle thin.
- [`/admin/simulator`](frontend/src/routes/(algo)/admin/simulator/+page.svelte) embeds one mini chart per symbol returned by `GET /charts/symbols?mode=sim` directly under the position pills, so the operator sees the trajectory + chase markers live.
- [`LogPanel`](frontend/src/lib/LogPanel.svelte) gained a **Chart** tab. Consumers pass `chartMode` (`sim` while a sim runs, otherwise `paper`) + `chartSymbols`. The `/agents` page wires both — its Chart tab tracks whichever surface is active.

**Cleanup**: deque `maxlen=600` is the only retention mechanism — at the default tick rates (2 s sim / 5 s paper) that's ~20 min of history per symbol. Restart loses the history; operator monitoring the chase live doesn't need cross-restart continuity. If post-mortem replay becomes valuable, swap to a `price_ticks` table here.

---

## Derivatives — underlying-driven re-pricing

Options + futures re-price coherently off underlying spot moves so a single "−3% NIFTY" tick cascades through every NIFTY contract instead of each strike moving in isolation.

**Module** ([`backend/api/algo/derivatives.py`](backend/api/algo/derivatives.py)) — pure-Python, no scipy:

- **Symbol parser** — `parse_tradingsymbol(sym)` returns `{kind: 'opt'|'fut', underlying, strike, opt_type, expiry}` for Kite F&O symbols. Handles monthly (`NIFTY25APR22000CE`) and weekly (`NIFTY2542422000CE`) options, monthly futures (`NIFTY25APRFUT`), stock options (`RELIANCE25APR2800CE`). Returns `None` for cash-equity tradingsymbols.
- **Black-Scholes** — `black_scholes(S, K, T_years, r, sigma, opt_type)` for vanilla European options. q=0 (Indian index options pay no carry). Vega/theta deliberately ignored — sim runs are minutes, not days.
- **IV calibrator** — `implied_vol(price, S, K, T, r, opt_type)` is a bisection solver over [0.0001, 5.0]. Falls back to `DEFAULT_IV = 0.15` when the bracket can't bracket. Locked once at sim seed; subsequent ticks re-price with that cached σ.
- **Re-pricer** — `reprice_row(row, *, spot, sigma)` returns the new last_price for a given derivative position. Futures track spot 1:1; options use BS with the cached σ.
- **Underlying-key resolver** — `underlying_ltp_key(name)` maps underlying names to Kite quote keys (`NIFTY` → `NSE:NIFTY 50`, `BANKNIFTY` → `NSE:NIFTY BANK`, stock fallthrough to `NSE:<NAME>`).

**Sim wiring** ([`backend/api/algo/sim/driver.py`](backend/api/algo/sim/driver.py)):

- `_underlyings: dict[str, float]` — name → current spot. Resolved at seed time via (1) `scenario.initial.underlyings` explicit override → (2) the futures position's last_price → (3) median strike across the option book as a crude ATM proxy.
- `_iv_cache: dict[str, float]` — per-option σ calibrated against the seed's last_price.
- `_underlying_history: dict[str, deque]` — parallel rolling buffer for spot ticks; surfaced via the same `/api/charts` endpoints as contract ticks.
- New move primitives in `_apply_moves` — scope `underlying.<NAME>` or `underlying.*`:
  - `underlying_pct {value: -0.03}` → spot × (1 + value)
  - `underlying_abs {value: -25}` → spot + value
  - `underlying_target {value: 22000}` → spot ← value
  After the move, every position whose underlying matches re-prices via `_reprice_derivatives_for`. Each derivative gets its own change row in the tick log so the LogPanel's Simulator tab shows the chain (spot move + N option re-prices).

**Paper/live wiring** ([`backend/api/algo/paper.py`](backend/api/algo/paper.py)) — `PaperTradeEngine._capture_price_history` parses each open order's symbol via `parse_tradingsymbol`, dedupes underlyings, then calls `broker.ltp([keys])` once with the resolved Kite keys. Underlying spots land in `_underlying_history` alongside the contract ticks. No new schema; same deque cap.

**Chart UI** ([`PriceChart.svelte`](frontend/src/lib/PriceChart.svelte)):

- `/api/charts/symbols` returns each symbol's `kind` (`underlying` / `derivative` / `other`) and `underlying` (name when kind=derivative). Sorted with underlyings first, derivatives grouped by underlying.
- Chart header shows a kind tag (sky-blue `SPOT` for underlyings, amber `F&O` for derivatives) next to the mode pill.
- For derivative charts the component fetches the underlying's history too and overlays it as a sky-blue dashed line, normalized into the option's plot area so a 22,000 NIFTY move doesn't squash the 180-rupee call line.
- A `chart-legend` chip identifies the dashed underlying line so the operator never confuses the two.

**Built-in scenarios** — [`scenarios.yaml`](backend/api/algo/sim/scenarios.yaml) ships `nifty-down-3pct` and `nifty-up-3pct` (each: three `underlying_pct` ticks of ±1% on `underlying.NIFTY`). Pair with `seed_mode: live` / `live+scenario` so the BS re-pricing runs against real strikes + premiums.

**Custom-positions seeding** — the `/admin/simulator` page exposes a "Custom positions" panel (account / symbol / qty / LTP rows) that the operator fills inline. `POST /api/simulator/start` accepts `custom_positions: list[dict]`; the driver appends them to whatever scripted/live seed produced via [`_normalise_custom_positions`](backend/api/algo/sim/driver.py) (uppercases the symbol, infers exchange `NFO` for parseable F&O / `NSE` otherwise, defaults `average_price = last_price`). Custom rows are layered BEFORE `_seed_derivatives` runs, so synthetic NIFTY/BANKNIFTY/etc. options pick up underlying spots + IV calibration the same way real positions do.

**Performance — per-underlying index + cached parse**: `_seed_derivatives` walks positions once, stashes the parser result on each row as `row["_parsed"]`, and builds [`_positions_by_underlying: dict[str, list[dict]]`](backend/api/algo/sim/driver.py). All downstream consumers (`_reprice_derivatives_for`, IV calibration, futures-as-spot proxy) read from these cached structures — `_apply_underlying_move("underlying.NIFTY", …)` is now O(matched-rows) instead of O(positions). Hot-path regex calls dropped from 3-per-row-per-tick to 1-per-row-per-seed.

---

## Paper-trading dashboard (`/admin/paper`)

Visual surface for the prod paper-trade engine, pairing with the simulator page so operators can monitor mode 2 the same way they monitor sims.

**Page**: [`frontend/src/routes/(algo)/admin/paper/+page.svelte`](frontend/src/routes/(algo)/admin/paper/+page.svelte). Polls `/api/charts/paper-status` every 3 s. Layout:

- Status banner — green/sky `CHASING` (orders in flight on main), amber `IDLE` (engine enabled, no orders), grey `DEV` (engine gated on this branch).
- Open-order pills — same shape as the sim page's chase pills (side / qty / symbol / current limit / attempt count).
- Chart grid — one mini chart per symbol with captured ticks; underlyings rendered first (sky-blue `SPOT` tag), derivatives grouped by underlying with the spot overlaid as a dashed line.
- Embedded LogPanel with `chartMode='paper'` so the Chart tab inside the panel mirrors the page's main chart grid.

**API**: [`/api/charts/paper-status`](backend/api/routes/charts.py) — admin-guarded. Returns `{enabled, branch, open_order_count, open_order_details, captured_symbols, captured_underlyings}`. `enabled = (deploy_branch == 'main')` — the engine still exists on dev branches but no `tick_loop` is running, so no orders register and the page banner explains the gate.

---

## Options analytics (`/admin/options`)

Distinct workspace from the tick-chart pages — this is options *research*, not live monitoring. For any single-leg option (live position / sim position / hypothetical typed-in symbol), it computes Greeks, payoff curve, theoretical-vs-market discrepancy, max-profit / max-loss / breakeven / probability-of-profit, plus a 30-day historical price chart.

**σ-driven payoff range**

The chart x-axis used to be a fixed ±10% around spot, which wasted space on short-DTE options (a 7-DTE option might cover 1σ at expiry in just ±5%) and squashed long-DTE ones (60-DTE, 25% IV easily wants ±25%). Both endpoints now auto-derive the range from the underlying's standard deviation at expiry:

```
span_pct = span_sigmas × σ × √T_years        (default span_sigmas = 2.5)
```

`σ` is the calibrated IV for single-leg, the qty-weighted IV proxy for strategy. Clamped to `[2 %, 50 %]`. Operator can override by passing an explicit `span_pct` in the query (single-leg) or request body (strategy).

The response now includes `span_pct` (decimal fraction actually applied) and `span_sigmas` (the σ-multiple it was derived from — 0 when the operator overrode `span_pct`). UI footnote reads "±2.5σ (7.3%)" when auto-derived, "±10.0%" when overridden.

**Math** ([`backend/api/algo/derivatives.py`](backend/api/algo/derivatives.py)):

- `greeks(S, K, T_years, r, sigma, opt_type)` — analytical Δ Γ Θ V ρ. Theta is per-day, Vega is per 1 % IV, Rho is per 1 % rate (trader-friendly units, not raw mathematical units).
- `prob_above(S, K, T, r, sigma)` — P(S_T ≥ K) under the Black-Scholes log-normal assumption. Used as the building block for POP.
- `risk_metrics(S, K, T, r, sigma, opt_type, qty, entry_price)` — single-leg max profit / max loss / breakeven / POP. Returns `inf` for unlimited-payoff legs (long calls, short puts); the API serializes those as `null` so the UI renders "∞".
- `payoff_curve(S, K, T, r, sigma, opt_type, qty, entry_price, span_pct, points)` — list of `{spot, today_value, expiry_value}` spanning ±`span_pct` around current spot. Both values are **position P&L** (signed qty, net of entry cost) so they read as money the operator would make/lose.

**LTP fallback chain (graceful degradation)**

Both endpoints now use `broker.quote()` (richer than `ltp()` — has `ohlc.close` + depth) and degrade through this chain rather than 502'ing on any failure:

1. **override** — operator-supplied `ltp` query param / leg field
2. **sim** — `_positions_rows` row's `last_price` when sim is active
3. **live** — broker's `last_price`
4. **close** — previous-day `ohlc.close` (off-hours, weekend, illiquid)
5. **depth** — midpoint of top-of-book bid/ask
6. **avg_cost** — operator's recorded entry price
7. **estimated** — Black-Scholes at `DEFAULT_IV` against the resolved spot

Spot fallback chain mirrors this: override → sim → broker quote → `fallback` (the option's strike used as a synthetic spot — payoff shape is preserved, absolute P&L is not). The endpoint never returns 502 when the operator passed an option that's parseable; it always produces a payoff curve and surfaces source provenance for the UI to render appropriate stale chips.

`ltp <= 0` is treated identically to `ltp = None` (sim pickers that copied a stale `last_price=0` would otherwise bypass the broker fetch and fail straight to `avg_cost`).

**Endpoints** ([`backend/api/routes/options.py`](backend/api/routes/options.py), admin-guarded):

| Route | Purpose |
|---|---|
| `GET /api/options/analytics?mode=live\|sim\|hypothetical&symbol=…&[account, qty, avg_cost, spot, ltp, iv, span_pct, points]` | Single-leg bundle — Greeks (per-share + position-scaled), pricing block, risk, payoff curve. One round-trip. Hypothetical mode lets the operator dry-analyse a strike before taking the trade. |
| `GET /api/options/historical?symbol=…&days=30&interval=day&exchange=NFO` | Kite OHLCV bars. Instrument-token lookup goes through the cached instruments dump. |
| `POST /api/options/strategy-analytics` (body `{legs: [{symbol, qty, avg_cost?, ltp?, iv?}], spot?, span_pct?, points?}`) | Multi-leg aggregate analytics — vertical spreads, iron condors, butterflies, strangles. Each leg's `ltp` is optional: when present (e.g. legs sourced from the simulator) it's used directly; when absent, the broker is hit once for the whole batch. v1 enforces same-underlying + same-expiry across legs (calendar / diagonal spreads not yet supported). |

**Expected value + risk:reward**

Both endpoints surface position-level expected value and R:R alongside the existing POP / max-profit / max-loss block:

- `expected_value(curve, S, T_years, sigma)` — trapezoidal integration of `expiry_value` against the risk-neutral lognormal pdf of the underlying:

  ```
  f(S_T) = (1 / (S_T σ √(2πT))) · exp(-(ln(S_T/S) − (r − σ²/2)T)² / (2σ²T))
  ```

  The curve typically spans ±2.5σ which captures ~99 % of the lognormal mass, so truncation error is sub-percent. The signed-qty payoff is already baked into the curve, so this is just one trapezoidal pass per request.

- `risk_reward_ratio(max_profit, max_loss)` = `max_profit / |max_loss|`. Returns `None` for unbounded legs (long calls, short puts) where the ratio isn't meaningful — UI renders "—".

**Response surface** — `OptionRisk` and `StrategyRisk` gain `ev` (₹), `ev_pct` (return-on-cost %, null when entry cost is 0), `rr_ratio` (null when unbounded). UI risk panel renders them as additional `kv-` rows alongside POP / breakeven / max-profit / max-loss.

**Why this matters operationally** — POP alone is misleading. A 95 %-POP credit spread that risks ₹50k to make ₹500 has positive expectancy but a single loss takes 100 winners to recover; EV captures the magnitude side and tells you whether the trade is actually worth taking. R:R does the same for the asymmetric clip-size aspect.

**Option-chain picker** — `/admin/options` Strategy mode now has a third leg-input alongside "Add from book" and "+ Add row": an option-chain table that lets the operator browse strikes for any underlying / expiry and click `+ CE` / `+ PE` to drop a leg. Sourced from the existing instruments cache ([`frontend/src/lib/data/instruments.js`](frontend/src/lib/data/instruments.js); IndexedDB-backed, ~90k contracts) so no new API. Default qty = `lot_size` for the contract, side toggle (Long / Short) flips the sign. Particularly useful for spreads and strangles where the operator doesn't have any of the legs in their book yet.

**Multi-leg math** ([`backend/api/algo/derivatives.py`](backend/api/algo/derivatives.py)):

- `multileg_payoff_curve(legs, S, ...)` — sums per-leg `today_value` + `expiry_value` at each spot. Each leg keeps its own (T_years, σ).
- `multileg_greeks(legs, S, ...)` — sums signed-qty per-leg Greeks (Greeks are linear in qty).
- `find_breakevens(curve)` — linear-interpolated zero-crossings on the expiry curve. Iron-condor-shaped strategies report 2 BEs; verticals 1; fully ITM/OTM 0.
- `multileg_pop(curve, S, T, σ_proxy)` — walks the expiry curve, identifies contiguous profit segments, integrates the lognormal `prob_above` over each. Open-ended endpoints (curve runs off-screen still in the money) use the analytical limits so we don't artificially clip POP. `σ_proxy` is the qty-weighted IV across legs — defensible single number from the data we have.
- `multileg_extremes(curve)` — numerical max profit / max loss from the expiry curve. As wide as the spot range; unlimited-payoff legs (long calls, short puts) need the operator to widen `span_pct` if the realistic upside isn't covered.

**Pricing-account setting** — `connections.price_account` (string, default blank) lets the operator pin which Kite account to use for shared market-data fetches (underlying spots in `PaperTradeEngine._capture_underlyings`, instrument lookup + LTP + historical for `/admin/options`). Implemented in [`backend/shared/brokers/registry.py::get_price_broker()`](backend/shared/brokers/registry.py); falls back to the first available account when the setting is blank.

**UI** — [`frontend/src/lib/OptionsPayoff.svelte`](frontend/src/lib/OptionsPayoff.svelte) is the payoff-chart SVG. Two curves (today amber solid, expiry sky dashed), profit/loss zone shading, vertical markers for spot (cyan) / strike (white dashed) / breakeven (amber dashed), hover crosshair with a 3-line tooltip. Hand-rolled SVG, no chart lib.

[`frontend/src/routes/(algo)/admin/options/+page.svelte`](frontend/src/routes/(algo)/admin/options/+page.svelte) wires four input modes: live position / sim position / hypothetical (single-leg) / **strategy** (multi-leg). Single-leg modes render the payoff chart on the left + Pricing / Greeks / Risk blocks on the right + historical chart full-width below. Strategy mode shows a leg-builder table (Add leg from book auto-fills LTP+cost from a live or sim position; + Add row gives a blank line for hypothetical legs), then aggregates into the same payoff chart (with multiple breakeven markers + every leg's strike marked) plus an Aggregate / Greeks / Risk side panel and a per-leg breakdown table beneath.

`OptionsPayoff` accepts either scalar `strike` / `breakeven` props (single-leg) or arrays `strikes` / `breakevens` (multi-leg) — same SVG, same palette.

Polling: analytics every 5 s while a symbol is set; historical only on symbol change (daily candles don't move intra-day). Strategy mode polls the same cadence so Greeks + IV stay live while the operator stares at the page.

---

## Charts batch endpoint + per-chart polling

The chart panel's per-symbol polling could blow up to N+M requests every 3 s (N = visible charts, M = underlying overlays). [`GET /api/charts/batch?mode=…&symbols=a,b,c`](backend/api/routes/charts.py) coalesces it to one round-trip.

- One `IN`-clause `algo_orders` query for the whole batch (cap 50 symbols), grouped client-side by symbol.
- Returns `{mode, charts: [ChartResponse, …]}` in the order of the input symbols.
- Symbols with no captured ticks come back with empty `ticks` / `events` so clients don't have to special-case absent entries.

**Frontend distribution**: [`PriceChart.svelte`](frontend/src/lib/PriceChart.svelte) gained a `data` prop. When the parent feeds it (and `chartsBySymbol` for underlying-overlay lookup), the chart skips its own poll timer (`stopPolling()` in a `$effect` triggered when `externalData` flips on). The simulator, paper, and agents pages all poll once and distribute via `chartsBySymbol`.

Effect: a page with 10 charts goes from ~200 req/min to ~20 req/min, no behaviour change for charts shown without a parent (Chart tab on /orders, /console where it falls back to per-chart polling).

---

## Chart grid lines

Both SVG chart components draw a faint cool-blue grid (`rgba(200,216,240,0.10)` for major lines, `0.07` for vertical x-axis lines) at 5 evenly-spaced y-positions and 4-5 x-positions across the visible domain. PriceChart x-grid lines carry HH:MM:SS labels along the bottom axis so the operator can correlate price moves with wall-clock seconds without dragging the hover crosshair. OptionsPayoff x-grid is unlabeled (the strike + breakeven + spot markers already carry the meaningful x-coordinates).

The grid colors are deliberately low-saturation cool-blue rather than amber — this keeps the chart's amber LTP / payoff lines visually dominant. Solid amber strokes against a faint blue grid is a much more legible combination than amber on amber-tinted grid.

---

## Public-theme row indicators

`.ag-theme-ramboq .ag-row.pos-long / .pos-short` carry a `box-shadow inset 4px` indicator on the row, but the public theme's `ag-col-fill` cells (Account / Symbol columns) use a *solid* `#e8e0d0` background which covered the row-level shadow on the leftmost cell — borders were invisible on the public performance page when no account filter was applied. Fix: cast the indicator onto `.ag-cell:first-child` directly so it sits above the cell's solid background. Algo theme already used a transparent (8 % alpha) `ag-col-fill` so the row-level shadow showed through; only the public theme needed the per-cell rule.

---

## Chart zoom + pan (PriceChart, OptionsPayoff)

Both SVG chart components ([`frontend/src/lib/PriceChart.svelte`](frontend/src/lib/PriceChart.svelte), [`frontend/src/lib/OptionsPayoff.svelte`](frontend/src/lib/OptionsPayoff.svelte)) carry a wheel-zoom + drag-pan + reset toolbar implemented in pure SVG/maths — no chart library.

**State**: each chart owns a `zoom: {xMin, xMax} | null` and `pan: {startClientX, startMin, startMax} | null`. The existing `xOf()` / `tMin` / `sMin` derivations read from `zoom` when set, falling back to the auto-derived data range otherwise. All downstream paths (LTP line, payoff curves, markers, hover tooltip) re-derive automatically.

**Handlers**:
- `onWheel` — clamps to data range when zooming out fully (resets to null), refuses to zoom narrower than 1 second (PriceChart) / 2 % of full range (OptionsPayoff).
- `onPointerDown` / `onPointerMoveSvg` / `onPointerUp` — pointer-captured drag-pan; suppresses hover tooltip while dragging.
- `resetZoom` — toolbar button that snaps back to auto-range. Visible only when `isZoomed` is true.

**CSS**: `cursor: crosshair` by default, `cursor: grabbing` when `.chart-panning` / `.payoff-panning` modifier is active. `touch-action: pan-y` so vertical scroll on mobile still works.

OptionsPayoff resets back to the auto `±span_sigmas × σ × √T` range that the API supplies — so post-reset the chart is consistent with the chart footnote ("±2.5σ (7.3%)").

---

## Market Summary + Market News (public)

`/market` shows the AI summary as the only card on the page (with the dual-timezone timestamp above) plus a separate "Market News" card below. `/performance` consolidates BOTH surfaces into a single tabbed card under the position grids: `[Market Summary | Market News]`. Only one panel is visible at a time so the page doesn't grow unbounded; flipping tabs is a paint, not a fetch (both feeds are loaded on mount).

Tab styling matches the public palette — navy text, champagne underline on the active tab, no extra chrome. Right side of the tab row carries the `lastRefresh` timestamp when on Summary, "Loading…" when news is still loading on first visit. Routes:

- [`/market`](frontend/src/routes/(public)/market/+page.svelte) — single AI-summary card + separate news card.
- [`/performance`](frontend/src/routes/(public)/performance/+page.svelte) — performance grids + tabbed `[Summary | News]` card.

The Gemini market-summary prompt was simplified — the AI's first line used to be a bold `**Daily Market Report — [date] | [date]**` heading, which duplicated the page-level `lastRefresh` timestamp shown above the card. Now the prompt asks for just the dual-timezone timestamp without the title prefix.

---

## Documentation surfaces — three roles

We ship three doc files; they target different audiences:

| File | Audience | What's in it |
|---|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | Operator new to the platform | **Concepts in plain English.** What an agent is, what simulation does, what Greeks mean, what the chase engine does. No JSON, no code paths, no API endpoints. |
| [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Day-to-day operator | **Operations reference.** Exact button labels, condition-tree JSON, API endpoints, config keys, troubleshooting tables. |
| [CLAUDE.md](CLAUDE.md) (this file) | Engineers + AI assistants | **Architecture + design notes.** Code structure, data flow, design rationale, refactoring history. |

Cross-link aggressively — every page on the platform should be findable via at least one of these (USER_GUIDE for the concept, ADMIN_GUIDE for the keystrokes).

---

## InfoHint pattern

Most algo admin pages used to ship a long descriptive paragraph at the top — fine for first-time onboarding but pure noise once the operator knows what the page does. [`frontend/src/lib/InfoHint.svelte`](frontend/src/lib/InfoHint.svelte) replaces those with a small amber `(i)` chip next to the page title; click to toggle an inline popover with the same gradient + amber accent the Settings row info uses. Implemented across `/admin/brokers`, `/admin/options`, `/admin/paper`, `/admin/simulator`, `/admin/settings`. ~30-40 vh saved per page; help text is one click away when needed.

`<InfoHint>` accepts a children snippet so the popover can include HTML / Svelte content. Default `label='i'`; `align='right'` available for header-bar use cases. Component is theme-aligned (no extra CSS in callers).

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
| `api_log_file` | `ramboq_logger.py` | Full API app log (5MB rotating × 5) |

The earlier `api_short_*` tail files were retired — the handler rewrote them in full on every single record, which burned 50+ sync I/O ops per minute during alert bursts. `/api/admin/logs` tails `api_log_file` directly now.

**Dev `/opt/ramboq_dev/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy.sh dev` | Dev deploy output (non-main branches) |
| `api_error_file` | `ramboq_dev_api.service` tee | All API stdout+stderr |
| `api_log_file` | `ramboq_logger.py` | Full API app log (5MB rotating × 5) |

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
