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
from backend.api.routes.instruments import InstrumentsController
from backend.api.routes.orders import AccountsController, OrdersController
from backend.api.routes.positions import PositionsController
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
    OrdersController,
    AccountsController,
    InstrumentsController,
    ContactController,
    ConfigController,
    performance_ws_handler,
    algo_ws_handler,
]

if _FRONTEND_BUILD.exists():
    _route_handlers += [_static_router, _assets_router, _spa_fallback, _spa_root]

app = Litestar(
    route_handlers=_route_handlers,
    cors_config=cors_config,
    openapi_config=openapi_config,
    on_startup=[init_db, bg_startup],
    on_shutdown=[bg_shutdown],
)
