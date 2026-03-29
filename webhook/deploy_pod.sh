#!/bin/bash
# Pod deploy script — triggered for all pod/* branch pushes.
# Called by hooks.json deploy-pod hook from /opt/ramboq_pod/webhook/deploy_pod.sh.

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

APP_ROOT="/opt/ramboq_pod"
APP_SERVICE="ramboq_pod.service"
LOG="$APP_ROOT/.log/hook_debug.log"
REF="${1:-refs/heads/pod/main}"
BRANCH="${REF#refs/heads/}"

{
  echo "[$TS] Deploy triggered: pod (branch: $BRANCH)"
  echo "Running as: $(whoami)"

  cd "$APP_ROOT" || { echo "[$TS] ERROR: cannot cd to $APP_ROOT"; exit 1; }

  git --git-dir="$APP_ROOT/.git" --work-tree="$APP_ROOT" config --add safe.directory "$APP_ROOT"

  # Preserve server-specific config.yaml (prod/mail/perplexity flags) across git checkout
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "setup/yaml/config.yaml" ] && cp "setup/yaml/config.yaml" "$CONFIG_BAK"

  # Reset config.yaml to git-tracked version so checkout proceeds cleanly
  git checkout -- setup/yaml/config.yaml

  PREV_HEAD=$(git rev-parse HEAD)
  git fetch origin "$BRANCH"
  git checkout -B "$BRANCH" "origin/$BRANCH"
  git pull origin "$BRANCH"
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)

  # Restore server-specific config.yaml
  [ -f "$CONFIG_BAK" ] && mv "$CONFIG_BAK" "setup/yaml/config.yaml"

  echo "[$TS] Changed files:"
  echo "$CHANGED"

  echo "[$TS] Building Podman image ramboq-pod:latest..."
  sudo podman build -t ramboq-pod:latest "$APP_ROOT" \
    && echo "[$TS] Podman image built successfully" \
    || { echo "[$TS] ERROR: Podman image build failed"; exit 1; }

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
