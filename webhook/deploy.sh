#!/bin/bash

LOG="/opt/ramboq/.log/hook_debug.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
export HOME=/var/www


{
  echo "[$TS] Webhook triggered"
  echo "[$TS] Current environment: $(env | grep GITHUB || echo 'No GitHub headers found')"
  echo "[$TS] Executing deploy steps..."

  echo "Running as: $(whoami)" >> "$LOG"

  cd /opt/ramboq || { echo "[$TS] Failed to cd into /opt/ramboq"; exit 1; }

  # Check if .git exists
  if [ -d .git ]; then
  # Use repo-level config so it doesn't rely on global write access
    git --git-dir=/opt/ramboq/.git --work-tree=/opt/ramboq config --add safe.directory /opt/ramboq

    # Pull the latest code
    git --git-dir=.git --work-tree=. pull origin main
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

  # Restart service without sudo, via systemctl user (if applicable)
  echo "[$TS] Attempting to restart ramboq.service..."
  sudo systemctl restart ramboq.service || echo "[$TS] Failed to restart ramboq.service"

  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
