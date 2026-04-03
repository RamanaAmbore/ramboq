"""
Config / content endpoints — serves static content from frontend_config.yaml.

GET /api/config/post   — investment insights (markdown text)
GET /api/config/about  — about page content (markdown text)
"""

from litestar import Controller, get

from api.schemas import PostResponse
from src.helpers.date_time_utils import timestamp_display
from src.helpers.utils import ramboq_config


class ConfigController(Controller):
    path = "/api/config"

    @get("/post")
    async def get_post(self) -> PostResponse:
        return PostResponse(
            content=ramboq_config.get("post", ""),
            refreshed_at=timestamp_display(),
        )

    @get("/about")
    async def get_about(self) -> PostResponse:
        return PostResponse(
            content=ramboq_config.get("about", ""),
            refreshed_at=timestamp_display(),
        )
