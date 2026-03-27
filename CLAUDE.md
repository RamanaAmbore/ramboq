# CLAUDE.md — RamboQ Project Reference

This file is for Claude Code. It provides project context, file map, patterns, and refactoring notes to avoid re-exploring the codebase from scratch each session.

---

## Project Overview

**RamboQ** is a production Streamlit web app for Rambo Quant Strategies LLP at [ramboq.com](https://ramboq.com). It provides portfolio performance tracking, market updates (via Perplexity AI), user onboarding, and investment information.

- **Single codebase**, two deployments: prod (`main` branch) and dev (any non-main branch)
- **No database** — all data comes from Zerodha Kite broker API and YAML config files
- **Auth is partially stubbed** — cookies track session state but backend user validation returns a placeholder

---

## Deployment Architecture

| Environment | Branch | Server path | Port | Domain |
|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8502 | ramboq.com |
| Development | any non-main | `/opt/ramboq_dev` | 8503 | dev.ramboq.com |

- GitHub push → webhook at `webhook.ramboq.com/hooks/update` → `deploy.sh` → git pull + pip install + systemctl restart
- `webhook.ramboq.com` and `dev.ramboq.com` must be **grey cloud (DNS only)** in Cloudflare — certbot and webhook HMAC validation both break if proxied

---

## Key File Map

### Entry Point
- **`app.py`** — Sets page config, loads CSS/favicon, initialises session state, renders header, routes to page function, renders footer. Page routing is a dict `page_functions = {"about": about, "market": market, ...}` keyed on `st.session_state.active_nav`.

### Pages (`src/`)
- **`about.py`** — Static content from `ramboq_config['about']`
- **`market.py`** — AI market report via `get_market_update()`; uses cycle date as cache key so it refreshes daily
- **`performance.py`** — Three tabs: Funds, Holdings, Positions. Fetches broker data via `fetch_margins/holdings/positions(refresh_time)`. Use `refresh_time` consistently — do not call `get_nearest_time()` again mid-function or cache keys diverge.
- **`profile.py`** — Profile view and update form with nested nominee fields
- **`user.py`** — Sign in / sign up / update password tabs with captcha and email notifications
- **`post.py`** — Investment insights from `ramboq_config['post']`
- **`contact.py`** — Contact form with SMTP notification
- **`faq.py`** — FAQ + Mermaid.js flow diagrams (nav/redemption/succession)
- **`header.py`** — Desktop and mobile nav bars; updates `st.query_params["page"]` and `st.session_state.active_nav`
- **`footer.py`** — Copyright, LLDIN, disclaimer; separate mobile/desktop layouts

### Shared UI (`src/`)
- **`components.py`** — `render_form()`, `write_section_heading()`, `disp_icon_text()`, `write_columns()`
- **`constants.py`** — Streamlit column configs (`holdings_config`, `positions_config`, `margins_config`) and HTML email templates
- **`utils_streamlit.py`** — `@st.cache_data` wrappers for all broker data fetches and `get_market_update()`; `reset_form_state_vars()`; `show_status_dialog()`

### Helpers (`src/helpers/`)
- **`broker_apis.py`** — `fetch_holdings()`, `fetch_positions()`, `fetch_margins()` — each decorated with `@for_all_accounts`; returns a list (one DataFrame per account)
- **`connections.py`** — `Connections` singleton (extends `SingletonBase`) holds one `KiteConnection` per account; handles Kite 2FA login, TOTP, and access token refresh. Re-authenticates after 23 hours (`conn_reset_hours` in `config.yaml`)
- **`decorators.py`** — `@for_all_accounts` iterates all accounts or a single one; `@retry_kite_conn()` retries with `test_conn=True` from attempt 2; `@track_it()` logs execution time; `@lock_it_for_update` / `@update_lock` for thread safety
- **`singleton_base.py`** — Thread-safe singleton via double-checked locking; `_instances` dict keyed by class
- **`utils.py`** — YAML loaders (run at module import), `get_image_bin_file()`, `get_path()`, `get_nearest_time()`, `add_comma_to_df_numbers()`, validators (email, phone, password, PIN, captcha), `CustomDict`
- **`genai_api.py`** — Perplexity AI via OpenAI-compatible client; falls back to `ramboq_config['market']` static content when `prod=False` in `ramboq_deploy.yaml`
- **`mail_utils.py`** — SMTP via Hostinger; respects `prod` and `mail` flags in `ramboq_deploy.yaml` before sending
- **`date_time_utils.py`** — Indian/EST timezone utilities using `zoneinfo`
- **`ramboq_logger.py`** — Rotating file handlers (5MB), line-limited handlers (50 lines), queue-based async logging

### Webhook / Deployment (`webhook/`)
- **`deploy.sh`** — Main deploy script; `main` → `/opt/ramboq` with nginx/static sync; non-main → `/opt/ramboq_dev` without sync
- **`initial_deploy.sh`** — One-time setup script; run once on a fresh server before first push. Accepts `--env prod|dev|both`, `--ssh-key-prod`, `--ssh-key-dev`, `--branch-dev`. Automates everything except secrets, certbot, Cloudflare DNS, and GitHub webhook
- **`hooks.json`** — Validates GitHub push event + repo name + HMAC-SHA256 secret; passes `ref` to `deploy.sh`. **Read from `/opt/ramboq/webhook/hooks.json` only** — the shared prod directory, never from `/opt/ramboq_dev`. After `git pull`, if this file was locally modified on the server, force reset with `git checkout HEAD -- webhook/hooks.json`
- **`ramboq.service`** — Prod systemd unit, port 8502; tee pipes Streamlit output to `error_file` only
- **`ramboq_dev.service`** — Dev systemd unit, port 8503; tee pipes Streamlit output to `error_file` only
- **`ramboq_hook.service`** — Webhook listener, port 9001; shared service handles all branches; all output (stdout+stderr) goes to `hook.log`
- **`log-request.sh`** — Logs raw incoming webhook requests

---

## Config Files (`setup/yaml/`)

| File | Tracked | Contents |
|---|---|---|
| `config.yaml` | Yes | `retry_count` (3), `conn_reset_hours` (23) |
| `ramboq_config.yaml` | Yes | All page content, nav labels, Perplexity prompts/params, Mermaid diagrams, fallback market report |
| `ramboq_constants.yaml` | Yes | 250+ ISD country codes, profile section keys |
| `secrets.yaml` | **No — gitignored** | SMTP creds, Kite API keys/TOTP per account, `cookie_secret`, Perplexity API key |
| `ramboq_deploy.yaml` | **No — gitignored** | Log file paths, log levels, `prod`/`mail`/`perplexity` flags, `enforce_password_standard` |

`secrets.yaml` and `ramboq_deploy.yaml` must be **hand-placed on the server** — they are never in git. Copy from prod to dev when setting up `/opt/ramboq_dev`.

---

## Key Patterns

### Caching
`@st.cache_data` with a time-based `dt` parameter is the cache key. `get_nearest_time()` rounds down to the nearest 10-minute interval — call it **once per page render** and reuse the value. Calling it multiple times risks different cache keys at interval boundaries.

```python
# Correct
refresh_time = get_nearest_time()
df_margins = fetch_margins(refresh_time)
df_holdings, sum_holdings = fetch_holdings(refresh_time, df_margins)
df_positions, sum_positions = fetch_positions(refresh_time)
```

### Multi-Account Broker Calls
`@for_all_accounts` in `decorators.py` wraps broker functions to iterate all accounts. Each call returns a **list of DataFrames** (one per account). Callers use `pd.concat(..., ignore_index=True)` to merge them.

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
- **Do not commit `secrets.yaml` or `ramboq_deploy.yaml`** — they are gitignored for good reason
- **Do not use `st.sidebar`** — sidebar navigation is disabled in `.streamlit/config.toml`; all navigation is via `header.py`
- **Do not add `refs/heads/main` to hooks.json trigger rules** — this blocks all non-main branch deploys; branch routing is handled inside `deploy.sh`, not in `hooks.json`
- **Do not use `2>>&1` in systemd ExecStart** — use `2>&1`; the `>>` append variant causes bash syntax errors in service files

---

## Refactoring Notes

| Area | Note |
|---|---|
| `user.py` auth | Backend validation is stubbed — `validate_user()` always returns `(True, "nop")`. Real auth needs implementing before production user login |
| Twilio alerts | Fully implemented in `ramboq_logger.py` but commented out. Re-enable by uncommenting the `TwilioHandler` class and adding `TWILIO_FROM_NUMBER` / `TWILIO_TO_NUMBER` to config |
| `ramboq_ssh/` | Entire codebase is duplicated here. Can be removed once dev deployment is stable and no longer needed as a reference |
| Regex validators | `validate_email()`, `validate_phone()` etc. in `utils.py` recompile regex on every call. Worth precompiling to module-level constants if form submissions become a bottleneck |
| Parallel broker calls | `fetch_holdings`, `fetch_positions`, `fetch_margins` are called sequentially. Could be parallelised with `concurrent.futures.ThreadPoolExecutor` for faster page load |
| `components.py` | `render_form()` has 9 nested `with` blocks — hard to follow. Candidate for breaking into smaller functions |

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
| `hook_debug.log` | `deploy.sh` | Dev deploy output (non-main branches) |
| `error_file` | `ramboq_dev.service` tee | All Streamlit stdout+stderr |
| `short_error_file` | `ramboq_logger.py` | Last 50 Python error lines (not written by service) |
| `log_file` | `ramboq_logger.py` | Full Python app log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Last 50 Python app log lines |

> Dev log paths are set in `/opt/ramboq_dev/setup/yaml/ramboq_deploy.yaml` (gitignored). `initial_deploy.sh` creates a template — do not copy prod's version verbatim.

---

## Common Tasks — Where to Make Changes

| Task | Files to edit |
|---|---|
| Add a new page | Create `src/newpage.py`, add to `page_functions` dict in `app.py`, add nav label to `ramboq_config.yaml` |
| Change page content (text, FAQs, etc.) | `setup/yaml/ramboq_config.yaml` |
| Change broker data columns shown | `src/constants.py` — update `holdings_config`, `positions_config`, or `margins_config` |
| Change Perplexity AI prompt | `setup/yaml/ramboq_config.yaml` — `pplx_system_msg`, `pplx_user_msg`, `pplx_temperature`, `pplx_max_tokens` |
| Change email template | `src/constants.py` — HTML template strings |
| Change connection retry behaviour | `setup/yaml/config.yaml` — `retry_count`, `conn_reset_hours` |
| Change log verbosity | `setup/yaml/ramboq_deploy.yaml` — `file_log_level`, `error_log_level`, `console_log_level` |
| Add a new broker account | `setup/yaml/secrets.yaml` — add entry under `kite_accounts` |
| Change deploy branch routing | `webhook/deploy.sh` — the `if/else` at the top |
