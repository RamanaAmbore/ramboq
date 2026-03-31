#!/bin/bash
# Dev deploy script — triggered for all non-main, non-pod/* branch pushes.
# Called by hooks.json deploy-dev hook from /opt/ramboq_dev/webhook/deploy_dev.sh.

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

APP_ROOT="/opt/ramboq_dev"
APP_SERVICE="ramboq_dev.service"
LOG="$APP_ROOT/.log/hook_debug.log"
REF="${1:-refs/heads/dev}"
BRANCH="${REF#refs/heads/}"

{
  echo "[$TS] Deploy triggered: dev (branch: $BRANCH)"
  echo "Running as: $(whoami)"

  cd "$APP_ROOT" || { echo "[$TS] ERROR: cannot cd to $APP_ROOT"; exit 1; }

  git --git-dir="$APP_ROOT/.git" --work-tree="$APP_ROOT" config --add safe.directory "$APP_ROOT"

  # Save server-specific config.yaml flags before git checkout overwrites it
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "setup/yaml/config.yaml" ] && cp "setup/yaml/config.yaml" "$CONFIG_BAK"

  # Reset config.yaml to git-tracked version so checkout proceeds cleanly
  git checkout -- setup/yaml/config.yaml

  PREV_HEAD=$(git rev-parse HEAD)
  git fetch origin "$BRANCH"
  git checkout -B "$BRANCH" "origin/$BRANCH"
  git pull origin "$BRANCH"
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)

  # Merge: keep new repo config as base (picks up any new fields), overlay only
  # env-specific flags from the server's saved config so they survive deploys.
  if [ -f "$CONFIG_BAK" ]; then
    for key in prod mail perplexity enforce_password_standard prod_test_in_dev; do
      val=$(grep "^${key}:" "$CONFIG_BAK" | head -1 | sed "s/^${key}:[[:space:]]*//" )
      [ -n "$val" ] && sed -i "s/^${key}:.*/${key}: ${val}/" "setup/yaml/config.yaml"
    done
    rm -f "$CONFIG_BAK"
  fi

  echo "[$TS] Changed files:"
  echo "$CHANGED"

  source venv/bin/activate
  pip install --no-cache-dir -r requirements.txt

  # Copy custom favicon and index.html into Streamlit static folder (survives pip upgrades)
  STREAMLIT_STATIC=$(python -c "import streamlit; import os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static'))")
  cp "$APP_ROOT/setup/images/favicon.png" "$STREAMLIT_STATIC/favicon.png"
  cp "$APP_ROOT/setup/streamlit/index.html" "$STREAMLIT_STATIC/index.html"

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
