#!/bin/bash
# Run the Litestar API server. Port 8000 (prod) / 8001 (dev).
#
# Usage:
#   bash backend/run_api.sh             # auto-reload (dev)
#   bash backend/run_api.sh --no-reload # production mode

cd "$(dirname "$0")/.."
source venv/bin/activate

RELOAD="--reload"
if [[ "$1" == "--no-reload" ]]; then
  RELOAD=""
fi

exec uvicorn backend.api.app:app --host 0.0.0.0 --port 8000 $RELOAD
