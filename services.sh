#!/bin/bash

LOG_FILE="/opt/ramboq/.log/reload_services.log"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

echo "[$TIMESTAMP] Starting service reload..." | tee -a $LOG_FILE

# Reload systemd daemon
echo "Reloading systemd daemon..." | tee -a $LOG_FILE
sudo systemctl daemon-reexec 2>&1 | tee -a $LOG_FILE
sudo systemctl daemon-reload 2>&1 | tee -a $LOG_FILE

# Reload Nginx
echo "Testing Nginx configuration..." | tee -a $LOG_FILE
if sudo nginx -t 2>&1 | tee -a $LOG_FILE; then
  echo "Reloading Nginx..." | tee -a $LOG_FILE
  sudo systemctl reload nginx 2>&1 | tee -a $LOG_FILE
else
  echo "❌ Nginx config test failed!" | tee -a $LOG_FILE
fi

# Restart webhook service
echo "Restarting ramboq_hook.service..." | tee -a $LOG_FILE
sudo systemctl restart ramboq_hook.service 2>&1 | tee -a $LOG_FILE

# Restart app service
echo "Restarting ramboq.service..." | tee -a $LOG_FILE
sudo systemctl restart ramboq.service 2>&1 | tee -a $LOG_FILE

echo "[$TIMESTAMP] Service reload complete." | tee -a $LOG_FILE


