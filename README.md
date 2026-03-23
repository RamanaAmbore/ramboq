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

### 4. Hand-Place Secret Config Files

These files are gitignored and must be created manually on the server:

```bash
mkdir -p /opt/ramboq/setup/yaml
mkdir -p /opt/ramboq/.log

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

Paste in:
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

Copy configs and create symlink:
```bash
sudo cp /opt/ramboq/etc/nginx/sites-available/ramboq.com /etc/nginx/sites-available/ramboq.com
sudo cp /opt/ramboq/etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-available/dev.ramboq.com
sudo cp /opt/ramboq/etc/nginx/sites-available/default /etc/nginx/sites-available/default

# Remove default enabled site if present
sudo rm -f /etc/nginx/sites-enabled/default

# Symlink ramboq.com
sudo ln -sf /etc/nginx/sites-available/ramboq.com /etc/nginx/sites-enabled/ramboq.com
sudo ln -sf /etc/nginx/sites-available/dev.ramboq.com /etc/nginx/sites-enabled/dev.ramboq.com

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

Install service files:
```bash
sudo cp /opt/ramboq/webhook/ramboq.service /etc/systemd/system/ramboq.service
sudo cp /opt/ramboq/webhook/ramboq_dev.service /etc/systemd/system/ramboq_dev.service
sudo cp /opt/ramboq/webhook/ramboq_hook.service /etc/systemd/system/ramboq_hook.service
```

Make deploy scripts executable:
```bash
chmod +x /opt/ramboq/webhook/deploy.sh
chmod +x /opt/ramboq/webhook/log-request.sh
chmod +x /opt/ramboq/webhook/services.sh
```

Reload systemd and enable services to start on boot:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ramboq.service
sudo systemctl enable ramboq_dev.service
sudo systemctl enable ramboq_hook.service
```

Start services:
```bash
sudo systemctl start ramboq.service
sudo systemctl start ramboq_dev.service
sudo systemctl start ramboq_hook.service
```

Verify both are running:
```bash
sudo systemctl status ramboq.service
sudo systemctl status ramboq_dev.service
sudo systemctl status ramboq_hook.service

# Confirm ports are open
ss -tlnp | grep -E '8502|8503|9001'
```

Expected output:
```
LISTEN  0  511  0.0.0.0:8502  ...  streamlit
LISTEN  0  511  0.0.0.0:8503  ...  streamlit
LISTEN  0  511  0.0.0.0:9001  ...  webhook
```

### 8. sudoers for `www-data`

The webhook runs as `www-data` and needs passwordless sudo for specific commands. Open sudoers safely:
```bash
sudo visudo -f /etc/sudoers.d/www-data-ramboq
```

Add these lines:
```
www-data ALL=(ALL) NOPASSWD: /bin/cp
www-data ALL=(ALL) NOPASSWD: /usr/sbin/nginx
www-data ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_dev.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_hook.service
```

Save and verify:
```bash
sudo visudo -c
```

### 9. GitHub Webhook Setup

1. Go to **GitHub → repo → Settings → Webhooks → Add webhook**
2. Payload URL: `https://webhook.ramboq.com/hooks/update`
3. Content type: `application/json`
4. Secret: (must match `hooks.json` value under `payload-hash-sha256.secret`)
5. Events: select **Just the push event**
6. Active: checked
7. Save

### 10. Cloudflare DNS Setup (if using Cloudflare)

The main `ramboq.com` can stay proxied (orange cloud). The `webhook` subdomain **must be DNS-only** (grey cloud) to avoid Cloudflare intercepting webhook TLS and causing 502 errors:

1. In Cloudflare dashboard → **DNS → Records**
2. Add record:
     - Type: `A`
     - Name: `webhook`
     - IPv4: your server's public IP
     - Proxy status: **DNS only** (grey cloud)
3. Add record:
    - Type: `A`
    - Name: `dev`
    - IPv4: your server's public IP
    - Proxy status: DNS only (recommended while validating branch deploy)
4. Confirm `ramboq.com` and `www.ramboq.com` records remain orange (proxied) as desired

Verify `webhook` resolves to your origin (not Cloudflare):
```bash
dig +short webhook.ramboq.com
# Should return your server IP, NOT a Cloudflare IP (104.x.x.x range)
```

Verify `dev` resolves to your origin:
```bash
dig +short dev.ramboq.com
```

---

## Deployment Flow

Every `git push` event triggers webhook validation, but deployment is allowed only for `main` and `dev` branches.

- `main` deploys to `/opt/ramboq` and restarts `ramboq.service` (prod)
- `dev` deploys to `/opt/ramboq_dev` and restarts `ramboq_dev.service` (dev)
- Any other branch is logged and skipped (no deployment)

### End-to-End Flow

```
Developer (local)
    │
    │  git push origin main
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
    ├── if ref == refs/heads/main:
    │     APP_ROOT=/opt/ramboq
    │     APP_SERVICE=ramboq.service
    │     sync etc/ and var/www/html to system paths
    │
    ├── if ref == refs/heads/dev:
    │     APP_ROOT=/opt/ramboq_dev
    │     APP_SERVICE=ramboq_dev.service
    │     no /etc or /var sync
    │
    ├── else:
    │     log and exit 0 (skip deployment)
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

### Debug Endpoints

| URL | Purpose |
|---|---|
| `https://ramboq.com/hooks/update` | GitHub webhook endpoint (POST only) |
| `https://ramboq.com/hooks/log` | Manual request logger — triggers `log-request.sh` |
| `https://dev.ramboq.com` | Dev website served from `/opt/ramboq_dev` |

### Log Files (on prod server)

| File | Contents |
|---|---|
| `/opt/ramboq/.log/hook_debug.log` | Full deploy script output per run |
| `/opt/ramboq/.log/hook.log` | webhook listener stdout |
| `/opt/ramboq/.log/hook.err` | webhook listener stderr |
| `/opt/ramboq/.log/incoming_requests.log` | Requests to `/hooks/log` endpoint |
| `/opt/ramboq/.log/error_file` | Streamlit app errors (full) |
| `/opt/ramboq/.log/short_error_file` | Streamlit app errors (short) |

### Useful Commands (on prod server)

```bash
# Check service status
sudo systemctl status ramboq.service
sudo systemctl status ramboq_dev.service
sudo systemctl status ramboq_hook.service

# Tail deploy logs
tail -f /opt/ramboq/.log/hook_debug.log

# Manually trigger a deploy (simulate webhook locally)
cd /opt/ramboq && bash webhook/deploy.sh refs/heads/main
cd /opt/ramboq && bash webhook/deploy.sh refs/heads/dev

# Reload all services (nginx + webhook + app)
bash /opt/ramboq/webhook/services.sh

# Test nginx config
sudo nginx -t

# View recent Streamlit errors
tail -50 /opt/ramboq/.log/short_error_file
```

---

## Security Notes

- `setup/yaml/secrets.yaml` — contains SMTP and broker credentials, **gitignored**, hand-place on server only
- `setup/yaml/ramboq_deploy.yaml` — prod config flags, **gitignored**
- `var/www/.ssh/` — SSH keys, **gitignored**, never commit
- The webhook secret in `hooks.json` should be rotated periodically and kept in sync with the GitHub webhook settings
- Port `9001` (webhook listener) is not directly exposed — only accessible via nginx proxy

