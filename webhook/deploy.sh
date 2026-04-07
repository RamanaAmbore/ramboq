#!/bin/bash
# Unified deploy script — handles prod and dev environments.
# Called by /etc/webhook/dispatch.sh with ENV and REF arguments.
# Usage: deploy.sh <ENV> <REF>
#   ENV : prod | dev
#   REF : refs/heads/<branch>  (e.g. refs/heads/main)
#
# Services run uvicorn (Litestar API) + SvelteKit SPA as static files.
# The SvelteKit build (frontend/build/) is served as static files by Litestar.

TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www

ENV="${1:-prod}"
REF="${2:-refs/heads/main}"
BRANCH="${REF#refs/heads/}"

case "$ENV" in
  prod) APP_ROOT="/opt/ramboq";     API_SERVICE="ramboq_api.service"     ;;
  dev)  APP_ROOT="/opt/ramboq_dev"; API_SERVICE="ramboq_dev_api.service" ;;
  *) echo "[$TS] ERROR: unknown ENV '$ENV'"; exit 1 ;;
esac

LOG="$APP_ROOT/.log/hook_debug.log"

{
  echo "[$TS] Deploy triggered: $ENV (branch: $BRANCH)"
  echo "Running as: $(whoami)"

  cd "$APP_ROOT" || { echo "[$TS] ERROR: cannot cd to $APP_ROOT"; exit 1; }

  git --git-dir="$APP_ROOT/.git" --work-tree="$APP_ROOT" config --add safe.directory "$APP_ROOT"

  # One-time migration: rename old config file names to new names
  [ -f "backend/config/config.yaml" ] && [ ! -f "backend/config/backend_config.yaml" ] && \
    mv "backend/config/config.yaml" "backend/config/backend_config.yaml" && \
    echo "[$TS] Migrated config.yaml → backend_config.yaml"
  [ -f "backend/config/ramboq_config.yaml" ] && [ ! -f "backend/config/frontend_config.yaml" ] && \
    mv "backend/config/ramboq_config.yaml" "backend/config/frontend_config.yaml" && \
    echo "[$TS] Migrated ramboq_config.yaml → frontend_config.yaml"
  [ -f "backend/config/ramboq_constants.yaml" ] && [ ! -f "backend/config/constants.yaml" ] && \
    mv "backend/config/ramboq_constants.yaml" "backend/config/constants.yaml" && \
    echo "[$TS] Migrated ramboq_constants.yaml → constants.yaml"

  # Save server-specific backend_config.yaml flags before git operations overwrite it
  CONFIG_BAK="/tmp/ramboq_config_$$.yaml"
  [ -f "backend/config/backend_config.yaml" ] && cp "backend/config/backend_config.yaml" "$CONFIG_BAK"

  # Reset backend_config.yaml to git-tracked version so git operations proceed cleanly
  git checkout -- backend/config/backend_config.yaml 2>/dev/null || true

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
  if [ -f "$CONFIG_BAK" ]; then
    for key in enforce_password_standard cap_in_dev genai telegram mail notify_on_startup alert_loss_abs alert_loss_pct alert_cooldown_minutes; do
      val=$(grep "^${key}:" "$CONFIG_BAK" | head -1 | sed "s/^${key}:[[:space:]]*//" )
      [ -n "$val" ] && sed -i "s/^${key}:.*/${key}: ${val}/" "backend/config/backend_config.yaml"
    done
    rm -f "$CONFIG_BAK"
  fi

  # Write current branch into config
  if grep -q "^deploy_branch:" "backend/config/backend_config.yaml" 2>/dev/null; then
    sed -i "s/^deploy_branch:.*/deploy_branch: ${BRANCH}/" "backend/config/backend_config.yaml"
  else
    echo "deploy_branch: ${BRANCH}" >> "backend/config/backend_config.yaml"
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

  # --- Install Python deps + build SvelteKit frontend ---
  source venv/bin/activate

  # Install Python dependencies (API layer only)
  pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-api.txt \
    && echo "[$TS] Python deps installed" \
    || { echo "[$TS] ERROR: pip install failed"; exit 1; }

  # Build SvelteKit frontend
  if command -v npm &>/dev/null && [ -f "$APP_ROOT/frontend/package.json" ]; then
    echo "[$TS] Building SvelteKit frontend..."
    cd "$APP_ROOT/frontend"
    npm install --prefer-offline 2>&1 | tail -3
    npm run build \
      && echo "[$TS] SvelteKit build complete" \
      || echo "[$TS] WARNING: SvelteKit build failed (non-fatal)"
    cd "$APP_ROOT"
  else
    echo "[$TS] npm not found or no frontend — skipping SvelteKit build"
  fi

  # Fix ownership — manual SSH operations (builds, git) may leave root-owned files
  # that block the next www-data deploy. Fix .svelte-kit, build, node_modules, .git, .log.
  sudo chown -R www-data:www-data "$APP_ROOT/.git" "$APP_ROOT/.log" \
    "$APP_ROOT/frontend/.svelte-kit" "$APP_ROOT/frontend/build" \
    "$APP_ROOT/frontend/node_modules" 2>/dev/null || true

  # Clear stale Kite token cache — forces fresh login after deploy
  rm -f "$APP_ROOT/.log/kite_tokens.json" 2>/dev/null || true

  echo "[$TS] Restarting $API_SERVICE..."
  sudo systemctl restart "$API_SERVICE" || echo "[$TS] ERROR: failed to restart $API_SERVICE"

  echo "[$TS] Sending startup notification..."
  python "$APP_ROOT/webhook/notify_deploy.py" \
    && echo "[$TS] Startup notification done" \
    || echo "[$TS] WARNING: startup notification failed"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
