"""
Litestar API application — Phase 1 of Streamlit → SvelteKit migration.

Runs alongside the Streamlit app on port 8000.
All broker data, market update, and background refresh are served from here.
Streamlit pages will be updated to call this API instead of broker APIs directly.
"""

from litestar import Litestar
from litestar.config.cors import CORSConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin

from api.routes.funds import FundsController
from api.routes.holdings import HoldingsController
from api.routes.market import MarketController
from api.routes.positions import PositionsController
from api.routes.ws import WSController

cors_config = CORSConfig(
    allow_origins=["http://localhost:8502", "http://localhost:8503", "http://localhost:8504",
                   "https://ramboq.com", "https://dev.ramboq.com", "https://pod.ramboq.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

openapi_config = OpenAPIConfig(
    title="RamboQuant API",
    version="1.0.0",
    description="Portfolio data API — holdings, positions, funds, market update",
    render_plugins=[ScalarRenderPlugin()],
)

app = Litestar(
    route_handlers=[
        HoldingsController,
        PositionsController,
        FundsController,
        MarketController,
        WSController,
    ],
    cors_config=cors_config,
    openapi_config=openapi_config,
)
