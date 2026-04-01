# RamboQuant — Migration Plan: Streamlit → Litestar + SvelteKit

This document tracks the phased migration from the Streamlit monolith to a proper
frontend/backend split. The goal is zero downtime — each phase is independently deployable.

---

## Target Stack

| Layer | Technology | Reason |
|---|---|---|
| **Backend API** | Litestar 2.x (ASGI) | Native async, fast DI, WebSocket, OpenAPI |
| **ASGI server** | Uvicorn | Standard, battle-tested |
| **Background jobs** | ARQ + Redis | Async-native, replaces threading.Thread loop |
| **DataFrame** | Polars (Phase 3) | 10–50× faster than pandas, Rust-based |
| **Frontend** | SvelteKit | Reactive, small bundle, no virtual DOM overhead |
| **Styling** | TailwindCSS | Responsive utility-first CSS |
| **Data grid** | AG Grid Community | High-performance financial tables |
| **Data fetching** | TanStack Query | Cache + background refresh + stale-while-revalidate |
| **Real-time push** | WebSockets (Litestar ↔ SvelteKit) | Live data without polling |
| **Auth** | Litestar JWT | Replaces stubbed `validate_user()` |

---

## Phase 1 — API Layer (current, `new` branch)

**Goal:** Litestar API runs alongside Streamlit. Streamlit pages remain unchanged.
Validates API contract and broker connectivity before touching the frontend.

### What's scaffolded

```
api/
  app.py              — Litestar app, CORS config, OpenAPI (Scalar UI at /schema)
  schemas.py          — Pydantic v2 response models
  routes/
    holdings.py       — GET /api/holdings/
    positions.py      — GET /api/positions/
    funds.py          — GET /api/funds/
    market.py         — GET /api/market/
    ws.py             — WS  /ws/performance  (placeholder — Phase 2)

workers/
  refresh_worker.py   — ARQ worker; mirrors background_refresh.py as cron jobs

requirements-api.txt  — litestar, uvicorn, redis, arq, httpx
run_api.sh            — starts Litestar on port 8000
run_worker.sh         — starts ARQ worker (requires Redis)
```

### How to run locally

```bash
# Install API deps
pip install -r requirements-api.txt

# Terminal 1 — Litestar API
bash run_api.sh

# Terminal 2 — Streamlit (unchanged)
streamlit run app.py --server.port 8502

# OpenAPI docs
open http://localhost:8000/schema
```

### API endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/holdings/` | `HoldingsResponse` — rows + summary |
| GET | `/api/positions/` | `PositionsResponse` — rows + summary |
| GET | `/api/funds/` | `FundsResponse` — cash, margins per account |
| GET | `/api/market/` | `MarketResponse` — AI market report |
| WS | `/ws/performance` | Live push (Phase 2) |

---

## Phase 2 — Redis pub/sub + WebSocket push

**Goal:** ARQ worker publishes refreshed data to Redis. Litestar WebSocket handler
fans out to connected clients. SvelteKit frontend subscribes via WebSocket — open browser
auto-updates without polling.

Steps:
1. Wire `workers/refresh_worker.py` to publish JSON to `redis://performance:update` after each fetch
2. Implement `api/routes/ws.py` WebSocket handler to subscribe to Redis and push to clients
3. Scaffold SvelteKit app in `frontend/` with AG Grid tables consuming `/api/...` and `/ws/performance`
4. Add JWT auth endpoints: `POST /api/auth/login`, `POST /api/auth/logout`

---

## Phase 3 — Polars + full SvelteKit frontend

**Goal:** Replace pandas with Polars everywhere; ship SvelteKit as the primary UI.
Streamlit kept for internal admin/debug only.

Steps:
1. Replace `pd.DataFrame`, `pd.concat`, `groupby` in `broker_apis.py` and `utils_streamlit.py` with Polars lazy frames
2. SvelteKit pages: Performance (AG Grid), Market (markdown render), Profile, Contact, FAQ
3. Responsive layout: TailwindCSS, mobile-first nav
4. Remove Streamlit dependency (keep as optional fallback behind a flag)

---

## What stays unchanged

- `src/helpers/` — broker_apis, connections, decorators, alert_utils, genai_api (all reused by API)
- `setup/yaml/` — all config and secrets files
- `webhook/` — deploy scripts, notify_deploy.py
- `src/helpers/background_refresh.py` — still active until ARQ worker is validated in prod

---

## Branch strategy

- `new` — active migration work
- `dev` / `main` / `pod` — production branches; never rebased or force-pushed
- Migration work merged to `dev` → `main` → `pod` when each phase is production-ready
