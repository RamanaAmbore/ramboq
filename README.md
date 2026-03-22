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
│       └── default                 # Nginx default site config
├── var/
│   └── www/html/                   # Static files served by nginx default site
├── webhook/
│   ├── hooks.json                  # Webhook trigger rules (GitHub event + SHA256)
│   ├── deploy.sh                   # Deployment script (pull, sync, restart)
│   ├── log-request.sh              # Incoming request logger
│   ├── ramboq.service              # systemd unit for the Streamlit app
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

The production server runs at `/opt/ramboq/` on a Linux server.

### systemd Services

**Streamlit app** — `webhook/ramboq.service` → copy to `/etc/systemd/system/`
```
ExecStart: streamlit run app.py --server.port=8502 --server.address=0.0.0.0
```

**Webhook listener** — `webhook/ramboq_hook.service` → copy to `/etc/systemd/system/`
```
ExecStart: /usr/bin/webhook -hooks /opt/ramboq/webhook/hooks.json -port 9001 -verbose
Runs as: www-data
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ramboq.service ramboq_hook.service
sudo systemctl start ramboq.service ramboq_hook.service
```

### Nginx

Copy configs from `etc/nginx/sites-available/` to `/etc/nginx/sites-available/`, then symlink:
```bash
sudo cp etc/nginx/sites-available/* /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/ramboq.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### sudoers for `www-data`

The deploy script runs as `www-data` and needs passwordless sudo for specific commands:
```
www-data ALL=(ALL) NOPASSWD: /bin/cp
www-data ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
www-data ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq.service
```

---

## Deployment Flow

Every `git push` to the `main` branch on GitHub triggers an **automatic deployment** to the production server via webhook.

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
    │    ref: refs/heads/main
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
    │    2. payload.ref == "refs/heads/main"
    │    3. payload.repository.name == "ramboq"
    │    4. HMAC SHA256 signature matches secret
    │
    │  If all pass → executes deploy.sh
    ▼
deploy.sh (runs as www-data)
    │
    ├── cd /opt/ramboq
    ├── git config safe.directory
    ├── PREV_HEAD = current commit hash
    ├── git pull origin main
    ├── CHANGED = git diff --name-only PREV_HEAD HEAD
    │
    ├── if etc/ files changed:
    │     cp etc/nginx/sites-available/ → /etc/nginx/sites-available/
    │     nginx -t → systemctl reload nginx
    │
    ├── if var/www/html/ files changed:
    │     cp var/www/html/ → /var/www/html/
    │
    ├── source venv/bin/activate
    ├── pip install -r requirements.txt
    └── systemctl restart ramboq.service
    ▼
ramboq.service
    Streamlit restarts on port 8502
    ▼
Nginx proxies ramboq.com → localhost:8502
    ▼
Live site updated ✅
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
sudo systemctl status ramboq_hook.service

# Tail deploy logs
tail -f /opt/ramboq/.log/hook_debug.log

# Manually trigger a deploy (simulate webhook locally)
cd /opt/ramboq && bash webhook/deploy.sh

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

