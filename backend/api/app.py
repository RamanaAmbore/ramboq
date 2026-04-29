"""
Litestar API application.

Single process serves both the REST API and the SvelteKit SPA.
All /api/* and /ws/* routes are handled by Litestar; everything else falls
through to index.html (SPA fallback) so SvelteKit client-side routing works.

Background refresh (holdings/positions/funds, market warm, alerts, open/close
summaries) runs as asyncio tasks within this same process — no Redis, no ARQ.
"""

from pathlib import Path

from litestar import Litestar, get
from litestar.config.cors import CORSConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.response import File
from litestar.static_files import create_static_files_router

from backend.api.background import on_startup as bg_startup, on_shutdown as bg_shutdown
from backend.api.database import init_db
from backend.api.routes.admin import AdminController
from backend.api.routes.agents import AgentController
from backend.api.routes.algo import AlgoController, algo_ws_handler
from backend.api.routes.auth import AuthController
from backend.api.routes.config import ConfigController
from backend.api.routes.contact import ContactController
from backend.api.routes.funds import FundsController
from backend.api.routes.holdings import HoldingsController
from backend.api.routes.market import MarketController
from backend.api.routes.news import NewsController
from backend.api.routes.grammar import GrammarTokenController
from backend.api.routes.instruments import InstrumentsController
from backend.api.routes.orders import AccountsController, OrdersController
from backend.api.routes.quote import QuoteController
from backend.api.routes.positions import PositionsController
from backend.api.routes.settings import SettingsController
from backend.api.routes.brokers import BrokersController
from backend.api.routes.charts import ChartsController
from backend.api.routes.options import OptionsController
from backend.api.routes.simulator import SimulatorController
from backend.api.routes.ws import performance_ws_handler
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)

# Path to SvelteKit build output (repo root → frontend/build)
_FRONTEND_BUILD = Path(__file__).parent.parent.parent / "frontend" / "build"

cors_config = CORSConfig(
    allow_origins=[
        "http://localhost:5173",   # SvelteKit dev server
        "https://ramboq.com",
        "https://dev.ramboq.com",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

openapi_config = OpenAPIConfig(
    title="RamboQuant API",
    version="3.0.0",
    description="Portfolio data API — holdings, positions, funds, orders, market, live WS push",
    render_plugins=[ScalarRenderPlugin()],
)

# ---------------------------------------------------------------------------
# SvelteKit static serving (production only — dev uses Vite)
# ---------------------------------------------------------------------------

_static_router      = None
_assets_router      = None
_spa_fallback       = None
_spa_root           = None

if _FRONTEND_BUILD.exists():
    _index_html = _FRONTEND_BUILD / "index.html"

    _static_router = create_static_files_router(
        path="/_app",
        directories=[_FRONTEND_BUILD / "_app"],
        name="frontend_assets",
        html_mode=False,
    )
    _assets_router = create_static_files_router(
        path="/assets-root",
        directories=[_FRONTEND_BUILD],
        name="frontend_root_assets",
        html_mode=False,
    )

    @get("/{path:path}", include_in_schema=False)
    async def _spa_fallback(path: str) -> File:  # noqa: F811
        # Serve static files (logo.png, nav_image.png, etc.) if they exist
        static_file = _FRONTEND_BUILD / path
        if static_file.is_file() and ".." not in path:
            return File(path=static_file, content_disposition_type="inline")
        return File(path=_index_html, filename="index.html", content_disposition_type="inline")

    @get("/", include_in_schema=False)
    async def _spa_root() -> File:  # noqa: F811
        return File(path=_index_html, filename="index.html", content_disposition_type="inline")

    logger.info(f"Serving SvelteKit build from {_FRONTEND_BUILD}")
else:
    logger.info("SvelteKit build not found — static serving skipped (dev mode)")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_route_handlers = [
    AuthController,
    AdminController,
    AgentController,
    AlgoController,
    HoldingsController,
    PositionsController,
    FundsController,
    MarketController,
    NewsController,
    GrammarTokenController,
    OrdersController,
    AccountsController,
    InstrumentsController,
    QuoteController,
    ContactController,
    ConfigController,
    SettingsController,
    SimulatorController,
    ChartsController,
    OptionsController,
    BrokersController,
    performance_ws_handler,
    algo_ws_handler,
]

if _FRONTEND_BUILD.exists():
    _route_handlers += [_static_router, _assets_router, _spa_fallback, _spa_root]

async def _rebuild_broker_connections() -> None:
    """Move broker accounts off secrets.yaml onto the DB-backed view.
    Runs once on startup after init_db so the broker_accounts table
    exists. First run also seeds DB from YAML for backwards compat."""
    from backend.shared.helpers.connections import Connections
    try:
        await Connections().rebuild_from_db()
    except Exception as e:
        logger.warning(f"broker rebuild_from_db failed (sticking with YAML view): {e}")


# ── Visitor IP / location logger ─────────────────────────────────────────
#
# Logs the approximate origin of every page open so the operator can see
# in /api/admin/logs ("System log" tab) when a visitor lands. Site sits
# behind Cloudflare, so the request headers carry:
#
#   CF-Connecting-IP  : real client IP (not the CF edge proxy)
#   CF-IPCountry      : 2-letter ISO country code (per CF GeoIP)
#   CF-Ray            : <id>-<colo> where colo is a 3-letter CF datacenter
#                       code (BOM = Mumbai, SIN = Singapore, LHR = London,
#                       IAD = Ashburn VA, …) — coarse geographic hint
#                       about which CF edge served the request.
#
# Country + colo combination gives "approx location" without hitting an
# external GeoIP service. De-duplicated per (IP, country, hour) so a
# single visitor doesn't spam the log every poll cycle. In-memory dict
# evicts entries older than 24 h on each read.
from time import monotonic
_visitor_log_cache: dict[tuple[str, str], float] = {}
_VISITOR_LOG_TTL_SEC   = 60 * 60       # re-log a known IP after 1 hour
_VISITOR_LOG_EVICT_SEC = 60 * 60 * 24  # drop entries older than 24 h


async def _log_visitor(request) -> None:  # type: ignore[no-untyped-def]
    """Litestar before_request hook — logs the visitor's IP +
    country + CF colo on first sight per hour. Fires on every
    request but the log line only writes for new (IP, country)
    pairs or those that haven't been seen in the last hour. Skips
    static asset paths so the log isn't drowned in
    /assets/*.js fetches."""
    try:
        path = request.scope.get("path") or ""
        # Skip static + asset traffic — the operator wants to see
        # "someone opened the site," not every chunk fetch.
        if (path.startswith("/assets/")
                or path.startswith("/_app/")
                or path == "/favicon.ico"
                or path.endswith(".png") or path.endswith(".jpg")
                or path.endswith(".svg") or path.endswith(".css")
                or path.endswith(".js")  or path.endswith(".woff")
                or path.endswith(".woff2") or path.endswith(".map")):
            return
        headers = request.headers
        # Cloudflare-supplied real client IP. Fallback chain for
        # local / dev (no Cloudflare) so the hook still produces
        # something useful: X-Forwarded-For (first hop) → request
        # client tuple → "?".
        ip = (
            headers.get("CF-Connecting-IP")
            or (headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            or (request.client.host if request.client else "")
            or "?"
        )
        country = headers.get("CF-IPCountry") or "??"
        # CF-Ray format: <id>-<colo>. Last hyphen-separated chunk is
        # the 3-letter CF datacenter code that served the request.
        cf_ray = headers.get("CF-Ray") or ""
        colo = cf_ray.rsplit("-", 1)[-1] if "-" in cf_ray else "?"
        ua = (headers.get("User-Agent") or "")[:80]

        now = monotonic()
        key = (ip, country)
        # Evict stale entries lazily so the dict doesn't grow forever.
        for k in [k for k, t in _visitor_log_cache.items()
                  if (now - t) > _VISITOR_LOG_EVICT_SEC]:
            _visitor_log_cache.pop(k, None)
        last = _visitor_log_cache.get(key)
        if last is not None and (now - last) < _VISITOR_LOG_TTL_SEC:
            return
        _visitor_log_cache[key] = now
        method = request.scope.get("method") or "GET"
        logger.info(f"[visitor] {ip} ({country}, CF:{colo}) {method} {path} UA=\"{ua}\"")
    except Exception:
        # The hook must NEVER break a real request — geolog is
        # best-effort.
        pass


app = Litestar(
    route_handlers=_route_handlers,
    cors_config=cors_config,
    openapi_config=openapi_config,
    on_startup=[init_db, _rebuild_broker_connections, bg_startup],
    on_shutdown=[bg_shutdown],
    before_request=_log_visitor,
)
