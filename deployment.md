# RamboQuant — Deployment Guide

Complete server setup and deployment reference for all three environments.

---

## Architecture Overview

```
Developer (local)
    │  git push origin <branch>
    ▼
GitHub → POST https://webhook.ramboq.com/hooks/ramboq-deploy (HMAC-SHA256 signed)
    ▼
Nginx (port 443, webhook.ramboq.com) → proxy to 127.0.0.1:9001
    ▼
Webhook listener (ramboq_hook.service, port 9001, www-data) — ONE shared service
    │  Validates: push event + repo name + HMAC signature
    │  Extracts `ref` from JSON payload
    │  Calls: /etc/webhook/dispatch.sh <ref>
    ▼
/etc/webhook/dispatch.sh — routes by branch:
    ├── refs/heads/main   → /opt/ramboq/webhook/deploy.sh prod <ref>
    ├── refs/heads/pod*   → /opt/ramboq_pod/webhook/deploy.sh pod <ref>
    └── all others        → /opt/ramboq_dev/webhook/deploy.sh dev <ref>
    ▼
deploy.sh <ENV> <REF> — env-scoped build + restart:
    ├── cd into APP_ROOT (env-specific)
    ├── git pull the requested branch
    ├── preserve server-local config flags
    ├── write deploy_branch into backend_config.yaml
    ├── pip install + npm run build
    └── systemctl restart <env API service>
    ▼
App running:
    ├── ramboq.com      → Litestar API port 8000 (ramboq_api.service) → DB `ramboq`
    ├── dev.ramboq.com  → Litestar API port 8001 (ramboq_dev_api.service) → DB `ramboq_dev`
    └── pod.ramboq.com  → Podman container `ramboq-pod-app` (ramboq_pod.service)
```

---

## Environments

| Environment | Branch | Server path | API port | Domain | Database | API service |
|---|---|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8000 | ramboq.com | `ramboq` | `ramboq_api.service` |
| Development | non-main | `/opt/ramboq_dev` | 8001 | dev.ramboq.com | `ramboq_dev` | `ramboq_dev_api.service` |
| Pod (container) | `pod` | `/opt/ramboq_pod` | — | pod.ramboq.com | `ramboq_dev` | `ramboq_pod.service` |

All three branches (`main`, `dev`, `pod`) are permanent — never deleted from GitHub. Streamlit services (`ramboq.service`, `ramboq_dev.service`) are disabled — Streamlit has been phased out.

---

## How Environment Isolation Works

Environments share the same codebase but differ through several mechanisms:

### 1. `ENV` arg passed by dispatch.sh
`deploy.sh <ENV>` sets `APP_ROOT`, `APP_SERVICE`, `API_SERVICE` via a case statement — everything downstream keys off these variables.

### 2. `deploy_branch` in `backend_config.yaml`
Every deploy writes the current branch name into `setup/yaml/backend_config.yaml`:
```yaml
deploy_branch: main   # or dev, or pod
```
This value is **always overwritten fresh** (never preserved). `api/database.py` reads it at startup to pick the database: `main` → `ramboq`, anything else → `ramboq_dev`. Alert/email subjects are tagged with `[branch]` for non-main deploys using the same field.

### 3. Server-local config flags (preserved across deploys)
Before `git pull`, `deploy.sh` backs up `backend_config.yaml` to `/tmp`, pulls the new version from git, then overlays these keys from the backup:
```
enforce_password_standard, cap_in_dev, genai, telegram, mail,
notify_on_startup, alert_loss_abs, alert_loss_pct, alert_cooldown_minutes
```
This lets prod and dev keep different values (e.g. `notify_on_startup: true` on dev, `false` on prod; different alert thresholds) without ever committing them. Adding a new such flag requires appending it to the `for key in …` loop in `deploy.sh`.

### 4. Systemd service files
Each env has its own API service with a different `WorkingDirectory` and `--port`:

| Service | WorkingDirectory | Port | Env var |
|---|---|---|---|
| `ramboq_api.service` | `/opt/ramboq` | 8000 | `RAMBOQ_LOG_PREFIX=api_` |
| `ramboq_dev_api.service` | `/opt/ramboq_dev` | 8001 | `RAMBOQ_LOG_PREFIX=api_` |
| `ramboq_pod.service` | container | — | set inside image |

`RAMBOQ_LOG_PREFIX=api_` makes the API write to `api_log_file` / `api_error_file`, separate from the legacy Streamlit `log_file` in the same `.log/` directory.

### 5. Nginx site configs
`etc/nginx/sites-available/ramboq.com` proxies to 8000; `dev.ramboq.com` proxies to 8001; `pod.ramboq.com` proxies to 8504. Synced to `/etc/nginx/sites-available/` by prod deploy when `etc/` files change.

### 6. `secrets.yaml` (gitignored, per-server)
Hand-placed on each server path. Contains Kite keys, SMTP creds, DB password, Telegram token, JWT cookie secret. Never committed; update all three server copies individually via SSH.

### What's shared across environments
- `ramboq_hook.service` (single webhook listener on port 9001)
- `/etc/webhook/dispatch.sh` and `/etc/webhook/hooks.json` (single copy, routes by branch)
- PostgreSQL instance (same server, separate databases per env)

### What deploy.sh restarts
| Env | Restarts |
|---|---|
| `prod` | `ramboq_api.service` only (Streamlit skipped — disabled) |
| `dev` | `ramboq_dev_api.service` only (Streamlit skipped — disabled) |
| `pod` | `ramboq_pod.service` (Podman container) |

Deploy notification (`notify_deploy.py`) reports status of all 3 services (`ramboq_api`, `ramboq_dev_api`, `ramboq_hook`) in every message — this is informational cross-env visibility, not the list of what was restarted.

---

## Prerequisites

- Ubuntu server with public IP
- Python 3.11+
- PostgreSQL 17
- Node.js 20+ (for SvelteKit build)
- nginx, certbot, systemd
- Podman (for pod environment only)

---

## Initial Server Setup

### Automated

```bash
sudo bash /opt/ramboq/webhook/initial_deploy.sh --env both
```

This handles: system packages, SSH setup, git clone, venv, pip install, log directories, systemd services, nginx config, and sudoers.

**After the script, do manually:**
1. Place `secrets.yaml` with real credentials (see below)
2. Set Cloudflare DNS records (grey cloud for webhook/dev/pod)
3. Run certbot for SSL
4. Add GitHub webhook
5. Set up PostgreSQL databases
6. Restart services

### PostgreSQL Setup

```sql
-- As postgres superuser
CREATE DATABASE ramboq OWNER rambo_admin;
CREATE DATABASE ramboq_dev OWNER rambo_admin;
```

Tables are auto-created on first API startup via `init_db()`.

The API selects the database by `deploy_branch` in `backend_config.yaml`:
- `main` → `ramboq`
- anything else → `ramboq_dev`

### Secrets File

Hand-place `setup/yaml/secrets.yaml` on all three server paths. Never committed to git.

```yaml
# SMTP
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQuant Team
smtp_user: <email>
smtp_pass: <password>

# Broker accounts
kite_accounts:
  <user_id>:
    password: ...
    totp_token: ...
    api_key: ...
    api_secret: ...
kite_login_url: https://kite.zerodha.com/api/login
kite_twofa_url: https://kite.zerodha.com/api/twofa

# Database
db_user: rambo_admin
db_password: <password>

# Auth
cookie_secret: <random-string>

# AI
gemini_api_key: <key>

# Notifications
telegram_bot_token: <token>
telegram_chat_id: <group-chat-id>
alert_emails:
  - <email>
```

Update on all three servers individually:
```bash
sudo nano /opt/ramboq/setup/yaml/secrets.yaml
sudo nano /opt/ramboq_dev/setup/yaml/secrets.yaml
sudo nano /opt/ramboq_pod/setup/yaml/secrets.yaml
```

---

## SSL Certificates

**Prerequisite:** DNS must resolve to server IP (grey cloud in Cloudflare).

```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com -d pod.ramboq.com
```

Auto-renewal via systemd timer:
```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

---

## Cloudflare DNS

| Type | Name | Target | Proxy |
|---|---|---|---|
| A | `ramboq.com` | server IP | Orange (proxied) |
| A | `www` | server IP | Orange (proxied) |
| A | `webhook` | server IP | **Grey (DNS only)** |
| A | `dev` | server IP | **Grey (DNS only)** |
| A | `pod` | server IP | **Grey (DNS only)** |

`webhook`, `dev`, and `pod` **must** be grey cloud — Cloudflare proxy breaks webhook HMAC validation and certbot HTTP challenges.

---

## GitHub Webhook

1. Go to **GitHub → repo → Settings → Webhooks → Add webhook**
2. Payload URL: `https://webhook.ramboq.com/hooks/update`
3. Content type: `application/json`
4. Secret: value from `hooks.json` → `payload-hmac-sha256.secret`
5. Events: **Just the push event**

Verify:
```bash
sudo systemctl status ramboq_hook.service
sudo ss -tlnp | grep 9001
```

---

## Service Files

All service files are in `webhook/` and installed to `/etc/systemd/system/`.

| File | Service | Port | Purpose | Status |
|---|---|---|---|---|
| `ramboq_api.service` | ramboq_api.service | 8000 | Prod Litestar API (uvicorn) | enabled |
| `ramboq_dev_api.service` | ramboq_dev_api.service | 8001 | Dev Litestar API (uvicorn) | enabled |
| `ramboq_hook.service` | ramboq_hook.service | 9001 | Webhook listener (shared, env-agnostic) | enabled |
| `ramboq_pod.service` | ramboq_pod.service | container | Podman container (pod branch only) | enabled |
| `ramboq.service` | ramboq.service | 8502 | Prod Streamlit (legacy, phased out) | **disabled** |
| `ramboq_dev.service` | ramboq_dev.service | 8503 | Dev Streamlit (legacy, phased out) | **disabled** |

After updating a service file:
```bash
sudo cp /opt/ramboq/webhook/ramboq.service /etc/systemd/system/ramboq.service
sudo systemctl daemon-reload && sudo systemctl restart ramboq.service
```

After updating `hooks.json` or `dispatch.sh`:
```bash
sudo cp /opt/ramboq/webhook/hooks.json /etc/webhook/hooks.json
sudo cp /opt/ramboq/webhook/dispatch.sh /etc/webhook/dispatch.sh
sudo systemctl restart ramboq_hook.service
```

---

## Litestar API Deployment

The API runs alongside Streamlit on each environment. On the server:

```bash
# Start API (includes background tasks + DB init)
bash run_api.sh --no-reload    # production mode

# Or with auto-reload for dev
bash run_api.sh
```

The API:
- Connects to PostgreSQL (db selected by `deploy_branch`)
- Creates tables on startup if they don't exist
- Starts background tasks (market warm, performance refresh, alerts)
- Serves SvelteKit build if `frontend/build/` exists

### SvelteKit Build (for production)

```bash
cd frontend && npm install && npm run build
```

The built files at `frontend/build/` are served by Litestar as static files.

---

## Config Merge on Deploy

`deploy.sh` merges `backend_config.yaml` on every deploy:
- Repo config is the base (picks up new fields)
- Server flags preserved: `enforce_password_standard`, `cap_in_dev`, `genai`, `telegram`, `mail`, `notify_on_startup`, `alert_loss_abs`, `alert_loss_pct`, `alert_cooldown_minutes`
- `deploy_branch` is always set fresh by the deploy script

To add a new server-local flag: append its name to the `for key in …` loop in [webhook/deploy.sh](webhook/deploy.sh) and default it to a safe value in the repo's `backend_config.yaml`.

---

## Podman Environment

The `pod` branch runs inside a Podman container.

```bash
# First-time setup
sudo apt install -y podman
sudo mkdir -p /opt/ramboq_pod
sudo chown www-data:www-data /opt/ramboq_pod
sudo -u www-data git clone <repo> /opt/ramboq_pod
sudo -u www-data git -C /opt/ramboq_pod checkout pod
```

Secrets are volume-mounted at runtime (never baked into the image):
```
-v /opt/ramboq_pod/setup/yaml:/app/setup/yaml:ro
-v /opt/ramboq_pod/.log:/app/.log:rw
```

Container name: `ramboq-pod-app` (set by `--name` in service file).

---

## Log Files

Each environment has its own `.log/` directory:

| File | Source | Contents |
|---|---|---|
| `hook_debug.log` | deploy.sh | Deploy script output |
| `hook.log` | ramboq_hook.service | Webhook listener output (shared, prod only) |
| `api_log_file` | Litestar API (RAMBOQ_LOG_PREFIX=api_) | API app log — read by `/api/admin/logs` |
| `api_error_file` | Litestar API systemd tee | API stdout+stderr (5MB rotating × 5) |
| `api_short_log_file`, `api_short_error_file` | ramboq_logger.py | Last 50 lines each |
| `log_file`, `error_file` | legacy Streamlit | Stale once Streamlit is disabled |

---

## Debugging

### Deploy not triggering
```bash
sudo systemctl status ramboq_hook.service
sudo ss -tlnp | grep 9001
tail -50 /opt/ramboq/.log/hook.log
```

### Deploy triggered but app not updated
```bash
tail -100 /opt/ramboq/.log/hook_debug.log      # prod
tail -100 /opt/ramboq_dev/.log/hook_debug.log   # dev
sudo systemctl status ramboq.service
```

### Permission issues (deploy fails silently)
```bash
# Always run after manual server operations
sudo chown -R www-data:www-data /opt/ramboq/.git /opt/ramboq/.log
sudo chown -R www-data:www-data /opt/ramboq_dev/.git /opt/ramboq_dev/.log
sudo chown -R www-data:www-data /opt/ramboq_pod/.git /opt/ramboq_pod/.log
```

### 502 Bad Gateway
```bash
sudo ss -tlnp | grep -E '8502|8503|8504'
tail -50 /opt/ramboq/.log/error_file
sudo nginx -t
```

### PostgreSQL connection issues
```bash
PGPASSWORD='<password>' psql -U rambo_admin -h localhost -d ramboq -c 'SELECT 1;'
```

---

## Useful Commands

```bash
# Service status (active services)
sudo systemctl status ramboq_api.service ramboq_dev_api.service ramboq_hook.service

# Live logs
tail -f /opt/ramboq/.log/hook_debug.log              # prod deploys
tail -f /opt/ramboq_dev/.log/hook_debug.log          # dev deploys
tail -f /opt/ramboq/.log/api_log_file                # prod API app log
tail -f /opt/ramboq_dev/.log/api_log_file            # dev API app log

# Manual deploy (bypass webhook)
sudo -u www-data bash /opt/ramboq/webhook/deploy.sh prod refs/heads/main
sudo -u www-data bash /opt/ramboq_dev/webhook/deploy.sh dev refs/heads/dev

# Confirm ports
sudo ss -tlnp | grep -E '8000|8001|9001'

# Reload all services
sudo systemctl daemon-reload
sudo systemctl restart ramboq_api.service ramboq_dev_api.service ramboq_hook.service
sudo nginx -t && sudo systemctl reload nginx

# Disable Streamlit (one-time)
sudo systemctl disable --now ramboq.service ramboq_dev.service
```
