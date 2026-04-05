# RamboQuant Analytics

A production web application for **RamboQuant Analytics LLP** at [ramboq.com](https://ramboq.com). The app provides portfolio performance tracking, AI market updates, partner management, investment information, and real-time notifications.

## Architecture

**Dual-stack**: Streamlit (legacy) + **Litestar API + SvelteKit frontend** (active migration on `new` branch).

| Layer | Technology |
|---|---|
| Backend API | Litestar 2.x (ASGI) + msgspec |
| ASGI server | Uvicorn |
| Frontend | SvelteKit + TailwindCSS + AG Grid |
| Database | PostgreSQL 17 via SQLAlchemy 2.x + asyncpg |
| Background | Litestar async tasks (primary) + ARQ/Redis (optional) |
| DataFrame | Polars (API aggregation) + pandas (broker layer) |
| Auth | JWT HS256 + PBKDF2-SHA256 passwords |
| Broker | Zerodha Kite API |
| AI | Gemini 2.5 Flash (Google GenAI) |
| Alerts | Telegram Bot API + SMTP email |
| Deploy | GitHub Webhook + systemd + nginx |

## Features

- **Portfolio tracking**: Holdings, positions, funds — per-account and combined views via AG Grid
- **AI market reports**: Gemini 2.5 Flash with Google Search grounding, cached daily
- **Real-time updates**: WebSocket push from background tasks to connected browsers
- **Partner management**: Registration (pending admin approval), KYC, contribution tracking, profit share
- **Admin dashboard**: User management (create, approve/reject, edit all partner fields), log viewer
- **Notifications**: Telegram + email alerts for market open/close summaries and loss thresholds
- **Segment-aware**: Equity (NSE/NFO 09:15–15:30) and Commodity (MCX 09:00–23:30) handled independently
- **Multi-environment**: prod (ramboq.com), dev (dev.ramboq.com)

---

## Database

PostgreSQL 17 on the server. Two databases:

| Database | Branch | Purpose |
|---|---|---|
| `ramboq` | `main` | Production |
| `ramboq_dev` | any other | Development |

Selected automatically by `deploy_branch` in `backend_config.yaml`.

**Credentials** in `secrets.yaml`:
```yaml
db_user: rambo_admin
db_password: <password>
db_host: localhost     # optional, default localhost
db_port: 5432          # optional, default 5432
```

**Users table** (30 columns):
- Identity: `id`, `account_id` (auto-generated `rambo-XXXXXX`), `username`, `password_hash`, `role` (admin/partner), `display_name`, `email`, `phone`
- KYC: `pan`, `aadhaar_last4`, `date_of_birth`, `kyc_verified`
- Address: `address_line1/2`, `city`, `state`, `pincode`
- Investment: `contribution`, `contribution_date`, `share_pct`
- Bank: `bank_name`, `bank_account`, `bank_ifsc`
- Nominee: `nominee_name`, `nominee_relation`, `nominee_phone`
- Status: `is_approved`, `is_active`, `join_date`, `notes`, `created_at`, `updated_at`

**Server setup** (one-time):
```sql
-- As postgres superuser
CREATE DATABASE ramboq OWNER rambo_admin;
CREATE DATABASE ramboq_dev OWNER rambo_admin;
```

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/login` | — | JWT token (403 if unapproved partner) |
| POST | `/api/auth/register` | — | Register partner (pending admin approval) |
| GET | `/api/auth/me` | JWT | User profile |
| GET | `/api/holdings/` | — | Holdings rows + summary |
| GET | `/api/positions/` | — | Positions rows + summary |
| GET | `/api/funds/` | — | Funds per account |
| GET | `/api/market/` | — | AI market report |
| GET | `/api/config/post` | — | Insights content |
| GET | `/api/config/about` | — | About content |
| POST | `/api/admin/users` | admin | Create user (pre-approved) |
| PUT | `/api/admin/users/{username}/approve` | admin | Approve pending user |
| PUT | `/api/admin/users/{username}/reject` | admin | Reject user |
| PUT | `/api/admin/users/{username}` | admin | Update partner fields |
| GET | `/api/admin/users` | admin | List all users |
| DELETE | `/api/admin/users/{username}` | admin | Deactivate user |
| GET | `/api/admin/logs` | admin | Tail log file |
| POST | `/api/admin/exec` | admin | Run shell command |
| WS | `/ws/performance` | — | Live push |

All responses include `refreshed_at` in IST|EST dual-timezone format.

---

## Project Structure

```
api/
  app.py              — Litestar app; on_startup: init_db + background tasks
  database.py         — PostgreSQL via asyncpg; DB selected by deploy_branch
  models.py           — User ORM (30 columns: personal, KYC, address, investment, bank, nominee)
  schemas.py          — msgspec.Struct response models
  background.py       — Async scheduler: market warm, performance refresh, close summaries
  cache.py            — In-process TTL cache with per-key locking
  auth_guard.py       — jwt_guard + admin_guard
  routes/
    auth.py           — Login, register, me, logout
    admin.py          — Create/approve/reject/update users, logs, exec
    holdings.py       — Polars aggregation
    positions.py      — Polars aggregation
    funds.py          — Polars aggregation
    market.py         — Gemini with 1h TTL cache
    config.py         — Post/about content
    orders.py         — Order CRUD (protected)
    ws.py             — WebSocket fan-out

workers/
  refresh_worker.py   — ARQ worker (optional alternative to Litestar background)

frontend/
  src/
    app.css           — AG Grid theme, buttons, form fields
    lib/
      api.js          — REST + admin helpers with JWT auth
      stores.js       — authStore + dataCache (stale-while-revalidate)
      ws.js           — Auto-reconnect WebSocket
    routes/
      +layout.svelte  — Responsive nav, role-based links
      performance/    — AG Grid: per-account + combined grids, URL ?tab= sync
      market/         — Markdown renderer + timestamp
      post/           — Insights with timestamp
      faq/            — Accordion + Mermaid diagrams
      about/          — Static content
      contact/        — Contact form
      signin/         — Sign In / Register (name, email, phone, PAN)
      admin/          — User management (create, approve, edit all fields)
      portfolio/      — Partner contribution info

src/helpers/          — Shared: broker_apis, connections, decorators, alert_utils, genai_api
setup/yaml/           — backend_config.yaml, frontend_config.yaml, constants.yaml, secrets.yaml
webhook/              — deploy.sh, dispatch.sh, service files, hooks.json
```

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-api.txt

# Start API (requires PostgreSQL — use server or local PostgreSQL)
bash run_api.sh

# Start frontend dev server
cd frontend && npm install && npm run dev
# open http://localhost:5173

# Optional: ARQ worker (alternative background mode, needs Redis)
docker run -d -p 6379:6379 redis:alpine
bash run_worker.sh
```

**Dependencies (`requirements-api.txt`):**
```
litestar[standard]~=2.12
uvicorn[standard]~=0.34
redis~=5.2, arq~=0.26        # optional — ARQ worker mode
polars>=1.0
httpx~=0.28
PyJWT~=2.10
SQLAlchemy[asyncio]~=2.0
asyncpg~=0.30
```

---

## Deployment

Two environments, auto-deployed on `git push` via GitHub webhook:

| Environment | Branch | Server path | Port | Domain |
|---|---|---|---|---|
| Production | `main` | `/opt/ramboq` | 8502 | ramboq.com |
| Development | non-main | `/opt/ramboq_dev` | 8503 | dev.ramboq.com |

**Flow**: `git push` → GitHub webhook → nginx → webhook listener (port 9001) → `dispatch.sh` → `deploy.sh` → git pull + pip install + systemctl restart

Both branches (`main`, `dev`) are permanent and kept in sync.

---

## Configuration

### `secrets.yaml` (gitignored — hand-place on server)
```yaml
# SMTP
smtp_server: smtp.hostinger.com
smtp_port: 587
smtp_user_name: RamboQuant Team
smtp_user: <email>
smtp_pass: <password>

# Broker
kite_accounts:
  <user_id>:
    password: ...
    totp_token: ...
    api_key: ...
    api_secret: ...
kite_login_url: https://kite.zerodha.com/api/login
kite_twofa_url: https://kite.zerodha.com/api/twofa

# Database
db_user: rambo_admin
db_password: <password>

# Auth
cookie_secret: <random-string>

# AI
gemini_api_key: <key>

# Notifications
telegram_bot_token: <token>
telegram_chat_id: <group-id>
alert_emails:
  - <email>
```

### `backend_config.yaml` (tracked — server flags preserved across deploys)
Key settings: `deploy_branch`, `cap_in_dev`, `genai`, `telegram`, `mail`, `notify_on_startup`, `alert_loss_abs`, `alert_loss_pct`, `performance_refresh_interval`, `market_segments`.

---

## Background Processing

Two modes:

| Mode | Command | Redis | Processes |
|---|---|---|---|
| Litestar async (default) | `bash run_api.sh` | No | 1 |
| ARQ worker | `run_api.sh` + `run_worker.sh` | Yes | 2 |

Tasks: market cache warm (daily 08:30 IST), performance refresh (every 5 min during market hours), open/close summaries, loss alerts.

---

## Auth Flow

- **Self-registration**: Partner registers (name, email, phone, PAN, password) → account pending → admin approves → partner can sign in
- **Admin-created**: Admin creates user via Users page → sets password, contribution, share % → user is pre-approved → admin shares password securely
- **Auto-generated account ID**: Each user gets a unique `rambo-XXXXXX` identifier
- **Roles**: `admin` (full access + Users page), `partner` (portfolio view)

---

## Alerts and Notifications

| Event | Telegram | Email |
|---|---|---|
| Market open | `Open — Equity/Commodity` | `RamboQuant Open:` |
| Loss threshold | `Alert` | `RamboQuant Alert:` |
| Market close | `Close` | `RamboQuant Close:` |
| Deploy | `Deploy OK` | `RamboQuant Deploy OK:` |

Timestamps in dual format: `Mon, March 30, 2026, 09:30 AM IST | Mon, March 30, 2026, 10:00 PM EDT`

---

## Security

- `secrets.yaml` is gitignored — never committed
- JWT tokens expire after 8 hours
- Passwords hashed with PBKDF2-SHA256 (260k iterations)
- Partner accounts require admin approval before login
- Admin endpoints protected by `admin_guard`
- PostgreSQL credentials in secrets.yaml only
- Webhook validated with HMAC-SHA256 signature
