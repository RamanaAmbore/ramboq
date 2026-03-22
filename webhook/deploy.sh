#!/bin/bash

LOG="/opt/ramboq/.log/hook_debug.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www


{
  echo "[$TS] Webhook triggered"
  echo "[$TS] Current environment: $(env | grep GITHUB || echo 'No GitHub headers found')"
  echo "[$TS] Executing deploy steps..."

  echo "Running as: $(whoami)"

  cd /opt/ramboq || { echo "[$TS] Failed to cd into /opt/ramboq"; exit 1; }

  # Check if .git exists
  if [ -d .git ]; then
    # Use repo-level config so it doesn't rely on global write access
    git --git-dir=/opt/ramboq/.git --work-tree=/opt/ramboq config --add safe.directory /opt/ramboq

    # Record the current HEAD before pulling
    PREV_HEAD=$(git rev-parse HEAD)

    # Pull the latest code
    git --git-dir=.git --work-tree=. pull origin main

    # Detect changed files since last deploy
    CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)
    echo "[$TS] Changed files:"
    echo "$CHANGED"

    # --- Sync /etc if nginx configs changed ---
    if echo "$CHANGED" | grep -q '^etc/'; then
      echo "[$TS] Detected changes in etc/ — copying to /etc/"
      sudo cp -r /opt/ramboq/etc/nginx/sites-available/. /etc/nginx/sites-available/
      echo "[$TS] Testing nginx config..."
      if sudo nginx -t; then
        echo "[$TS] Reloading nginx..."
        sudo systemctl reload nginx
      else
        echo "[$TS] ❌ nginx config test failed — not reloading"
      fi
    fi

    # --- Sync /var/www/html if static files changed ---
    if echo "$CHANGED" | grep -q '^var/www/html/'; then
      echo "[$TS] Detected changes in var/www/html/ — copying to /var/www/html/"
      sudo cp -r /opt/ramboq/var/www/html/. /var/www/html/
    fi

  else
    echo "[$TS] ❌ Not a Git directory: .git missing in /opt/ramboq"
  fi

  # Activate virtualenv
  if [ -f venv/bin/activate ]; then
    source venv/bin/activate
    # Use pip safely in script
    pip install --no-cache-dir -r requirements.txt
  else
    echo "[$TS] Virtualenv not found at venv/bin/activate"
  fi

  #cp /opt/ramboq/index.html /opt/ramboq/venv/lib/python3.13/site-packages/streamlit/static/index.html
  #cp /opt/ramboq/setup/images/favicon.png /opt/ramboq/venv/lib/python3.13/site-packages/streamlit/static/favicon.png

  # Restart app service
  echo "[$TS] Attempting to restart ramboq.service..."
  sudo systemctl restart ramboq.service || echo "[$TS] Failed to restart ramboq.service"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
