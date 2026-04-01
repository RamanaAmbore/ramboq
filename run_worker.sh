#!/bin/bash
# Run the ARQ background worker.
# Replaces the background_refresh.py threading loop in Phase 2.
# Requires Redis running: docker run -d -p 6379:6379 redis:alpine
#
# Usage:
#   bash run_worker.sh

cd "$(dirname "$0")"
source venv/bin/activate

exec arq workers.refresh_worker.WorkerSettings
