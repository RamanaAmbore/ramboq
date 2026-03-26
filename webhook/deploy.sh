#!/bin/bash

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

REF="${1:-refs/heads/main}"
BRANCH="${REF#refs/heads/}"

if [ "$BRANCH" = "main" ]; then
  APP_ROOT="/opt/ramboq"
  APP_SERVICE="ramboq.service"
  LOG="/opt/ramboq/.log/hook_debug.log"
  SYNC_SYSTEM_PATHS="true"
else
  APP_ROOT="/opt/ramboq_dev"
  APP_SERVICE="ramboq_dev.service"
  LOG="/opt/ramboq_dev/.log/hook_debug.log"
  SYNC_SYSTEM_PATHS="false"
fi


{
  echo "[$TS] Webhook triggered"
  echo "[$TS] Git ref: $REF"
  echo "[$TS] Branch: $BRANCH"
  echo "[$TS] App root: $APP_ROOT"
  echo "[$TS] App service: $APP_SERVICE"
  echo "[$TS] Current environment: $(env | grep GITHUB || echo 'No GitHub headers found')"
  echo "[$TS] Executing deploy steps..."

  echo "Running as: $(whoami)"

  cd "$APP_ROOT" || { echo "[$TS] Failed to cd into $APP_ROOT"; exit 1; }

  # Check if .git exists
  if [ -d .git ]; then
    # Use repo-level config so it doesn't rely on global write access
    git --git-dir="$APP_ROOT/.git" --work-tree="$APP_ROOT" config --add safe.directory "$APP_ROOT"

    # Record the current HEAD before pulling
    PREV_HEAD=$(git rev-parse HEAD)

    # Pull the latest code
    git --git-dir=.git --work-tree=. fetch origin "$BRANCH"
    git --git-dir=.git --work-tree=. checkout -B "$BRANCH" "origin/$BRANCH"
    git --git-dir=.git --work-tree=. pull origin "$BRANCH"

    # Detect changed files since last deploy
    CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)
    echo "[$TS] Changed files:"
    echo "$CHANGED"

    if [ "$SYNC_SYSTEM_PATHS" = "true" ]; then
      # --- Sync /etc if nginx configs changed (prod only) ---
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

      # --- Sync /var/www/html if static files changed (prod only) ---
      if echo "$CHANGED" | grep -q '^var/www/html/'; then
        echo "[$TS] Detected changes in var/www/html/ — copying to /var/www/html/"
        sudo cp -r /opt/ramboq/var/www/html/. /var/www/html/
      fi
    fi

  else
    echo "[$TS] ❌ Not a Git directory: .git missing in $APP_ROOT"
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
  echo "[$TS] Attempting to restart $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] Failed to restart $APP_SERVICE"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
