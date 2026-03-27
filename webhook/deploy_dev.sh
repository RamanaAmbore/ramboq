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

  PREV_HEAD=$(git rev-parse HEAD)
  git fetch origin "$BRANCH"
  git checkout -B "$BRANCH" "origin/$BRANCH"
  git pull origin "$BRANCH"
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)
  echo "[$TS] Changed files:"
  echo "$CHANGED"

  source venv/bin/activate
  pip install --no-cache-dir -r requirements.txt

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
