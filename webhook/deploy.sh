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

  # One-time migration: rename old config file names to new names
  [ -f "setup/yaml/config.yaml" ] && [ ! -f "setup/yaml/backend_config.yaml" ] && \
    mv "setup/yaml/config.yaml" "setup/yaml/backend_config.yaml" && \
    echo "[$TS] Migrated config.yaml → backend_config.yaml"
  [ -f "setup/yaml/ramboq_config.yaml" ] && [ ! -f "setup/yaml/frontend_config.yaml" ] && \
    mv "setup/yaml/ramboq_config.yaml" "setup/yaml/frontend_config.yaml" && \
    echo "[$TS] Migrated ramboq_config.yaml → frontend_config.yaml"
  [ -f "setup/yaml/ramboq_constants.yaml" ] && [ ! -f "setup/yaml/constants.yaml" ] && \
    mv "setup/yaml/ramboq_constants.yaml" "setup/yaml/constants.yaml" && \
    echo "[$TS] Migrated ramboq_constants.yaml → constants.yaml"

  # Save server-specific backend_config.yaml flags before git pull overwrites it
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "setup/yaml/backend_config.yaml" ] && cp "setup/yaml/backend_config.yaml" "$CONFIG_BAK"

  # Reset backend_config.yaml to git-tracked version so pull proceeds cleanly
  git checkout -- setup/yaml/backend_config.yaml 2>/dev/null || true

  PREV_HEAD=$(git rev-parse HEAD)
  git pull origin main
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)

  # Merge: keep new repo config as base (picks up any new fields), overlay only
  # env-specific flags from the server's saved config so they survive deploys.
  if [ -f "$CONFIG_BAK" ]; then
    for key in enforce_password_standard cap_in_dev genai telegram mail notify_on_startup; do
      val=$(grep "^${key}:" "$CONFIG_BAK" | head -1 | sed "s/^${key}:[[:space:]]*//" )
      [ -n "$val" ] && sed -i "s/^${key}:.*/${key}: ${val}/" "setup/yaml/backend_config.yaml"
    done
    rm -f "$CONFIG_BAK"
  fi

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

  # Copy custom favicon and index.html into Streamlit static folder (survives pip upgrades)
  STREAMLIT_STATIC=$(python -c "import streamlit; import os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static'))")
  cp "$APP_ROOT/setup/images/favicon.png" "$STREAMLIT_STATIC/favicon.png"
  cp "$APP_ROOT/setup/streamlit/index.html" "$STREAMLIT_STATIC/index.html"

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Sending startup notification..."
  python "$APP_ROOT/webhook/notify_deploy.py" \
    && echo "[$TS] Startup notification done" \
    || echo "[$TS] WARNING: startup notification failed"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
