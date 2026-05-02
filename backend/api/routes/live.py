"""
Live mode status — `/api/live/*`.

Dedicated status endpoint for live execution flags. Previously these were
only accessible buried in /admin/settings. This gives the Live page a
structured API.

Endpoints
  GET  /api/live/status    — which execution.live.* flags are active
"""

from __future__ import annotations

from litestar import Controller, get
from litestar.exceptions import HTTPException

from backend.api.auth_guard import admin_guard
from backend.shared.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


class LiveController(Controller):
    path = "/api/live"
    guards = [admin_guard]

    @get("/status")
    async def status(self) -> dict:
        from backend.shared.helpers.utils import config, is_prod_branch
        from backend.shared.helpers.settings import get_bool

        branch = config.get("deploy_branch", "dev") or "dev"
        is_prod = is_prod_branch()

        paper_mode = get_bool("execution.paper_trading_mode", True)
        shadow_mode = get_bool("execution.shadow_mode", False)

        live_flags = {
            "cancel_order": get_bool("execution.live.cancel_order", False),
            "cancel_all_orders": get_bool("execution.live.cancel_all_orders", False),
            "modify_order": get_bool("execution.live.modify_order", False),
            "place_order": get_bool("execution.live.place_order", False),
            "close_position": get_bool("execution.live.close_position", False),
            "chase_close_positions": get_bool("execution.live.chase_close_positions", False),
        }

        live_count = sum(1 for v in live_flags.values() if v)
        total = len(live_flags)

        # Effective state: what actually happens when an agent fires
        if not is_prod:
            effective = "dev_paper"  # dev never hits broker
        elif paper_mode:
            effective = "paper"     # master toggle overrides everything
        elif shadow_mode:
            effective = "shadow"    # shadow intercepts before live
        elif live_count == 0:
            effective = "paper"     # all per-action flags off
        elif live_count == total:
            effective = "live"      # fully live
        else:
            effective = "mixed"     # some actions live, some paper

        return {
            "enabled": is_prod,
            "branch": branch,
            "paper_trading_mode": paper_mode,
            "shadow_mode": shadow_mode,
            "live_flags": live_flags,
            "live_count": live_count,
            "total_flags": total,
            "effective": effective,
        }
