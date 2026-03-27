# Podman Deployment — pod.ramboq.com

This document covers the one-time server setup and the ongoing deploy workflow for the containerised environment at `pod.ramboq.com`.

---

## Architecture

```
GitHub push (pod/* branch)
        │
        ▼
GitHub Webhook → webhook.ramboq.com (port 9001)
        │
        ▼
/etc/webhook/hooks.json          ← independent system config
        │  deploy-pod hook matches refs/heads/pod/*
        ▼
/opt/ramboq_pod/webhook/deploy_pod.sh
        │
        ▼
git pull → /opt/ramboq_pod       ← pod branch code
        │
        ▼
sudo podman build -t ramboq-pod:latest
        │
        ▼
systemctl restart ramboq_pod.service
        │
        ▼
podman run -p 8504:8504          ← container
        │
        ▼
nginx (pod.ramboq.com → localhost:8504, SSL)
```

**Key directories on server**

| Path | Purpose |
|---|---|
| `/opt/ramboq_pod/` | Git working tree (pod branch) |
| `/opt/ramboq_pod/.log/` | Log files (volume-mounted into container at `/app/.log/`) |
| `/opt/ramboq_pod/setup/yaml/` | Config + secrets (volume-mounted into container at `/app/setup/yaml/`) |
| `/opt/ramboq_pod/setup/images/` | Static images (baked into image at build time) |
| `/etc/webhook/hooks.json` | Webhook routing config — independent of all deployments |

**Secrets are never baked into the image.** `setup/yaml/secrets.yaml` and `setup/yaml/ramboq_deploy.yaml` are volume-mounted read-only at runtime. The `Containerfile` explicitly deletes them if accidentally copied during build.

---

## One-time Server Setup

Run these steps once on a fresh server before the first push. Requires root or sudo access.

### Step 1 — Install Podman

```bash
sudo apt-get update && sudo apt-get install -y podman
podman --version   # verify
```

### Step 2 — Clone the repository

```bash
sudo git clone https://github.com/RamanaAmbore/ramboq.git /opt/ramboq_pod
sudo chown -R www-data:www-data /opt/ramboq_pod
```

### Step 3 — Checkout the pod branch

```bash
sudo git config --global --add safe.directory /opt/ramboq_pod
sudo git -C /opt/ramboq_pod fetch origin pod/<branch-name>
sudo git -C /opt/ramboq_pod checkout pod/<branch-name>
```

Replace `<branch-name>` with the active pod branch (e.g., `pod/main`).

### Step 4 — Create log directory and make deploy script executable

```bash
sudo mkdir -p /opt/ramboq_pod/.log
sudo chown -R www-data:www-data /opt/ramboq_pod/.log
sudo chmod +x /opt/ramboq_pod/webhook/deploy_pod.sh
```

### Step 5 — Place secrets (never committed to git)

Create `secrets.yaml` manually with the required credentials:

```bash
sudo tee /opt/ramboq_pod/setup/yaml/secrets.yaml <<'EOF'
# FILL IN REAL VALUES before starting the service
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQ Team
smtp_user: <your-email>
smtp_pass: <your-smtp-password>
kite_accounts:
    <USER_ID>:
        password: <password>
        totp_token: <totp>
        api_key: <api_key>
        api_secret: <api_secret>
cookie_secret: <random-strong-string>
kite_login_url: https://kite.zerodha.com/api/login
kite_twofa_url: https://kite.zerodha.com/api/twofa
pplx_api_key: <perplexity-api-key>
EOF
sudo chown www-data:www-data /opt/ramboq_pod/setup/yaml/secrets.yaml
sudo chmod 600 /opt/ramboq_pod/setup/yaml/secrets.yaml
```

### Step 6 — Create ramboq_deploy.yaml

Log paths must use `/app/.log/` (container-internal paths, mapped to `/opt/ramboq_pod/.log/` at runtime):

```bash
sudo tee /opt/ramboq_pod/setup/yaml/ramboq_deploy.yaml <<'EOF'
file_log_file: /app/.log/log_file
error_log_file: /app/.log/error_file
file_log_level: 10
error_log_level: 40
short_file_log_file: /app/.log/short_log_file
short_error_log_file: /app/.log/short_error_file
console_log_level: 40
prod: True
mail: False
perplexity: False
enforce_password_standard: False
EOF
sudo chown www-data:www-data /opt/ramboq_pod/setup/yaml/ramboq_deploy.yaml
```

> Note: set `perplexity: True` when ready to enable live Perplexity AI market reports.

### Step 7 — Install the systemd service

```bash
sudo cp /opt/ramboq_pod/webhook/ramboq_pod.service /etc/systemd/system/ramboq_pod.service
sudo systemctl daemon-reload
sudo systemctl enable ramboq_pod.service
```

### Step 8 — Add sudoers entries for www-data

The webhook listener runs as `www-data`. It needs passwordless sudo for podman build and service restarts:

```bash
sudo tee /etc/sudoers.d/ramboq <<'EOF'
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_dev.service
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart ramboq_pod.service
www-data ALL=(ALL) NOPASSWD: /bin/cp -r /opt/ramboq/etc/nginx/sites-available/. /etc/nginx/sites-available/
www-data ALL=(ALL) NOPASSWD: /bin/cp -r /opt/ramboq/var/www/html/. /var/www/html/
www-data ALL=(ALL) NOPASSWD: /usr/sbin/nginx
www-data ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
www-data ALL=(ALL) NOPASSWD: /usr/bin/podman build -t ramboq-pod\:latest *
EOF
```

### Step 9 — Deploy hooks.json and dispatch.sh

`hooks.json` and `dispatch.sh` live at `/etc/webhook/` — independent of all deployment directories. Copy from the pod repo and restart the listener:

```bash
sudo mkdir -p /etc/webhook
sudo cp /opt/ramboq_pod/webhook/hooks.json /etc/webhook/hooks.json
sudo cp /opt/ramboq_pod/webhook/dispatch.sh /etc/webhook/dispatch.sh
sudo chmod +x /etc/webhook/dispatch.sh
sudo systemctl restart ramboq_hook.service
```

> `dispatch.sh` is the single entry point called by the webhook listener. It reads the branch name from the git ref and routes to the correct environment's deploy script. After any change to either file, repeat the copy and restart.

### Step 10 — Configure nginx

Copy the nginx site config from the pod repo and enable it:

```bash
sudo cp /opt/ramboq_pod/etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-available/pod.ramboq.com
sudo ln -s /etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-enabled/pod.ramboq.com
sudo nginx -t && sudo systemctl reload nginx
```

### Step 11 — Obtain SSL certificate

Add `pod.ramboq.com` to the existing certificate. List current domains first so none are dropped:

```bash
sudo certbot certificates
sudo certbot --expand -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com -d pod.ramboq.com
```

### Step 12 — Cloudflare DNS

Add an A record for `pod.ramboq.com` pointing to the server IP. Set proxy status to **DNS only** (grey cloud) — Cloudflare proxying breaks Streamlit WebSocket connections.

### Step 13 — Initial build and start

```bash
sudo podman build -t ramboq-pod:latest /opt/ramboq_pod
sudo systemctl start ramboq_pod.service
sudo systemctl status ramboq_pod.service
```

---

## Ongoing Deploy Workflow

No manual steps are needed after the one-time setup. Every push to a `pod/*` branch triggers an automatic deploy:

```bash
git push origin pod/<branch-name>
```

**What happens automatically:**
1. GitHub sends a webhook to `webhook.ramboq.com`
2. `/etc/webhook/hooks.json` matches the `pod/*` branch via `deploy-pod` hook
3. `/opt/ramboq_pod/webhook/deploy_pod.sh` is called
4. Pulls latest code into `/opt/ramboq_pod`
5. Runs `sudo podman build -t ramboq-pod:latest /opt/ramboq_pod`
6. Restarts `ramboq_pod.service` with the new image
7. New container starts on port 8504

---

## Validation

After a deploy, verify each layer:

```bash
# 1. Deploy log
tail -50 /opt/ramboq_pod/.log/hook_debug.log

# 2. Image rebuilt
sudo podman images | grep ramboq-pod

# 3. Container running
sudo podman ps

# 4. Port listening
ss -tlnp | grep 8504

# 5. App logs (written inside container, visible via volume mount)
tail -50 /opt/ramboq_pod/.log/error_file

# 6. nginx and HTTPS
sudo nginx -t
curl -I https://pod.ramboq.com
```

---

## Key Files

| File | Server path | Purpose |
|---|---|---|
| `Containerfile` | `/opt/ramboq_pod/Containerfile` | Image build instructions |
| `.containerignore` | `/opt/ramboq_pod/.containerignore` | Files excluded from image build |
| `webhook/deploy_pod.sh` | `/opt/ramboq_pod/webhook/deploy_pod.sh` | Pod deploy script — self-contained, no cross-env references |
| `webhook/ramboq_pod.service` | `/etc/systemd/system/ramboq_pod.service` | systemd service — runs `podman run` on port 8504 |
| `webhook/hooks.json` | `/etc/webhook/hooks.json` | Webhook config — validates push event, HMAC; calls dispatch.sh |
| `webhook/dispatch.sh` | `/etc/webhook/dispatch.sh` | Routes branch to correct env deploy script |
| `etc/nginx/sites-available/pod.ramboq.com` | `/etc/nginx/sites-available/pod.ramboq.com` | nginx reverse proxy config |
| `setup/yaml/secrets.yaml` | `/opt/ramboq_pod/setup/yaml/secrets.yaml` | Kite API keys, SMTP, cookie secret — gitignored, server only |
| `setup/yaml/ramboq_deploy.yaml` | `/opt/ramboq_pod/setup/yaml/ramboq_deploy.yaml` | Log paths (must use `/app/.log/`), feature flags — gitignored, server only |

---

## Important Notes

- **Log paths in `ramboq_deploy.yaml` must use `/app/.log/`**, not `/opt/ramboq_pod/.log/`. The container sees `/app/.log/` internally; the host volume mount maps it to `/opt/ramboq_pod/.log/`.
- **`deploy_pod.sh` is self-contained** — it only operates on `/opt/ramboq_pod`. It has no reference to prod or dev directories. Pushing to `pod/*` never touches any other environment.
- **`hooks.json` and `dispatch.sh` live at `/etc/webhook/`** — not inside any deployment directory. After updating either file in the repo, copy manually: `sudo cp /opt/ramboq_pod/webhook/hooks.json /etc/webhook/hooks.json && sudo cp /opt/ramboq_pod/webhook/dispatch.sh /etc/webhook/dispatch.sh && sudo systemctl restart ramboq_hook.service`
- **Podman runs as root** (no `User=` in the service file). The image is stored in root's container storage. Always build with `sudo podman build`.
- **`pod.ramboq.com` must be grey cloud in Cloudflare** (DNS only). Orange cloud breaks Streamlit WebSocket connections.
- **Secrets survive deploys** because they are volume-mounted, not baked into the image. The `Containerfile` also explicitly removes them during build as a defence-in-depth measure.
