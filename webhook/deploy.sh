#!/bin/bash
# Unified deploy script — handles prod, dev, and pod environments.
# Called by /etc/webhook/dispatch.sh with ENV and REF arguments.
# Usage: deploy.sh <ENV> <REF>
#   ENV : prod | dev | pod
#   REF : refs/heads/<branch>  (e.g. refs/heads/main)
#
# Phase 3: Streamlit removed. Services now run uvicorn (Litestar + SvelteKit SPA).
# The SvelteKit build (frontend/build/) is served as static files by Litestar.

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

ENV="${1:-prod}"
REF="${2:-refs/heads/main}"
BRANCH="${REF#refs/heads/}"

case "$ENV" in
  prod) APP_ROOT="/opt/ramboq";     APP_SERVICE="ramboq.service"     ;;
  dev)  APP_ROOT="/opt/ramboq_dev"; APP_SERVICE="ramboq_dev.service" ;;
  pod)  APP_ROOT="/opt/ramboq_pod"; APP_SERVICE="ramboq_pod.service" ;;
  *) echo "[$TS] ERROR: unknown ENV '$ENV'"; exit 1 ;;
esac

LOG="$APP_ROOT/.log/hook_debug.log"

{
  echo "[$TS] Deploy triggered: $ENV (branch: $BRANCH)"
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

  # Save server-specific backend_config.yaml flags before git operations overwrite it
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "setup/yaml/backend_config.yaml" ] && cp "setup/yaml/backend_config.yaml" "$CONFIG_BAK"

  # Reset backend_config.yaml to git-tracked version so git operations proceed cleanly
  git checkout -- setup/yaml/backend_config.yaml 2>/dev/null || true

  # --- Git update ---
  PREV_HEAD=$(git rev-parse HEAD)
  if [ "$ENV" = "prod" ]; then
    git pull origin main
  else
    git fetch origin "$BRANCH"
    git checkout -B "$BRANCH" "origin/$BRANCH"
    git pull origin "$BRANCH"
  fi
  CHANGED=$(git diff --name-only "$PREV_HEAD" HEAD)

  # --- Restore / merge server-specific config flags ---
  if [ "$ENV" = "pod" ]; then
    [ -f "$CONFIG_BAK" ] && mv "$CONFIG_BAK" "setup/yaml/backend_config.yaml"
  else
    if [ -f "$CONFIG_BAK" ]; then
      for key in enforce_password_standard cap_in_dev genai telegram mail notify_on_startup; do
        val=$(grep "^${key}:" "$CONFIG_BAK" | head -1 | sed "s/^${key}:[[:space:]]*//" )
        [ -n "$val" ] && sed -i "s/^${key}:.*/${key}: ${val}/" "setup/yaml/backend_config.yaml"
      done
      rm -f "$CONFIG_BAK"
    fi
  fi

  # Write current branch into config
  if grep -q "^deploy_branch:" "setup/yaml/backend_config.yaml" 2>/dev/null; then
    sed -i "s/^deploy_branch:.*/deploy_branch: ${BRANCH}/" "setup/yaml/backend_config.yaml"
  else
    echo "deploy_branch: ${BRANCH}" >> "setup/yaml/backend_config.yaml"
  fi

  echo "[$TS] Changed files:"
  echo "$CHANGED"

  # --- Prod-only: sync nginx configs ---
  if [ "$ENV" = "prod" ]; then
    if echo "$CHANGED" | grep -q '^etc/'; then
      echo "[$TS] Syncing nginx configs..."
      sudo cp -r "$APP_ROOT/etc/nginx/sites-available/." /etc/nginx/sites-available/
      if sudo nginx -t; then
        sudo systemctl reload nginx
      else
        echo "[$TS] ERROR: nginx config test failed — not reloading"
      fi
    fi
  fi

  # --- Pod: build Podman image ---
  if [ "$ENV" = "pod" ]; then
    echo "[$TS] Building Podman image ramboq-pod:latest..."
    sudo podman build -t ramboq-pod:latest "$APP_ROOT" \
      && echo "[$TS] Podman image built successfully" \
      || { echo "[$TS] ERROR: Podman image build failed"; exit 1; }
  fi

  # --- Prod / dev: install Python deps + build SvelteKit frontend ---
  if [ "$ENV" != "pod" ]; then
    source venv/bin/activate

    # Install Python dependencies (API layer only — no Streamlit)
    pip install --no-cache-dir -r requirements-api.txt \
      && echo "[$TS] Python deps installed" \
      || { echo "[$TS] ERROR: pip install failed"; exit 1; }

    # Build SvelteKit frontend (only if frontend files changed or build doesn't exist)
    if echo "$CHANGED" | grep -q '^frontend/' || [ ! -d "$APP_ROOT/frontend/build" ]; then
      echo "[$TS] Building SvelteKit frontend..."
      cd "$APP_ROOT/frontend"
      npm ci --prefer-offline 2>&1 | tail -5
      npm run build \
        && echo "[$TS] SvelteKit build complete" \
        || { echo "[$TS] ERROR: SvelteKit build failed"; exit 1; }
      cd "$APP_ROOT"
    else
      echo "[$TS] No frontend changes — skipping SvelteKit build"
    fi
  fi

  echo "[$TS] Restarting $APP_SERVICE..."
  sudo systemctl restart "$APP_SERVICE" || echo "[$TS] ERROR: failed to restart $APP_SERVICE"

  echo "[$TS] Sending startup notification..."
  if [ "$ENV" = "pod" ]; then
    sleep 5
    sudo podman exec ramboq-pod-app python /app/webhook/notify_deploy.py \
      && echo "[$TS] Startup notification done" \
      || echo "[$TS] WARNING: startup notification failed"
  else
    python "$APP_ROOT/webhook/notify_deploy.py" \
      && echo "[$TS] Startup notification done" \
      || echo "[$TS] WARNING: startup notification failed"
  fi

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
