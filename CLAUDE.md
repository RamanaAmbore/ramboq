# CLAUDE.md — RamboQuant Project Reference

This file is for Claude Code. It provides project context, file map, patterns, and refactoring notes to avoid re-exploring the codebase from scratch each session.

---

## Project Overview

**RamboQuant** is a production Streamlit web app for RamboQuant Analytics LLP at [ramboq.com](https://ramboq.com). It provides portfolio performance tracking, market updates (via Gemini AI), user onboarding, and investment information.

- **Single codebase**, two deployments: prod (`main` branch) and dev (any non-main branch)
- **No database** — all data comes from Zerodha Kite broker API and YAML config files
- **Auth is partially stubbed** — cookies track session state but backend user validation returns a placeholder

---

## Deployment Architecture

| Environment | Branch | Server path | Port | Domain | Runtime |
|---|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8502 | ramboq.com | Python venv |
| Podman (container dev) | `pod` | `/opt/ramboq_pod` | 8504 | pod.ramboq.com | Podman container |
| Development | any other non-main | `/opt/ramboq_dev` | 8503 | dev.ramboq.com | Python venv |

- GitHub push → webhook at `webhook.ramboq.com/hooks/update` → `deploy.sh` → branch routing → venv+pip OR podman build → systemctl restart
- `webhook.ramboq.com`, `dev.ramboq.com`, and `pod.ramboq.com` must be **grey cloud (DNS only)** in Cloudflare
- For the `pod` branch: `deploy_pod.sh` runs `podman build -t ramboq-pod:latest` then restarts `ramboq_pod.service`
- Secrets are never baked into the Podman image — `setup/yaml/` is volume-mounted at runtime; log paths in `backend_config.yaml` are relative (`.log/`), resolving to `/app/.log/` inside the container (mapped to `/opt/ramboq_pod/.log/` on the host)

---

## Key File Map

### Entry Point
- **`app.py`** — Sets page config, loads CSS/favicon, initialises session state, renders header, routes to page function, renders footer. Page routing is a dict `page_functions = {"about": about, "market": market, ...}` keyed on `st.session_state.active_nav`. On every startup, copies `setup/images/favicon.png` and `setup/streamlit/index.html` into the Streamlit static folder so they survive pip upgrades. Starts background refresh daemon thread.

### Pages (`src/`)
- **`about.py`** — Static content from `ramboq_config['about']`
- **`market.py`** — AI market report via `get_market_update()`; uses cycle date as cache key so it refreshes daily. No spinner — background thread pre-warms cache.
- **`performance.py`** — Three tabs: Funds, Holdings, Positions. Each tab shows: summary (all accounts + TOTAL) first, then per-account detail dataframes, then all-accounts combined dataframe. URL param `?tab=funds|holdings|positions` synced via JS for direct sharing. Fetches broker data via `fetch_margins/holdings/positions(refresh_time)`. Use `refresh_time` consistently — do not call `get_nearest_time()` again mid-function or cache keys diverge.
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
- **`date_time_utils.py`** — Indian/EST timezone utilities using `zoneinfo`. `is_market_open(now, holiday_set, market_start, market_end)` — returns True if not in holiday_set and within time window; weekends NOT hardcoded as closed to support special trading sessions (Muhurat etc.)
- **`ramboq_logger.py`** — Rotating file handlers (5MB), line-limited handlers (50 lines), queue-based async logging
- **`background_refresh.py`** — Daemon thread started once at app startup. Warms market update cache immediately at startup. During market hours: pre-fetches broker data at each interval boundary; sends open summary (15 min after segment open); fires loss alerts. After market close: sends close summary. Segment-aware — handles Equity (NSE/BSE/NFO/CDS) and Commodity (MCX) independently with separate holiday calendars and open/close times.
- **`alert_utils.py`** — Loss alert and market summary notifications. `send_summary(sum_holdings, sum_positions, ist_display, msg_type, label)` — sends open/close summary. `check_and_alert(sum_holdings, sum_positions, alert_state, ist_display)` — checks day P&L thresholds, fires one row per breached threshold. Both send via Telegram Bot API and SMTP email. Message type prefixes: Telegram `Open|Alert|Close`, email subject `RamboQuant Open:|RamboQuant Alert:|RamboQuant Close:`.

### Static Assets (`setup/streamlit/`)
- **`index.html`** — Custom Streamlit entry HTML with RamboQuant Analytics meta tags, OG/Twitter cards, and favicon link. Copied into the Streamlit venv static folder on every deploy and app startup to survive pip upgrades.
- **`favicon.png`** — Reference copy of the Streamlit default favicon (not deployed — source favicon is `setup/images/favicon.png`)

### Webhook / Deployment (`webhook/`)
- **`deploy.sh`** — Prod deploy script (`main` branch); git pull, pip install, copies `setup/images/favicon.png` and `setup/streamlit/index.html` into Streamlit static folder, syncs nginx/static files, restarts service
- **`deploy_dev.sh`** — Dev deploy script (non-main, non-pod branches); same as deploy.sh but without nginx/static sync
- **`deploy_pod.sh`** — Pod deploy script (`pod` branch); runs `podman build` then restarts service. Favicon and index.html are copied inside the container via `Containerfile` (no venv on host)
- **`initial_deploy.sh`** — One-time setup script; run once on a fresh server before first push. Accepts `--env prod|dev|both`, `--ssh-key-prod`, `--ssh-key-dev`, `--branch-dev`. Automates everything except secrets, certbot, Cloudflare DNS, and GitHub webhook
- **`ramboq_pod.service`** — Podman container systemd unit, port 8504; mounts `setup/yaml` and `.log` as volumes
- **`hooks.json`** — Single `ramboq-deploy` hook; validates push event, repo name, and HMAC-SHA256 signature; passes `ref` to `dispatch.sh`. **Deployed to `/etc/webhook/hooks.json`** (independent of all deployment directories). Copy manually after changes: `sudo cp /opt/ramboq/webhook/hooks.json /etc/webhook/hooks.json && sudo systemctl restart ramboq_hook.service`
- **`dispatch.sh`** — Thin router at `/etc/webhook/dispatch.sh`; reads branch from `ref`, calls the correct env's deploy script (`deploy.sh` for `main`, `deploy_pod.sh` for any branch starting with `pod`, `deploy_dev.sh` for everything else). No env-specific logic here. Copy after changes: `sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh`
- **`ramboq.service`** — Prod systemd unit, port 8502; tee pipes Streamlit output to `error_file` only
- **`ramboq_dev.service`** — Dev systemd unit, port 8503; tee pipes Streamlit output to `error_file` only
- **`ramboq_hook.service`** — Webhook listener, port 9001; shared service handles all branches; all output (stdout+stderr) goes to `hook.log`
- **`log-request.sh`** — Logs raw incoming webhook requests

---

## Config Files (`setup/yaml/`)

| File | Tracked | Contents |
|---|---|---|
| `backend_config.yaml` | **Yes — tracked** | `retry_count`, `conn_reset_hours`, relative log paths, log levels, `enforce_password_standard`/`cap_in_dev`/`genai`/`mail`/`telegram` flags (defaults `False`), alert thresholds, market segment definitions; deploy scripts merge new repo config with server's preserved flags |
| `frontend_config.yaml` | Yes | All page content, nav labels, Gemini prompts/params, Mermaid diagrams, fallback market report |
| `constants.yaml` | Yes | 250+ ISD country codes, profile section keys |
| `secrets.yaml` | **No — gitignored** | SMTP creds, Kite API keys/TOTP per account, `cookie_secret`, `kite_login_url`, `kite_twofa_url`, `gemini_api_key`, `telegram_bot_token`, `telegram_chat_id`, `alert_emails` |

`secrets.yaml` must be **hand-placed on the server** — never in git. `initial_deploy.sh` creates `backend_config.yaml` with correct `cap_in_dev` flag; subsequent deploys merge: repo config is the base (picks up new fields), only `enforce_password_standard`/`cap_in_dev`/`genai`/`telegram`/`mail` are overlaid from the server's saved copy.

### Production capabilities — `cap_in_dev` and individual flags

Production capabilities (GenAI, Telegram, email) are controlled by two backend_config.yaml flags that must both be True:

| Flag | Purpose | Prod/pod | Dev (testing) | Dev (idle) |
|---|---|---|---|---|
| `cap_in_dev` | Environment master switch | `True` | `True` | `False` |
| `genai` | GenAI market update (Gemini) | `True` | `True`/`False` | — |
| `telegram` | Telegram alert notifications | `True` | `True`/`False` | — |
| `mail` | Email notifications (SMTP) | `True` | `True`/`False` | — |

**Gate logic:** `is_prod_capable() AND config.get('<flag>')` where `is_prod_capable()` = `cap_in_dev`.

- When `cap_in_dev: False` — all capabilities skip, no CPU/bandwidth used (dev running alongside prod)
- When `cap_in_dev: True` — each capability fires or skips based on its own flag independently
- No code change ever needed — flip flags in backend_config.yaml on the server

**Adding a new production capability:** add its flag to `backend_config.yaml` (default `False`), gate it with `is_prod_capable() AND config.get('<flag>')` in the relevant module. Add the flag to the preserved keys list in `deploy_dev.sh` and `deploy.sh`. Set it to `True` on prod/pod servers.

---

## Alert and Notification System

### Message Types and Prefixes

| Event | Telegram prefix | Email subject prefix |
|---|---|---|
| Market open summary | `Open` | `RamboQuant Open: ` |
| Intra-day loss alert | `Alert` | `RamboQuant Alert: ` |
| Market close summary | `Close` | `RamboQuant Close: ` |

### Open/Close Summary Format
Sent per segment (Equity and Commodity independently):
- **Telegram**: `Open — Equity — Mon, March 30, 2026, 09:30 AM IST` + monospace table
- **Email subject**: `RamboQuant Open: Equity — Mon, March 30, 2026, 09:30 AM IST`
- Holdings table: Account | Cur Val | P&L | P&L% | Day Loss | Day Loss%
- Positions table: Account | P&L
- Accounts shown as masked values (ZG#### / ZJ####)

### Loss Alert Format
One row per breached threshold (abs and pct fire separate rows):
- Columns: Type | Account | Day Loss | Day Loss% | Abs | Pct
- `—` shown for columns not applicable to that threshold

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
- Weekends NOT hardcoded as closed — special trading sessions (Muhurat, special Saturday) work correctly since they are absent from the holiday list
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
| Close summary (per segment) | Once after segment close time, on trading days only |

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
- **Do not commit `secrets.yaml`** — it is gitignored; contains API keys, SMTP credentials, cookie secrets, Telegram token
- **Do not use `st.sidebar`** — sidebar navigation is disabled in `.streamlit/config.toml`; all navigation is via `header.py`
- **Do not add branch filter rules to hooks.json** — branch routing is handled in `dispatch.sh`, not in `hooks.json`; `hooks.json` only validates the event, repo, and HMAC
- **Do not use `2>>&1` in systemd ExecStart** — use `2>&1`; the `>>` append variant causes bash syntax errors in service files
- **Always `chown www-data` after manual server operations** — any file created or modified on the server via SSH (git commands, scp, manual edits) must be owned by `www-data` or deploy scripts will fail silently. After any manual work run: `sudo chown -R www-data:www-data /opt/ramboq/.git /opt/ramboq/.log /opt/ramboq_dev/.git /opt/ramboq_dev/.log /opt/ramboq_pod/.git /opt/ramboq_pod/.log`
- **Do not hardcode weekends as closed** — use `is_market_open()` with the Kite holiday list; special Saturday trading sessions must work
- **Do not add `show_spinner` to `@st.cache_data` on broker/market fetch functions** — background thread pre-warms cache; spinners would show on first load after restart but are misleading since data is already warm

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
| `hook_debug.log` | `deploy.sh` | Prod deploy output (main branch) |
| `hook.log` | `ramboq_hook.service` | All webhook listener output (stdout+stderr combined) |
| `incoming_requests.log` | `log-request.sh` | Raw webhook requests |
| `error_file` | `ramboq.service` tee | All Streamlit stdout+stderr |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines (not written by service) |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

**Dev `/opt/ramboq_dev/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy_dev.sh` | Dev deploy output (non-main, non-pod branches) |
| `error_file` | `ramboq_dev.service` tee | All Streamlit stdout+stderr |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines (not written by service) |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

**Pod `/opt/ramboq_pod/.log/`**

| File | Source | Notes |
|---|---|---|
| `hook_debug.log` | `deploy_pod.sh` | Pod deploy output (`pod` branch) |
| `error_file` | `ramboq_pod.service` tee | All Streamlit stdout+stderr from container |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

> All three environments use the same relative `.log/` paths — no per-environment config changes needed. The `cap_in_dev`/`genai`/`mail`/`telegram` flags differ per environment and are set by `initial_deploy.sh`, then preserved across deploys.

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
| Change deploy branch routing | `webhook/dispatch.sh` — the `if/elif/else` at the bottom; copy to server after changes |
| Change browser tab title or SEO meta tags | `setup/streamlit/index.html` — update `<title>`, OG/Twitter meta tags |
| Change footer text | `setup/yaml/frontend_config.yaml` — `footer_name`, `footer_text2`, `footer_mobile_text3`, `footer_desktop_text3` |
| Change alert thresholds | `setup/yaml/backend_config.yaml` — `alert_loss_abs`, `alert_loss_pct`, `alert_cooldown_minutes` |
| Change alert recipients | `setup/yaml/secrets.yaml` on server — `alert_emails`, `telegram_chat_id` |
| Add/change market segment hours | `setup/yaml/backend_config.yaml` — `market_segments` block |
| Change open/close summary timing | `setup/yaml/backend_config.yaml` — `open_summary_offset_minutes`, `close_summary_offset_minutes` |
