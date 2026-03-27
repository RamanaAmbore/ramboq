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
/opt/ramboq/webhook/deploy.sh   ← always read from prod
        │  detects pod/* prefix
        ▼
git pull → /opt/ramboq_pod      ← pod branch code
        │
        ▼
sudo podman build -t ramboq-pod:latest
        │
        ▼
systemctl restart ramboq_pod.service
        │
        ▼
podman run -p 8504:8504         ← container
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

**Secrets are never baked into the image.** `setup/yaml/secrets.yaml` and `setup/yaml/ramboq_deploy.yaml` are volume-mounted read-only at runtime. The `Containerfile` explicitly deletes them if accidentally copied.

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
sudo git -C /opt/ramboq_pod fetch origin pod/<branch-name>
sudo git -C /opt/ramboq_pod checkout pod/<branch-name>
```

Replace `<branch-name>` with the active pod branch (e.g., `pod/main`).

### Step 4 — Create log and image directories

```bash
sudo mkdir -p /opt/ramboq_pod/.log
sudo mkdir -p /opt/ramboq_pod/setup/images/testimonials
sudo chown -R www-data:www-data /opt/ramboq_pod/.log /opt/ramboq_pod/setup/images
```

### Step 5 — Place secrets (never committed to git)

Copy from prod or create manually:

```bash
sudo cp /opt/ramboq/setup/yaml/secrets.yaml /opt/ramboq_pod/setup/yaml/secrets.yaml
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
twilio_alert: ''
twilio_account_sid: ''
twilio_auth_token: ''
prod: True
mail: False
perplexity: False
enforce_password_standard: False
EOF
sudo chown www-data:www-data /opt/ramboq_pod/setup/yaml/ramboq_deploy.yaml
```

> Note: `prod: True` enables real Perplexity AI calls. Set `perplexity: True` separately when ready.

### Step 7 — Install the systemd service

```bash
sudo cp /opt/ramboq_pod/webhook/ramboq_pod.service /etc/systemd/system/ramboq_pod.service
sudo systemctl daemon-reload
sudo systemctl enable ramboq_pod.service
```

### Step 8 — Add sudoers entries for www-data

The webhook listener runs as `www-data`. It needs sudo for podman build and service restart:

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

### Step 9 — Configure nginx

Copy the nginx site config from the repo and enable it:

```bash
sudo cp /opt/ramboq/etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-available/pod.ramboq.com
sudo ln -s /etc/nginx/sites-available/pod.ramboq.com /etc/nginx/sites-enabled/pod.ramboq.com
sudo nginx -t && sudo systemctl reload nginx
```

### Step 10 — Obtain SSL certificate

`pod.ramboq.com` should be added to the existing `ramboq.com` certificate:

```bash
sudo certbot --expand -d ramboq.com -d www.ramboq.com -d webhook.ramboq.com -d dev.ramboq.com -d pod.ramboq.com
```

Check existing domains first so you do not drop any:

```bash
sudo certbot certificates
```

### Step 11 — Cloudflare DNS

Add an A record for `pod.ramboq.com` pointing to the server IP. Set proxy status to **DNS only** (grey cloud) — Cloudflare proxying breaks Streamlit WebSocket connections.

### Step 12 — Initial build and start

```bash
sudo podman build -t ramboq-pod:latest /opt/ramboq_pod
sudo systemctl start ramboq_pod.service
sudo systemctl status ramboq_pod.service
```

---

## Ongoing Deploy Workflow

No manual steps are needed after the one-time setup. Every push to a `pod/*` branch triggers an automatic deploy:

```
git push origin pod/<branch-name>
```

**What happens automatically:**
1. GitHub sends a webhook to `webhook.ramboq.com`
2. `deploy.sh` detects the `pod/` prefix in the branch name
3. Pulls latest code into `/opt/ramboq_pod`
4. Runs `sudo podman build -t ramboq-pod:latest /opt/ramboq_pod`
5. Restarts `ramboq_pod.service` with the new image
6. New container starts on port 8504

---

## Validation

After a deploy, verify each layer:

```bash
# 1. Image built
sudo podman images | grep ramboq-pod

# 2. Container running
sudo podman ps

# 3. Port listening
ss -tlnp | grep 8504

# 4. App logs (inside container, written to volume)
tail -50 /opt/ramboq_pod/.log/error_file

# 5. Deploy log
tail -50 /opt/ramboq_pod/.log/hook_debug.log

# 6. nginx
sudo nginx -t
curl -I https://pod.ramboq.com
```

---

## Key Files

| File | Location | Purpose |
|---|---|---|
| `Containerfile` | repo root | Image build instructions |
| `.containerignore` | repo root | Files excluded from image build (venv, secrets, logs) |
| `webhook/ramboq_pod.service` | repo | systemd service — runs `podman run` on port 8504 |
| `webhook/deploy.sh` | repo (read from `/opt/ramboq`) | Webhook handler — routes pod/* branches to podman build |
| `etc/nginx/sites-available/pod.ramboq.com` | repo | nginx reverse proxy config |
| `setup/yaml/secrets.yaml` | server only — gitignored | Kite API keys, SMTP, cookie secret |
| `setup/yaml/ramboq_deploy.yaml` | server only — gitignored | Log paths (must use `/app/.log/`), feature flags |

---

## Important Notes

- **Log paths in `ramboq_deploy.yaml` must use `/app/.log/`**, not `/opt/ramboq_pod/.log/`. The container sees `/app/.log/` internally; the host volume mount maps it to `/opt/ramboq_pod/.log/`.
- **`deploy.sh` is always read from `/opt/ramboq/webhook/deploy.sh`** (the prod directory). Changes to deploy.sh must be merged to `main` to take effect for all branch types including pod.
- **`hooks.json` is always read from `/opt/ramboq/webhook/hooks.json`**. Branch routing is handled inside `deploy.sh`, not in `hooks.json`.
- **Podman runs as root** (no `User=` in the service file). The image is stored in root's container storage. Always build with `sudo podman build`.
- **`pod.ramboq.com` must be grey cloud in Cloudflare** (DNS only). Orange cloud breaks Streamlit WebSocket connections.
- **Secrets survive deploys** because they are volume-mounted, not baked into the image. The `Containerfile` also explicitly removes them during build as a defence-in-depth measure.
