#!/bin/bash
# Webhook dispatch script — deployed to /etc/webhook/dispatch.sh
# Routes incoming push events to the correct environment's deploy script.
# No environment-specific logic here — each deploy script is self-contained.

REF="${1:-refs/heads/main}"
BRANCH="${REF#refs/heads/}"

if [ "$BRANCH" = "main" ]; then
    exec /opt/ramboq/webhook/deploy.sh
elif echo "$BRANCH" | grep -q "^pod/"; then
    exec /opt/ramboq_pod/webhook/deploy_pod.sh "$@"
else
    exec /opt/ramboq_dev/webhook/deploy_dev.sh "$@"
fi
