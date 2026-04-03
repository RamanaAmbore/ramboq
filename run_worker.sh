#!/bin/bash
# Run the ARQ background worker.
# Replaces the background_refresh.py threading loop in Phase 2.
# Requires Redis running: podman run -d -p 6379:6379 redis:alpine
#
# Usage:
#   bash run_worker.sh

cd "$(dirname "$0")"
source venv/bin/activate

# ARQ 0.26/0.27 calls asyncio.get_event_loop() in Worker.__init__ which
# fails on Python 3.14 (no implicit loop). Set an explicit loop first.
exec python3 -c "
import asyncio

# Create and set a loop before ARQ Worker initialises
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from arq import run_worker
from workers.refresh_worker import WorkerSettings

run_worker(WorkerSettings)
"
