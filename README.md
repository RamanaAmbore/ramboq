# RamboQuant Analytics

A production Streamlit web application for **RamboQuant Analytics LLP**, serving as the public-facing website at [ramboq.com](https://ramboq.com). The app provides investment strategy information, partner onboarding, market data, performance tracking, and user authentication with cookie-based sessions.

## Features

- **Multi-page Streamlit app**: About, Market, Performance, Profile, FAQ, Contact, Post
- **User authentication**: Sign-in / sign-out / registration with encrypted cookies (`streamlit-cookies-manager`)
- **Broker integration**: Zerodha Kite API connectivity via `broker_apis.py`
- **GenAI integration**: AI-powered content via `genai_api.py`
- **Email notifications**: SMTP via Hostinger (`mail_utils.py`)
- **Custom styling**: Full CSS override with background images and favicon
- **Structured logging**: Multi-level file and console logging via `ramboq_logger.py`
- **Config-driven**: All content, secrets, and deploy settings managed via YAML files

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit (Python) |
| Web server | Nginx (reverse proxy + SSL) |
| App server | Streamlit on port `8502` |
| SSL | Let's Encrypt / Certbot |
| Deployment | GitHub Webhook + shell automation |
| Process manager | systemd |
| Broker API | Zerodha Kite |
| AI | GenAI API |

---

## Project Structure

```
/
├── app.py                          # Main Streamlit entrypoint
├── requirements.txt                # Python dependencies
├── src/                            # Application source code
│   ├── about.py, contact.py, faq.py, market.py, performance.py
│   ├── post.py, profile.py, user.py, footer.py, header.py
│   ├── components.py, constants.py, utils_streamlit.py
│   └── helpers/
│       ├── broker_apis.py          # Zerodha Kite integration
│       ├── connections.py          # DB / API connection management
│       ├── date_time_utils.py      # Indian timezone utilities
│       ├── decorators.py           # Retry / logging decorators
│       ├── genai_api.py            # GenAI API wrapper
│       ├── mail_utils.py           # SMTP email sending
│       ├── ramboq_logger.py        # Centralised logging
│       ├── singleton_base.py       # Singleton pattern base class
│       └── utils.py                # Config loaders, path helpers, CSS
├── setup/
│   ├── images/                     # Favicons, background images, certificates
│   ├── resume/                     # PDF resume files
│   ├── style/style.css             # Base CSS
│   └── yaml/
│       ├── config.yaml             # Connection settings, log paths (relative), app flags — tracked in git
│       ├── ramboq_config.yaml      # Page content (about, faq, contact text)
│       ├── ramboq_constants.yaml   # App-wide constants
│       └── secrets.yaml            # ⛔ SMTP + broker credentials (gitignored)
├── etc/
│   └── nginx/sites-available/
│       ├── ramboq.com              # Nginx config for ramboq.com (port 443 → 8502)
│       ├── dev.ramboq.com          # Nginx config for dev.ramboq.com (port 443 → 8503)
│       └── default                 # Nginx default site config
├── var/
│   └── www/html/                   # Static files served by nginx default site
├── webhook/
│   ├── hooks.json                  # Webhook trigger rules (GitHub event + SHA256)
│   ├── deploy.sh                   # Deployment script (pull, sync, restart)
│   ├── initial_deploy.sh           # One-time server setup script (run once before first deploy)
│   ├── log-request.sh              # Incoming request logger
│   ├── ramboq.service              # systemd unit for the Streamlit app
│   ├── ramboq_dev.service          # systemd unit for the dev Streamlit app
│   └── ramboq_hook.service         # systemd unit for the webhook listener
└── ramboq_ssh/                     # Snapshot of prod server files (local reference only)
```

---

## Configuration Files

### `setup/yaml/secrets.yaml` (gitignored — hand-place on server)
```yaml
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQuant Team
smtp_user: <email>
smtp_pass: <password>
kite_accounts:
  <user_id>:
    password: ...
    totp_token: ...
    api_key: ...
    api_secret: ...
cookie_secret: <random-string>
kite_login_url: https://kite.zerodha.com/api/login
kite_twofa_url: https://kite.zerodha.com/api/twofa
gemini_api_key: <gemini-api-key>
```

### `setup/yaml/config.yaml` (tracked in git — server flags overridden by `initial_deploy.sh`, preserved across deploys)
```yaml
# Connection settings
retry_count: 3
conn_reset_hours: 23

# Log file paths (relative to app working directory — uniform across prod, dev, and pod)
file_log_file: .log/log_file
error_log_file: .log/error_file
short_file_log_file: .log/short_log_file
short_error_log_file: .log/short_error_file

# Log levels (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)
file_log_level: 10
error_log_level: 40
console_log_level: 40

# App flags — set to True on server by initial_deploy.sh; preserved across deploys
prod: False
mail: False
perplexity: False
enforce_password_standard: False
```

---

## Installation (Dev)

### Prerequisites
- Python 3.11+
- `pip`
- nginx (for production)
- systemd (for production)

### Steps

```bash
git clone https://github.com/<org>/ramboq.git
cd ramboq
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Hand-place `setup/yaml/secrets.yaml` (not in git). `config.yaml` is tracked in git with safe defaults — update `prod`, `mail`, `perplexity` flags on the server after first deploy.

Run locally:
```bash
streamlit run app.py --server.port=8502
```

---

## Production Server Setup

The production server runs at `/opt/ramboq/` on a Linux (Ubuntu) server.

### Automated Setup with `initial_deploy.sh`

Steps 1–8 are automated by `webhook/initial_deploy.sh`. Run it once on a fresh server after cloning or copying the script:

```bash
# Set up both prod and dev (HTTPS clone, no SSH key)
sudo bash /opt/ramboq/webhook/initial_deploy.sh --env both

# Set up with SSH keys for git authentication
sudo bash /opt/ramboq/webhook/initial_deploy.sh \
  --env both \
  --ssh-key-prod /path/to/prod_key \
  --ssh-key-dev /path/to/dev_key \
  --branch-dev dev
```

The script handles: system packages, SSH setup, git clone, venv, pip install, log directories, `config.yaml` template, systemd service install, nginx config, sudoers, and service startup.

**After the script completes, you still need to do manually:**
1. Fill in `secrets.yaml` with real SMTP/Kite credentials
2. Set Cloudflare DNS records to grey cloud — see Step 10
3. Run certbot for SSL certificates — see Step 6
4. Add GitHub webhook — see Step 9
5. Restart services after filling in secrets: `sudo systemctl restart ramboq.service ramboq_dev.service`

---

### Step 6. SSL Certificate (Let's Encrypt / Certbot)

**Prerequisite:** DNS must resolve to your server IP before running certbot. See Step 10.

```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com
```

Certbot will verify domain ownership via HTTP challenge, issue the cert, add SSL directives to nginx, and reload nginx.

**Expanding an existing cert** (e.g. to add a new hostname later):
```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com
# Select "Expand" when prompted
```

**Auto-renewal** — Certbot installs a systemd timer automatically. Verify:
```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

**Verify certificate covers correct domains:**
```bash
openssl s_client -connect ramboq.com:443 -servername ramboq.com 2>/dev/null \
    | openssl x509 -noout -text | grep -A5 "Subject Alternative"
```

---

### If updating service files after initial setup

Service files in the repo under `webhook/` are the source of truth. After changing them:
```bash
sudo cp /opt/ramboq/webhook/ramboq.service /etc/systemd/system/ramboq.service
sudo systemctl daemon-reload && sudo systemctl restart ramboq.service
```

---

### Step 9. GitHub Webhook Setup

The webhook listener runs as a systemd service (`ramboq_hook.service`) on port `9001` and is proxied via nginx at `https://webhook.ramboq.com/hooks/update`. A single webhook handles both prod and dev deploys — branch routing is done inside `deploy.sh`.

**Prerequisite:** The `webhook.ramboq.com` DNS record must be **grey cloud (DNS only)** in Cloudflare before proceeding. See Step 10.

**Step 1 — Note the webhook secret from hooks.json**

The secret is defined in `webhook/hooks.json` under `payload-hmac-sha256.secret`. GitHub will sign every payload with this secret and the listener will reject requests that don't match.

**Step 2 — Add the webhook in GitHub**

1. Go to **GitHub → repo → Settings → Webhooks → Add webhook**
2. Fill in:
   - **Payload URL:** `https://webhook.ramboq.com/hooks/update`
   - **Content type:** `application/json`
   - **Secret:** value from `hooks.json` → `payload-hmac-sha256.secret`
   - **Which events:** select **Just the push event**
   - **Active:** checked
3. Click **Add webhook**

GitHub will immediately send a ping event. A green tick next to the webhook confirms nginx and the listener are reachable.

**Step 3 — Verify the listener is running**

```bash
sudo systemctl status ramboq_hook.service
sudo ss -tlnp | grep 9001
```

**Step 4 — Test by pushing a commit**

```bash
# From local machine
git push origin main     # triggers prod deploy
git push origin dev      # triggers dev deploy
```

Watch the deploy log:
```bash
tail -f /opt/ramboq/.log/hook_debug.log
```

**Step 5 — Debug if webhook shows a red cross in GitHub**

```bash
# Check webhook listener errors
tail -50 /opt/ramboq/.log/hook.log

# Check nginx is proxying correctly
sudo nginx -t
curl -I https://webhook.ramboq.com/hooks/update

# Check incoming request log
tail -20 /opt/ramboq/.log/incoming_requests.log
```

Common causes:
- `webhook.ramboq.com` is orange cloud in Cloudflare — switch to grey
- `ramboq_hook.service` is not running — `sudo systemctl start ramboq_hook.service`
- Secret in `hooks.json` doesn't match the secret set in GitHub webhook settings

### 10. Cloudflare DNS Setup

Add all DNS records in Cloudflare dashboard → your domain → **DNS → Records**.

| Type | Name | IPv4 | Proxy status | Why |
|---|---|---|---|---|
| `A` | `ramboq.com` | server IP | Orange (proxied) | Prod site — Cloudflare CDN and DDoS protection |
| `A` | `www` | server IP | Orange (proxied) | www redirect |
| `A` | `webhook` | server IP | **Grey (DNS only)** | Must be unproxied — Cloudflare intercepts TLS and breaks webhook HMAC validation |
| `A` | `dev` | server IP | **Grey (DNS only)** | Must be unproxied — certbot HTTP challenge fails if Cloudflare proxies the request |

> **Important:** `webhook` and `dev` must be **DNS only (grey cloud)**. If either is orange (proxied), certbot will fail with `NXDOMAIN` or connection errors and the GitHub webhook will return 502.

**Verify all records resolve to your server IP (not a Cloudflare IP):**

```bash
dig +short ramboq.com
dig +short webhook.ramboq.com
dig +short dev.ramboq.com
```

`webhook` and `dev` must return your server's IP directly. If any returns a Cloudflare IP (`104.x.x.x` or `172.x.x.x` range), switch it to grey cloud in Cloudflare and wait for propagation before continuing.

**Verify propagation before running certbot:**

```bash
# Wait until this returns your server IP
watch -n5 dig +short dev.ramboq.com
```

---

## First-Time Dev Deployment (Prod Already Running)

These steps set up `/opt/ramboq_dev` on a server where prod (`/opt/ramboq`) is already working.

### Automated (recommended)

```bash
sudo bash /opt/ramboq/webhook/initial_deploy.sh --env dev --branch-dev dev
```

Then fill in secrets and restart:
```bash
sudo cp /opt/ramboq/setup/yaml/secrets.yaml /opt/ramboq_dev/setup/yaml/secrets.yaml
sudo systemctl restart ramboq_dev.service
```

### Manual steps (if not using initial_deploy.sh)

**1. Clone and checkout dev branch:**
```bash
sudo mkdir -p /opt/ramboq_dev
sudo chown www-data:www-data /opt/ramboq_dev
sudo -u www-data git clone https://github.com/RamanaAmbore/ramboq.git /opt/ramboq_dev
sudo -u www-data git -C /opt/ramboq_dev checkout dev
```

> The explicit checkout ensures `PREV_HEAD` is correct on the first push.

**2. Create venv, install deps, create log dir:**
```bash
cd /opt/ramboq_dev
python3 -m venv venv && source venv/bin/activate
pip install --no-cache-dir -r requirements.txt && deactivate
sudo mkdir -p /opt/ramboq_dev/.log
sudo chown -R www-data:www-data /opt/ramboq_dev/.log
```

**3. Place secrets and set dev flags in config.yaml:**
```bash
sudo cp /opt/ramboq/setup/yaml/secrets.yaml /opt/ramboq_dev/setup/yaml/secrets.yaml
# config.yaml is already present from git — just set prod: False (it is by default)
# Log paths use relative .log/ paths — no changes needed
```

**4. Install service, enable nginx dev site, remove default site:**
```bash
sudo cp /opt/ramboq_dev/webhook/ramboq_dev.service /etc/systemd/system/ramboq_dev.service
sudo systemctl daemon-reload && sudo systemctl enable ramboq_dev.service && sudo systemctl start ramboq_dev.service
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-enabled/dev.ramboq.com
sudo nginx -t && sudo systemctl reload nginx
```

**5. SSL certificate** (DNS must be grey cloud first):
```bash
dig +short dev.ramboq.com   # must return server IP before proceeding
sudo certbot --nginx -d dev.ramboq.com
```

### Push to trigger first deploy and verify

```bash
git push origin dev
```
```bash
tail -f /opt/ramboq_dev/.log/hook_debug.log   # deploy log
tail -f /opt/ramboq_dev/.log/error_file        # app log
sudo ss -tlnp | grep 8503                      # confirm port 8503
```

Then visit **https://dev.ramboq.com**.

---

## Deployment Flow

Every `git push` event triggers webhook validation. Branch routing:

| Branch | Deploys to | Domain | Port | Runtime |
|---|---|---|---|---|
| `main` | `/opt/ramboq` | ramboq.com | 8502 | Python venv |
| `pod` | `/opt/ramboq_pod` | pod.ramboq.com | 8504 | Podman container |
| any other non-`main` | `/opt/ramboq_dev` | dev.ramboq.com | 8503 | Python venv |

Each environment has its own self-contained deploy script. `dispatch.sh` (at `/etc/webhook/`) is the single entry point — it reads the branch name and calls the right script. No env-specific logic exists outside its own directory. `dispatch.sh` is copied from the repo to `/etc/webhook/dispatch.sh` manually after changes — it is **not** auto-deployed.

### End-to-End Flow

```
Developer (local)
    │
    │  git push origin <branch>
    ▼
GitHub
    │  POST https://webhook.ramboq.com/hooks/update
    │  Headers:
    │    X-GitHub-Event: push
    │    X-Hub-Signature-256: sha256=<HMAC of payload>
    │  Payload:
    │    ref: refs/heads/<branch>
    │    repository.name: ramboq
    ▼
Nginx (port 443, webhook.ramboq.com)
    │  location /hooks/update {
    │      proxy_pass http://127.0.0.1:9001/hooks/ramboq-deploy;
    │      proxy_set_header X-Hub-Signature-256 ...;
    │  }
    ▼
webhook listener (port 9001, www-data)
    │  /etc/webhook/hooks.json — validates trigger rules:
    │    1. X-GitHub-Event header == "push"
    │    2. payload.repository.name == "ramboq"
    │    3. HMAC SHA256 signature matches secret
    │
    │  If all pass → executes /etc/webhook/dispatch.sh <ref>
    ▼
/etc/webhook/dispatch.sh (runs as www-data)
    │
    ├── branch == main        → /opt/ramboq/webhook/deploy.sh
    ├── branch starts with pod → /opt/ramboq_pod/webhook/deploy_pod.sh <ref>
    └── any other              → /opt/ramboq_dev/webhook/deploy_dev.sh <ref>
    ▼
Per-environment deploy script (self-contained, no cross-env references)
    ├── git pull origin <branch> into its own APP_ROOT
    ├── prod/dev: pip install -r requirements.txt
    │   pod:     sudo podman build -t ramboq-pod:latest
    └── sudo systemctl restart <APP_SERVICE>
    ▼
ramboq.service / ramboq_dev.service / ramboq_pod.service
    Streamlit on port 8502 (prod), 8503 (dev), 8504 (pod container)
    ▼
Nginx proxies each domain to its port
    ▼
Target environment updated ✅
```

### Webhook Secret

The GitHub webhook and `hooks.json` share a secret for HMAC-SHA256 signature validation:
- Set the secret in **GitHub → repo → Settings → Webhooks → Secret**
- The same secret must be in `webhook/hooks.json` under `payload-hmac-sha256.secret`
- The HMAC rule must include `"parameter": {"source": "header", "name": "X-Hub-Signature-256"}` — without this the webhook listener throws `no source for value retrieval` and returns 500
- Current secret is `f8b12c3d5e8a4fa19b1749a0c6e9312b` — rotate this periodically

### Service Files

All systemd service files live in the repo under `webhook/` and are installed to `/etc/systemd/system/` on the server.

| Service file | Installed path | Purpose |
|---|---|---|
| `webhook/ramboq.service` | `/etc/systemd/system/ramboq.service` | Prod Streamlit app on port 8502 |
| `webhook/ramboq_dev.service` | `/etc/systemd/system/ramboq_dev.service` | Dev Streamlit app on port 8503 |
| `webhook/ramboq_hook.service` | `/etc/systemd/system/ramboq_hook.service` | Webhook listener on port 9001 |

If you update a service file in the repo, copy it to the system and reload:
```bash
sudo cp /opt/ramboq/webhook/ramboq.service /etc/systemd/system/ramboq.service
sudo systemctl daemon-reload
sudo systemctl restart ramboq.service
```

### Log Files

Prod and dev logs are fully separated into their own directories.

**Prod — `/opt/ramboq/.log/`**

| File | Written by | Contents |
|---|---|---|
| `hook_debug.log` | `deploy.sh` | Full deploy output for every push to `main` |
| `hook.log` | `ramboq_hook.service` | All webhook listener output (stdout + stderr combined) |
| `incoming_requests.log` | `log-request.sh` | Requests hitting `/hooks/log` |
| `error_file` | `ramboq.service` tee | All Streamlit stdout+stderr (full app output) |
| `short_error_file` | `ramboq_logger.py` | Python error log, last 50 lines (errors only) |
| `log_file` | `ramboq_logger.py` | Python app full log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Python app log, last 50 lines |

**Dev — `/opt/ramboq_dev/.log/`**

| File | Written by | Contents |
|---|---|---|
| `hook_debug.log` | `deploy_dev.sh` | Full deploy output for every non-main, non-pod push |
| `error_file` | `ramboq_dev.service` tee | All Streamlit stdout+stderr (full app output) |
| `short_error_file` | `ramboq_logger.py` | Python error log, last 50 lines (errors only) |
| `log_file` | `ramboq_logger.py` | Python app full log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Python app log, last 50 lines |

**Pod — `/opt/ramboq_pod/.log/`**

| File | Written by | Contents |
|---|---|---|
| `hook_debug.log` | `deploy_pod.sh` | Full deploy output for every `pod` branch push |
| `error_file` | `ramboq_pod.service` tee | All Streamlit stdout+stderr from container |
| `short_error_file` | `ramboq_logger.py` | Python error log, last 50 lines (errors only) |
| `log_file` | `ramboq_logger.py` | Python app full log (5MB rotating) |
| `short_log_file` | `ramboq_logger.py` | Python app log, last 50 lines |

> `short_error_file` is managed solely by `ramboq_logger.py`'s `LineLimitedFileHandler` — the service does not write to it directly. `error_file` captures all raw Streamlit output via the service's `tee` command.

### Debug Endpoints

| URL | Purpose |
|---|---|
| `https://webhook.ramboq.com/hooks/update` | GitHub webhook endpoint (POST only) |
| `https://webhook.ramboq.com/hooks/log` | Manual request logger — triggers `log-request.sh` |
| `https://dev.ramboq.com` | Dev website served from `/opt/ramboq_dev` |
| `https://pod.ramboq.com` | Pod website served from Podman container |

### Debugging Guide

**Deploy not triggering after a push**
```bash
# Check webhook listener is running
sudo systemctl status ramboq_hook.service

# Check listener is on port 9001
sudo ss -tlnp | grep 9001

# Check nginx is proxying to it
sudo nginx -t
curl -I https://webhook.ramboq.com/hooks/update

# Check if GitHub delivered the payload (GitHub → repo → Settings → Webhooks → recent deliveries)
# Then check what the listener received
tail -50 /opt/ramboq/.log/hook.log
tail -50 /opt/ramboq/.log/incoming_requests.log
```

**Webhook received but "trigger rules were not satisfied"**
```bash
# Check what's in the server's hooks.json — it may have diverged from the repo
cat /opt/ramboq/webhook/hooks.json

# If it still has refs/heads/main restriction or is missing the HMAC parameter field,
# force reset it to the repo version:
cd /opt/ramboq
git diff webhook/hooks.json          # see what differs
git checkout HEAD -- webhook/hooks.json
sudo systemctl restart ramboq_hook.service
```

Common causes:
- `refs/heads/main` restriction in trigger rules — blocks all non-main branch deploys; remove it
- HMAC rule missing `"parameter": {"source": "header", "name": "X-Hub-Signature-256"}` — causes `500 no source for value retrieval`
- Secret in `hooks.json` doesn't match the secret in GitHub webhook settings

> **Note:** `hooks.json` is read from `/opt/ramboq/webhook/hooks.json` (the shared prod directory), not from `/opt/ramboq_dev`. The webhook service is shared — it handles both prod and dev branches.

**Deploy triggered but app not updated**
```bash
# Prod — see exactly what deploy.sh did
tail -100 /opt/ramboq/.log/hook_debug.log

# Dev — see exactly what deploy.sh did
tail -100 /opt/ramboq_dev/.log/hook_debug.log

# Pod — see exactly what deploy_pod.sh did
tail -100 /opt/ramboq_pod/.log/hook_debug.log

# Check the service restarted
sudo systemctl status ramboq.service       # prod
sudo systemctl status ramboq_dev.service   # dev
sudo systemctl status ramboq_pod.service   # pod
```

**Deploy script fails silently — log file shows no output after trigger line**

Root cause: log files or `.git/` objects are owned by `root` instead of `www-data` (caused by manual git/ssh operations run as root). The deploy script's `{ ... } >> $LOG` block fails to open the log file and exits without executing.

```bash
# Find root-owned files in .log/ and .git/
sudo find /opt/ramboq/.log /opt/ramboq/.git -not -user www-data
sudo find /opt/ramboq_dev/.log /opt/ramboq_dev/.git -not -user www-data
sudo find /opt/ramboq_pod/.log /opt/ramboq_pod/.git -not -user www-data

# Fix — run after any manual server operation
sudo chown -R www-data:www-data /opt/ramboq/.git /opt/ramboq/.log
sudo chown -R www-data:www-data /opt/ramboq_dev/.git /opt/ramboq_dev/.log
sudo chown -R www-data:www-data /opt/ramboq_pod/.git /opt/ramboq_pod/.log
```

Also watch for stale remote refs blocking `git fetch` (can happen if old feature branches like `pod/testimonials` conflict with a branch named `pod`):
```bash
cd /opt/ramboq_pod && sudo -u www-data git remote prune origin
```

**App not loading in browser — shows nginx default page**
```bash
# The default nginx site is catching the request — remove it
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# Verify only the correct sites are enabled
ls -la /etc/nginx/sites-enabled/
```

**App not loading in browser — 502 Bad Gateway**
```bash
# Check Streamlit is running on the correct port
sudo ss -tlnp | grep -E '8502|8503'

# Check recent app errors
tail -50 /opt/ramboq/.log/short_error_file          # prod
tail -50 /opt/ramboq_dev/.log/short_error_file      # dev

# Check nginx config and status
sudo nginx -t
sudo systemctl status nginx
```

**Nginx fails to start (e.g. SSL cert missing)**
```bash
sudo nginx -t                           # shows exact error and file
sudo systemctl status nginx             # shows recent journal entries
journalctl -u nginx --since "5 min ago"
```

### Useful Commands

```bash
# Check all service statuses
sudo systemctl status ramboq.service ramboq_dev.service ramboq_hook.service

# Tail deploy logs live
tail -f /opt/ramboq/.log/hook_debug.log         # prod deploys
tail -f /opt/ramboq_dev/.log/hook_debug.log     # dev deploys

# Tail app logs live
tail -f /opt/ramboq/.log/short_error_file        # prod app
tail -f /opt/ramboq_dev/.log/short_error_file    # dev app

# Manually trigger a deploy (bypasses webhook, runs deploy.sh directly)
bash /opt/ramboq/webhook/deploy.sh refs/heads/main
bash /opt/ramboq/webhook/deploy.sh refs/heads/dev

# Reload all services at once (nginx + webhook + app)
bash /opt/ramboq/webhook/services.sh

# Confirm ports are open
sudo ss -tlnp | grep -E '8502|8503|9001'
```

---

## Podman (Containerised) Deployment

The `pod/*` branches deploy to `pod.ramboq.com` as a Podman container. This reuses the same webhook, nginx, systemd, and certbot infrastructure as the other environments.

### Architecture

```
git push origin pod/<branch>
    ↓
webhook → /etc/webhook/dispatch.sh → /opt/ramboq_pod/webhook/deploy_pod.sh
    ↓ git pull into /opt/ramboq_pod
    ↓ sudo podman build -t ramboq-pod:latest /opt/ramboq_pod
    ↓ systemctl restart ramboq_pod.service
    ↓
podman run ramboq-pod:latest -p 8504:8504
  -v /opt/ramboq_pod/setup/yaml:/app/setup/yaml:ro
  -v /opt/ramboq_pod/.log:/app/.log:rw
    ↓
nginx pod.ramboq.com → localhost:8504
```

### Key files

| File | Purpose |
|---|---|
| `Containerfile` | Podman image definition (python:3.13-slim, installs requirements, runs Streamlit on 8504) |
| `.containerignore` | Excludes venv, .git, secrets, logs from image build |
| `etc/nginx/sites-available/pod.ramboq.com` | nginx reverse proxy → port 8504 |
| `webhook/ramboq_pod.service` | systemd unit that runs the Podman container |

### Secrets handling

`secrets.yaml` and `config.yaml` are **never baked into the image** — they are volume-mounted at runtime from `/opt/ramboq_pod/setup/yaml/`. Log paths in `config.yaml` use relative paths (`.log/`), which resolve to `/app/.log/` inside the container (mapped to `/opt/ramboq_pod/.log/` on the host) — identical format to prod and dev.

### First-time pod environment setup (on server)

**1. Install Podman:**
```bash
sudo apt install -y podman
podman --version
```

**2. Add Cloudflare DNS record** — grey cloud (DNS only):
```
pod.ramboq.com → <server-IP>
```

**3. Expand SSL cert to include pod subdomain:**
```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com -d pod.ramboq.com
# Select "Expand" when prompted
```

**4. Clone repo and set up directories:**
```bash
sudo mkdir -p /opt/ramboq_pod
sudo chown www-data:www-data /opt/ramboq_pod
sudo -u www-data git clone https://github.com/RamanaAmbore/ramboq.git /opt/ramboq_pod
sudo -u www-data git -C /opt/ramboq_pod checkout pod   # or your pod/* branch
sudo mkdir -p /opt/ramboq_pod/.log
sudo chown -R www-data:www-data /opt/ramboq_pod/.log
```

**5. Place secret config files:**
```bash
sudo mkdir -p /opt/ramboq_pod/setup/yaml
# Create secrets.yaml manually — do not copy from another environment
sudo nano /opt/ramboq_pod/setup/yaml/secrets.yaml
sudo nano /opt/ramboq_pod/setup/yaml/config.yaml
```
```yaml
# Log paths are relative — resolve to /app/.log/ inside the container (mapped to /opt/ramboq_pod/.log/ on host)
retry_count: 3
conn_reset_hours: 23
file_log_file: .log/log_file
error_log_file: .log/error_file
short_file_log_file: .log/short_log_file
short_error_log_file: .log/short_error_file
file_log_level: 10
error_log_level: 40
console_log_level: 40
prod: True
mail: False
perplexity: False
enforce_password_standard: False
```
```bash
sudo chown -R www-data:www-data /opt/ramboq_pod/setup/yaml/
```

**6. Build initial Podman image:**
```bash
cd /opt/ramboq_pod
podman build -t ramboq-pod:latest .
```

**7. Install and start systemd service:**
```bash
sudo cp /opt/ramboq_pod/webhook/ramboq_pod.service /etc/systemd/system/ramboq_pod.service
sudo systemctl daemon-reload
sudo systemctl enable ramboq_pod.service
sudo systemctl start ramboq_pod.service
sudo systemctl status ramboq_pod.service
```

**8. Enable nginx site:**
```bash
sudo cp /opt/ramboq_pod/etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-available/pod.ramboq.com
sudo ln -sf /etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-enabled/pod.ramboq.com
sudo nginx -t && sudo systemctl reload nginx
```

**9. Add sudoers entry for pod service:**
```bash
sudo visudo
# Add to existing www-data line:
# www-data ALL=NOPASSWD: ... /bin/systemctl restart ramboq_pod.service
```

**10. Verify:**
```bash
sudo ss -tlnp | grep 8504          # Podman container listening
curl -I https://pod.ramboq.com     # nginx forwarding
tail -f /opt/ramboq_pod/.log/hook_debug.log   # deploy log
```

### Ongoing deployment

Push to the `pod` branch:
```bash
git push origin pod
```
`deploy_pod.sh` runs `podman build` then restarts the service automatically.

---

## Security Notes

- `setup/yaml/secrets.yaml` — contains SMTP and broker credentials, **gitignored**, hand-place on server only
- `setup/yaml/config.yaml` — tracked in git with safe defaults; server-specific flag overrides (`prod: True` etc.) are preserved across deploys by the deploy scripts
- `var/www/.ssh/` — SSH keys, **gitignored**, never commit
- The webhook secret in `hooks.json` should be rotated periodically and kept in sync with the GitHub webhook settings
- Port `9001` (webhook listener) is not directly exposed — only accessible via nginx proxy

