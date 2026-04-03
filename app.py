"""
DECOMMISSIONED — Phase 3.

This was the Streamlit entry point. The application now runs as a Litestar
ASGI server that serves both the REST/WebSocket API and the SvelteKit SPA.

Start the server with:
    uvicorn api.app:app --host 0.0.0.0 --port 8000

Or via the systemd service:
    sudo systemctl start ramboq.service

The ARQ background worker runs separately:
    bash run_worker.sh
"""
raise SystemExit(
    "app.py is decommissioned. Run: uvicorn api.app:app --host 0.0.0.0 --port 8000"
)
