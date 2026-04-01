#!/bin/bash
# Run the Litestar API server alongside the Streamlit app.
# Port 8000 — Streamlit stays on 8502/8503/8504.
#
# Usage:
#   bash run_api.sh             # default: auto-reload on code changes (dev)
#   bash run_api.sh --no-reload # production mode (no auto-reload)

cd "$(dirname "$0")"
source venv/bin/activate

RELOAD="--reload"
if [[ "$1" == "--no-reload" ]]; then
  RELOAD=""
fi

exec uvicorn api.app:app --host 0.0.0.0 --port 8000 $RELOAD
