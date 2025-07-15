#!/bin/bash

LOG="/opt/ramboq/.log/hook_debug.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

{
  echo "[$TS] Webhook triggered"
  echo "[$TS] Current environment: $(env | grep GITHUB || echo 'No GitHub headers found')"
  echo "[$TS] Executing deploy steps..."
  cd /opt/ramboq
  git pull origin main
  source venv/bin/activate
  pip install -r requirements.txt
  systemctl restart ramboq
  echo "[$TS] Deployment complete"
} >> "$LOG" 2>&1
