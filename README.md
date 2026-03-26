# RamboQ — Rambo Quant Strategies

A production Streamlit web application for **Rambo Quant Strategies LLP**, serving as the public-facing website at [ramboq.com](https://ramboq.com). The app provides investment strategy information, partner onboarding, market data, performance tracking, and user authentication with cookie-based sessions.

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
│       ├── config.yaml             # General app config (retry, ISD codes, etc.)
│       ├── ramboq_config.yaml      # Page content (about, faq, contact text)
│       ├── ramboq_constants.yaml   # App-wide constants
│       ├── ramboq_deploy.yaml      # ⛔ Prod-only logging paths & flags (gitignored)
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
smtp_user: <email>
smtp_pass: <password>
kite_accounts:
  <user_id>:
    password: ...
    totp_token: ...
    api_key: ...
    api_secret: ...
cookie_secret: <random-string>
```

### `setup/yaml/ramboq_deploy.yaml` (gitignored — hand-place on server)
```yaml
file_log_file: /opt/ramboq/.log/log_file
error_log_file: /opt/ramboq/.log/error_file
short_file_log_file: /opt/ramboq/.log/short_log_file
short_error_log_file: /opt/ramboq/.log/short_error_file
prod: True
mail: False
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

Hand-place `setup/yaml/secrets.yaml` and `setup/yaml/ramboq_deploy.yaml` (not in git).

Run locally:
```bash
streamlit run app.py --server.port=8502
```

---

## Production Server Setup

The production server runs at `/opt/ramboq/` on a Linux (Ubuntu) server. Follow these steps in order for a fresh server setup.

### 1. System Prerequisites

```bash
sudo apt update && sudo apt upgrade -y

# Install nginx, certbot, python3, pip, git
sudo apt install -y nginx python3 python3-pip python3-venv git

# Install webhook binary
sudo apt install -y webhook

# Verify installations
nginx -v
python3 --version
webhook --version
```

### 2. Clone the Repository

```bash
sudo mkdir -p /opt/ramboq
sudo chown $USER:$USER /opt/ramboq
git clone https://github.com/RamanaAmbore/ramboq.git /opt/ramboq
cd /opt/ramboq
```

### 3. Python Virtual Environment

```bash
cd /opt/ramboq
python3 -m venv venv
source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
deactivate
```

### 4. Hand-Place Secret Config Files and Create Log Directory

These files are gitignored and must be created manually on the server:

```bash
mkdir -p /opt/ramboq/setup/yaml
mkdir -p /opt/ramboq/.log
sudo chown -R www-data:www-data /opt/ramboq/.log

# Create secrets.yaml
nano /opt/ramboq/setup/yaml/secrets.yaml
```

Paste in (fill real values):
```yaml
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQ Team
smtp_user: rambo@ramboq.com
smtp_pass: <your-smtp-password>
kite_accounts:
    <USER_ID>:
        password: <password>
        totp_token: <totp>
        api_key: <api_key>
        api_secret: <api_secret>
cookie_secret: <random-strong-string>
kite_login_url: https://kite.zerodha.com/api/login
```

```bash
# Create ramboq_deploy.yaml
nano /opt/ramboq/setup/yaml/ramboq_deploy.yaml
```

Paste in (prod paths):
```yaml
file_log_file: /opt/ramboq/.log/log_file
error_log_file: /opt/ramboq/.log/error_file
short_file_log_file: /opt/ramboq/.log/short_log_file
short_error_log_file: /opt/ramboq/.log/short_error_file
file_log_level: 10
error_log_level: 40
console_log_level: 40
prod: True
mail: False
```

### 5. Nginx Setup

> **Important:** The default nginx site (`server_name _;`) catches ALL requests that don't match a named server block. If it is enabled in `sites-enabled`, it will intercept requests to `ramboq.com` and `dev.ramboq.com` and show the nginx default HTML page instead of the Streamlit app. It **must be removed** from `sites-enabled`.

```bash
sudo cp /opt/ramboq/etc/nginx/sites-available/ramboq.com /etc/nginx/sites-available/ramboq.com
sudo cp /opt/ramboq/etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-available/dev.ramboq.com

# Remove the default site — this is the cause of the nginx default page showing
sudo rm -f /etc/nginx/sites-enabled/default

# Symlink the app sites
sudo ln -sf /etc/nginx/sites-available/ramboq.com /etc/nginx/sites-enabled/ramboq.com
sudo ln -sf /etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-enabled/dev.ramboq.com

# Verify only the correct sites are enabled
ls -la /etc/nginx/sites-enabled/
# Expected: ramboq.com -> ... and dev.ramboq.com -> ... only

# Test and reload
sudo nginx -t && sudo systemctl reload nginx
```

### 6. SSL Certificate (Let's Encrypt / Certbot)

Install Certbot if not present:
```bash
sudo apt install -y certbot python3-certbot-nginx
```

Issue certificate (covers main domain, webhook subdomain, and dev domain):
```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com
```

Certbot will:
1. Verify domain ownership via HTTP challenge
2. Issue the certificate
3. Auto-edit your nginx config to add SSL directives
4. Reload nginx

**Expanding an existing cert** (e.g. to add a new hostname later):
```bash
sudo certbot --nginx -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com
# Select "Expand" when prompted
```

**Auto-renewal** — Certbot installs a systemd timer automatically. Verify:
```bash
sudo systemctl status certbot.timer
# Test renewal dry-run
sudo certbot renew --dry-run
```

**Verify certificate covers correct domains:**
```bash
openssl s_client -connect ramboq.com:443 -servername ramboq.com 2>/dev/null \
    | openssl x509 -noout -text | grep -A5 "Subject Alternative"
```

### 7. systemd Services

**Prod service** — runs from `/opt/ramboq`, logs to `/opt/ramboq/.log/`, port 8502:
```bash
sudo cp /opt/ramboq/webhook/ramboq.service /etc/systemd/system/ramboq.service
```

**Dev service** — runs from `/opt/ramboq_dev`, logs to `/opt/ramboq_dev/.log/`, port 8503:
```bash
sudo cp /opt/ramboq/webhook/ramboq_dev.service /etc/systemd/system/ramboq_dev.service
```

**Webhook listener** — shared service, logs to `/opt/ramboq/.log/`, port 9001:
```bash
sudo cp /opt/ramboq/webhook/ramboq_hook.service /etc/systemd/system/ramboq_hook.service
```

Make deploy scripts executable:
```bash
chmod +x /opt/ramboq/webhook/deploy.sh
chmod +x /opt/ramboq/webhook/log-request.sh
chmod +x /opt/ramboq/webhook/services.sh
```

Reload systemd and enable all services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ramboq.service ramboq_dev.service ramboq_hook.service
sudo systemctl start ramboq.service ramboq_dev.service ramboq_hook.service
```

Verify all are running:
```bash
sudo systemctl status ramboq.service
sudo systemctl status ramboq_dev.service
sudo systemctl status ramboq_hook.service

# Confirm ports are open
sudo ss -tlnp | grep -E '8502|8503|9001'
```

Expected:
```
LISTEN  0  511  0.0.0.0:8502  ...  streamlit   (prod)
LISTEN  0  511  0.0.0.0:8503  ...  streamlit   (dev)
LISTEN  0  511  0.0.0.0:9001  ...  webhook
```

### 8. sudoers for `www-data`

The webhook runs as `www-data` and needs passwordless sudo for specific commands. Edit sudoers directly:
```bash
sudo visudo
```

Find or add these lines:
```
www-data ALL=NOPASSWD: /bin/cp
www-data ALL=NOPASSWD: /usr/sbin/nginx
www-data ALL=NOPASSWD: /bin/systemctl reload nginx
www-data ALL=NOPASSWD: /bin/systemctl restart ramboq.service
www-data ALL=NOPASSWD: /bin/systemctl restart ramboq_dev.service
www-data ALL=NOPASSWD: /bin/systemctl restart ramboq_hook.service
```

Save and verify:
```bash
sudo visudo -c
```

### 9. GitHub Webhook Setup

The webhook listener runs as a systemd service (`ramboq_hook.service`) on port `9001` and is proxied via nginx at `https://webhook.ramboq.com/hooks/update`. A single webhook handles both prod and dev deploys — branch routing is done inside `deploy.sh`.

**Prerequisite:** The `webhook.ramboq.com` DNS record must be **grey cloud (DNS only)** in Cloudflare before proceeding. See Step 10.

**Step 1 — Note the webhook secret from hooks.json**

The secret is defined in `webhook/hooks.json` under `payload-hash-sha256.secret`. GitHub will sign every payload with this secret and the listener will reject requests that don't match.

**Step 2 — Add the webhook in GitHub**

1. Go to **GitHub → repo → Settings → Webhooks → Add webhook**
2. Fill in:
   - **Payload URL:** `https://webhook.ramboq.com/hooks/update`
   - **Content type:** `application/json`
   - **Secret:** value from `hooks.json` → `payload-hash-sha256.secret`
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
tail -50 /opt/ramboq/.log/hook.err

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

### 1. Clone the repo into the dev directory

```bash
sudo mkdir -p /opt/ramboq_dev
sudo chown www-data:www-data /opt/ramboq_dev
sudo -u www-data git clone https://github.com/RamanaAmbore/ramboq.git /opt/ramboq_dev
sudo -u www-data git -C /opt/ramboq_dev checkout dev
```

The explicit checkout ensures `PREV_HEAD` is correct on the first push — without it the repo starts on `main` and the first deploy diff compares `main` vs the pushed branch instead of just the new changes.

### 2. Create virtualenv and install dependencies

```bash
cd /opt/ramboq_dev
python3 -m venv venv
source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
deactivate
```

### 3. Create the dev log directory

```bash
sudo mkdir -p /opt/ramboq_dev/.log
sudo chown -R www-data:www-data /opt/ramboq_dev/.log
```

### 4. Place secret config files

`secrets.yaml` is identical to prod — copy it directly. `ramboq_deploy.yaml` must use **dev-specific log paths**:

```bash
sudo mkdir -p /opt/ramboq_dev/setup/yaml

# secrets.yaml — same credentials as prod
sudo cp /opt/ramboq/setup/yaml/secrets.yaml /opt/ramboq_dev/setup/yaml/secrets.yaml

# ramboq_deploy.yaml — dev version with /opt/ramboq_dev/.log/ paths
sudo nano /opt/ramboq_dev/setup/yaml/ramboq_deploy.yaml
```

Paste in (note all log paths point to `/opt/ramboq_dev/.log/`):
```yaml
file_log_file: /opt/ramboq_dev/.log/log_file
error_log_file: /opt/ramboq_dev/.log/error_file
short_file_log_file: /opt/ramboq_dev/.log/short_log_file
short_error_log_file: /opt/ramboq_dev/.log/short_error_file
file_log_level: 10
error_log_level: 40
console_log_level: 40
prod: False
mail: False
```

```bash
sudo chown -R www-data:www-data /opt/ramboq_dev/setup/yaml/
```

### 5. Install and start the dev systemd service

```bash
sudo cp /opt/ramboq_dev/webhook/ramboq_dev.service /etc/systemd/system/ramboq_dev.service
sudo systemctl daemon-reload
sudo systemctl enable ramboq_dev.service
sudo systemctl start ramboq_dev.service
```

### 6. Add sudoers permission for dev service

```bash
sudo visudo
```

Find the existing `www-data` line and add `ramboq_dev.service` alongside `ramboq.service`:
```
www-data ALL=NOPASSWD: /bin/systemctl restart ramboq.service, /bin/systemctl restart ramboq_dev.service
```

### 7. Enable the nginx dev site

> Ensure the default nginx site is **not** in `sites-enabled` — it will intercept all requests and show the nginx default page. See prod Step 5.

```bash
sudo cp /opt/ramboq_dev/etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-available/dev.ramboq.com
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-enabled/dev.ramboq.com
sudo nginx -t && sudo systemctl reload nginx
```

### 8. SSL certificate for dev.ramboq.com

The `dev` DNS record must be **grey cloud (DNS only)** in Cloudflare — certbot's HTTP challenge fails if proxied.

```bash
# Confirm DNS resolves to your server IP before proceeding
dig +short dev.ramboq.com

# Issue the cert
sudo certbot --nginx -d dev.ramboq.com
```

### 9. Push to trigger the first deploy

From your local machine:
```bash
git push origin dev
```

### 10. Verify

```bash
tail -f /opt/ramboq_dev/.log/hook_debug.log   # dev deploy log
tail -f /opt/ramboq_dev/.log/error_file        # dev app log
sudo ss -tlnp | grep 8503                      # confirm port 8503 is up
```

Then visit **https://dev.ramboq.com**.

---

## Deployment Flow

Every `git push` event triggers webhook validation. Branch routing:

| Branch | Deploys to | Domain | Port |
|---|---|---|---|
| `main` | `/opt/ramboq` | ramboq.com | 8502 |
| any non-`main` | `/opt/ramboq_dev` | dev.ramboq.com | 8503 |

The deploy script checks out whichever branch was pushed in `/opt/ramboq_dev`, so the last push always wins. There is no isolation between non-main branches — they share one dev directory and one dev service.

### End-to-End Flow

```
Developer (local)
    │
    │  git push origin <branch>
    ▼
GitHub
    │  POST https://ramboq.com/hooks/update
    │  Headers:
    │    X-GitHub-Event: push
    │    X-Hub-Signature-256: sha256=<HMAC of payload>
    │  Payload:
    │    ref: refs/heads/<branch>
    │    repository.name: ramboq
    ▼
Nginx (port 443, ramboq.com)
    │  location /hooks/update {
    │      proxy_pass http://127.0.0.1:9001/hooks/ramboq-deploy;
    │      proxy_set_header X-Hub-Signature-256 ...;
    │  }
    ▼
webhook listener (port 9001, www-data)
    │  Validates ALL trigger rules in hooks.json:
    │    1. X-GitHub-Event header == "push"
    │    2. payload.repository.name == "ramboq"
    │    3. HMAC SHA256 signature matches secret
    │
    │  If all pass → executes deploy.sh with payload ref as argument
    ▼
deploy.sh (runs as www-data)
    │
    ├── if branch == main:
    │     APP_ROOT=/opt/ramboq
    │     APP_SERVICE=ramboq.service
    │     sync etc/ and var/www/html to system paths
    │
    └── else (any non-main branch):
          APP_ROOT=/opt/ramboq_dev
          APP_SERVICE=ramboq_dev.service
          no /etc or /var sync
    │
    ├── cd APP_ROOT
    ├── git config safe.directory
    ├── PREV_HEAD = current commit hash
    ├── git fetch/checkout/pull origin <branch>
    ├── CHANGED = git diff --name-only PREV_HEAD HEAD
    │
    ├── source venv/bin/activate
    ├── pip install -r requirements.txt
    └── systemctl restart APP_SERVICE
    ▼
ramboq.service or ramboq_dev.service
    Streamlit restarts on port 8502 (prod) or 8503 (dev)
    ▼
Nginx proxies ramboq.com → localhost:8502 and dev.ramboq.com → localhost:8503
    ▼
Target environment updated ✅
```

### Webhook Secret

The GitHub webhook and `hooks.json` share a secret for HMAC-SHA256 signature validation:
- Set the secret in **GitHub → repo → Settings → Webhooks → Secret**
- The same secret must be in `webhook/hooks.json` under `payload-hash-sha256.secret`
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
| `hook.log` | `ramboq_hook.service` | Webhook listener stdout (shared — covers all branches) |
| `hook.err` | `ramboq_hook.service` | Webhook listener stderr (shared) |
| `incoming_requests.log` | `log-request.sh` | Requests hitting `/hooks/log` |
| `error_file` | `ramboq.service` | Streamlit full error log |
| `short_error_file` | `ramboq.service` | Streamlit recent errors |
| `log_file` | `ramboq_logger.py` | Python app full log |
| `short_log_file` | `ramboq_logger.py` | Python app recent log |

**Dev — `/opt/ramboq_dev/.log/`**

| File | Written by | Contents |
|---|---|---|
| `hook_debug.log` | `deploy.sh` | Full deploy output for every non-main push |
| `error_file` | `ramboq_dev.service` | Streamlit full error log |
| `short_error_file` | `ramboq_dev.service` | Streamlit recent errors |
| `log_file` | `ramboq_logger.py` | Python app full log |
| `short_log_file` | `ramboq_logger.py` | Python app recent log |

### Debug Endpoints

| URL | Purpose |
|---|---|
| `https://ramboq.com/hooks/update` | GitHub webhook endpoint (POST only) |
| `https://ramboq.com/hooks/log` | Manual request logger — triggers `log-request.sh` |
| `https://dev.ramboq.com` | Dev website served from `/opt/ramboq_dev` |

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
tail -50 /opt/ramboq/.log/hook.err
tail -50 /opt/ramboq/.log/incoming_requests.log
```

**Deploy triggered but app not updated**
```bash
# Prod — see exactly what deploy.sh did
tail -100 /opt/ramboq/.log/hook_debug.log

# Dev — see exactly what deploy.sh did
tail -100 /opt/ramboq_dev/.log/hook_debug.log

# Check the service restarted
sudo systemctl status ramboq.service       # prod
sudo systemctl status ramboq_dev.service   # dev
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

## Security Notes

- `setup/yaml/secrets.yaml` — contains SMTP and broker credentials, **gitignored**, hand-place on server only
- `setup/yaml/ramboq_deploy.yaml` — prod config flags, **gitignored**
- `var/www/.ssh/` — SSH keys, **gitignored**, never commit
- The webhook secret in `hooks.json` should be rotated periodically and kept in sync with the GitHub webhook settings
- Port `9001` (webhook listener) is not directly exposed — only accessible via nginx proxy

