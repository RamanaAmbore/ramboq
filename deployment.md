⚙️ Secure GitHub Webhook Deployment for ramboq.com: A Complete Guide with Nginx, systemd, and Cloudflare
This tutorial explains how to automate deployments from GitHub using signed webhooks, served via Nginx with SSL (via Certbot), integrated with Cloudflare DNS and reverse proxying. Services are orchestrated with systemd, and deploy logic is modularized inside /webhook.

🧭 Architecture Overview
Developer → GitHub → Webhook (HMAC signed)
             ↓
       Cloudflare DNS & Proxy
             ↓
           Nginx
       /hooks/update ↘
                    Webhook listener → deploy.sh → Restart app
             /
        Streamlit app (/)



📁 Directory Structure
/opt/ramboq/
├── src/
├── setup/
├── .venv/
├── .log/
│   ├── hook.log
│   ├── hook.err
│   ├── hook_debug.log
│   └── reload_services.log
├── webhook/
│   ├── hooks.json
│   ├── deploy.sh
│   └── services.sh



🔑 Step 1: SSH Setup for GitHub Access
sudo -u www-data ssh-keygen -t ed25519 -f /var/www/.ssh/id_ed25519 -N ""
# Add id_ed25519.pub to GitHub Deploy Keys (read/write)
sudo chown -R www-data:www-data /var/www/.ssh
chmod 700 /var/www/.ssh
chmod 600 /var/www/.ssh/id_ed25519
git remote set-url origin git@github.com:<your_user>/ramboq.git



🔐 Step 2: Generate Webhook Secret
openssl rand -hex 16


Save this secret securely. Use it in GitHub webhook config and inside hooks.json.

🔗 Step 3: GitHub Webhook Creation
In GitHub repo:
- Go to Settings → Webhooks → Add Webhook
- Payload URL: https://www.ramboq.com/hooks/update
- Content-Type: application/json
- Secret: (your secret from above)
- Event: ✅ Push only

🧬 Step 4: hooks.json (Webhook Trigger Rules)
[
  {
    "id": "ramboq-deploy",
    "execute-command": "/opt/ramboq/webhook/deploy.sh",
    "command-working-directory": "/opt/ramboq",
    "pass-environment-to-command": [
      {
        "source": "header",
        "name": "X-Hub-Signature-256",
        "envname": "HTTP_X_HUB_SIGNATURE_256"
      },
      {
        "source": "header",
        "name": "X-GitHub-Event",
        "envname": "HTTP_X_GITHUB_EVENT"
      }
    ],
    "trigger-rule": {
      "and": [
        {
          "match": {
            "type": "value",
            "value": "push",
            "parameter": {
              "source": "header",
              "name": "X-GitHub-Event"
            }
          }
        },
        {
          "match": {
            "type": "value",
            "value": "refs/heads/main",
            "parameter": {
              "source": "payload",
              "name": "ref"
            }
          }
        },
        {
          "match": {
            "type": "payload-hmac-sha256",
            "parameter": {
              "source": "header",
              "name": "X-Hub-Signature-256"
            },
            "secret": "your_generated_secret_here"
          }
        }
      ]
    }
  }
]



🧾 Step 5: deploy.sh
#!/bin/bash

LOG="/opt/ramboq/.log/hook_debug.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

{
  echo "[$TS] Deploy triggered"
  env | grep '^HTTP_' || echo "No HTTP headers found"
  cat
  echo "[$TS] Signature: $HTTP_X_HUB_SIGNATURE_256"

  cd /opt/ramboq || exit 1
  git config --add safe.directory /opt/ramboq
  git pull origin main

  source .venv/bin/activate
  pip install --no-cache-dir -r requirements.txt

  sudo systemctl restart ramboq.service || echo "Restart failed"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1



🔁 Step 6: services.sh
#!/bin/bash

LOG_FILE="/opt/ramboq/.log/reload_services.log"
TS=$(date +"%Y-%m-%d %H:%M:%S")

echo "[$TS] Reloading services..." | tee -a $LOG_FILE

sudo systemctl daemon-reexec
sudo systemctl daemon-reload

if sudo nginx -t; then
  sudo systemctl reload nginx
else
  echo "Nginx test failed" | tee -a $LOG_FILE
fi

sudo systemctl restart ramboq_hook.service
sudo systemctl restart ramboq.service

echo "[$TS] Reload complete." | tee -a $LOG_FILE



⚙️ Step 7: Systemd Services
These should be saved in /etc/systemd/system/

ramboq.service
[Unit]
Description=Streamlit App for ramboq.com
After=network.target

[Service]
WorkingDirectory=/opt/ramboq
ExecStart=/bin/bash -c 'source /opt/ramboq/.venv/bin/activate && streamlit run app.py --server.port=8502 --server.address=0.0.0.0'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target


ramboq_hook.service
[Unit]
Description=Webhook Listener for ramboq.com
After=network.target

[Service]
ExecStart=/usr/bin/webhook -hooks /opt/ramboq/webhook/hooks.json -port 9001 -verbose
StandardOutput=append:/opt/ramboq/.log/hook.log
StandardError=append:/opt/ramboq/.log/hook.err
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target



🌐 Step 8: Nginx Setup
Create /etc/nginx/sites-available/ramboq.com:
server {
    server_name ramboq.com www.ramboq.com localhost;

    location / {
        proxy_pass http://localhost:8502;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    location /hooks/update {
        proxy_pass http://127.0.0.1:9001/hooks/ramboq-deploy;
        proxy_http_version 1.1;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/ramboq.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ramboq.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    listen 80;
    server_name ramboq.com www.ramboq.com localhost;

    if ($host = www.ramboq.com) {
        return 301 https://$host$request_uri;
    }

    if ($host = ramboq.com) {
        return 301 https://$host$request_uri;
    }

    return 404;
}


Enable with:
sudo ln -s /etc/nginx/sites-available/ramboq.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx



🔐 Step 9: Certbot SSL Setup
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d ramboq.com -d www.ramboq.com
sudo certbot renew --dry-run



☁️ Step 10: Cloudflare Setup
- Add DNS A records for ramboq.com and www.ramboq.com pointing to server IP
- Proxy traffic (orange cloud) to enable caching, DDoS mitigation
- SSL Mode: Full (Strict)
- Optionally restrict traffic to only Cloudflare IP ranges in Nginx

🐳 Step 11: Docker (Planned)
Some components may be containerized in future. You'll write a separate Docker tutorial covering:
- App containerization
