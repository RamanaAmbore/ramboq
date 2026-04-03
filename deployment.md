# RamboQuant — Deployment Guide

Complete server setup and deployment reference for all three environments.

---

## Architecture Overview

```
Developer (local)
    │  git push origin <branch>
    ▼
GitHub → POST https://webhook.ramboq.com/hooks/update (HMAC-SHA256 signed)
    ▼
Nginx (port 443, webhook.ramboq.com) → proxy to port 9001
    ▼
Webhook listener (ramboq_hook.service, port 9001, www-data)
    │  Validates: push event + repo name + HMAC signature
    │  Calls: /etc/webhook/dispatch.sh <ref>
    ▼
dispatch.sh — routes by branch:
    ├── main         → /opt/ramboq/webhook/deploy.sh prod main
    ├── pod*         → /opt/ramboq_pod/webhook/deploy.sh pod <ref>
    └── any other    → /opt/ramboq_dev/webhook/deploy.sh dev <ref>
    ▼
deploy.sh — git pull, pip install, config merge, systemctl restart
    ▼
App running:
    ├── ramboq.com      (port 8502) — Streamlit + Litestar API (port 8000)
    ├── dev.ramboq.com  (port 8503) — Streamlit + Litestar API (port 8001)
    └── pod.ramboq.com  (port 8504) — Podman container
```

---

## Environments

| Environment | Branch | Server path | Streamlit port | API port | Domain | Database |
|---|---|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8502 | 8000 | ramboq.com | `ramboq` |
| Development | non-main | `/opt/ramboq_dev` | 8503 | 8001 | dev.ramboq.com | `ramboq_dev` |
| Pod (container) | `pod` | `/opt/ramboq_pod` | 8504 | — | pod.ramboq.com | `ramboq_dev` |

All three branches (`main`, `dev`, `pod`) are permanent — never deleted from GitHub.

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

| File | Service | Port | Purpose |
|---|---|---|---|
| `ramboq.service` | ramboq.service | 8502 | Prod Streamlit app |
| `ramboq_dev.service` | ramboq_dev.service | 8503 | Dev Streamlit app |
| `ramboq_pod.service` | ramboq_pod.service | 8504 | Podman container |
| `ramboq_hook.service` | ramboq_hook.service | 9001 | Webhook listener (shared) |

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

`deploy.sh` merges backend_config.yaml on every deploy:
- Repo config is the base (picks up new fields)
- These server flags are preserved: `enforce_password_standard`, `cap_in_dev`, `genai`, `telegram`, `mail`, `notify_on_startup`
- `deploy_branch` is always set fresh by the deploy script

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
| `error_file` | systemd service tee | All Streamlit stdout+stderr |
| `log_file` | ramboq_logger.py | Full Python app log (5MB rotating × 5) |

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
# Service status
sudo systemctl status ramboq.service ramboq_dev.service ramboq_hook.service

# Live logs
tail -f /opt/ramboq/.log/hook_debug.log         # prod deploys
tail -f /opt/ramboq/.log/log_file                # prod app log

# Manual deploy (bypass webhook)
bash /opt/ramboq/webhook/deploy.sh prod main
bash /opt/ramboq_dev/webhook/deploy.sh dev dev

# Confirm ports
sudo ss -tlnp | grep -E '8502|8503|8504|9001|8000|8001'

# Reload all services
sudo systemctl daemon-reload
sudo systemctl restart ramboq.service ramboq_dev.service ramboq_hook.service
sudo nginx -t && sudo systemctl reload nginx
```
