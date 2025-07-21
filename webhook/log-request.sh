#!/bin/bash
ts=$(date "+%Y-%m-%d %H:%M:%S")
echo "[$ts] --- Incoming Webhook ---" >> /opt/ramboq/.log/requests.log
echo "$WEBHOOK_REQUEST_HEADERS" >> /opt/ramboq/.log/requests.log
echo "$WEBHOOK_REQUEST_BODY" >> /opt/ramboq/.log/requests.log
