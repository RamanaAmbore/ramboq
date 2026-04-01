#!/bin/bash
# Webhook dispatch script — deployed to /etc/webhook/dispatch.sh
# Routes incoming push events to the correct environment's deploy script.
# Usage: dispatch.sh <REF>  (called by webhook with ref as first arg)

REF="${1:-refs/heads/main}"
BRANCH="${REF#refs/heads/}"

if [ "$BRANCH" = "main" ]; then
    exec /opt/ramboq/webhook/deploy.sh prod "$REF"
elif echo "$BRANCH" | grep -q "^pod"; then
    exec /opt/ramboq_pod/webhook/deploy.sh pod "$REF"
else
    exec /opt/ramboq_dev/webhook/deploy.sh dev "$REF"
fi
