#!/bin/bash
# Prod deploy script — triggered only for pushes to main.
# Called by hooks.json deploy-prod hook from /opt/ramboq/webhook/deploy.sh.

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

APP_ROOT="/opt/ramboq"
APP_SERVICE="ramboq.service"
LOG="$APP_ROOT/.log/hook_debug.log"

{
  echo "[$TS] Deploy triggered: prod (main)"
  echo "Running as: $(whoami)"

  cd "$APP_ROOT" || { echo "[$TS] ERROR: cannot cd to $APP_ROOT"; exit 1; }

  git --git-dir="$APP_ROOT/.git" --work-tree="$APP_ROOT" config --add safe.directory "$APP_ROOT"

  # Preserve server-specific config.yaml (prod/mail/perplexity flags) across git pull
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "setup/yaml/config.yaml" ] && cp "setup/yaml/config.yaml" "$CONFIG_BAK"

  PREV_HEAD=$(git rev-parse HEAD)
  git pull origin main
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)

  # Restore server-specific config.yaml
  [ -f "$CONFIG_BAK" ] && mv "$CONFIG_BAK" "setup/yaml/config.yaml"

  echo "[$TS] Changed files:"
  echo "$CHANGED"

  if echo "$CHANGED" | grep -q '^etc/'; then
    echo "[$TS] Syncing nginx configs..."
    sudo cp -r "$APP_ROOT/etc/nginx/sites-available/." /etc/nginx/sites-available/
    if sudo nginx -t; then
      sudo systemctl reload nginx
    else
      echo "[$TS] ERROR: nginx config test failed — not reloading"
    fi
  fi

  if echo "$CHANGED" | grep -q '^var/www/html/'; then
    echo "[$TS] Syncing static files..."
    sudo cp -r "$APP_ROOT/var/www/html/." /var/www/html/
  fi

  source venv/bin/activate
  pip install --no-cache-dir -r requirements.txt

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
