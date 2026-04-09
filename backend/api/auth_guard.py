"""
Litestar guard that enforces JWT authentication on protected routes.
Sets request.state.token_payload with the decoded JWT on success.

Apply at the controller level:
    class OrdersController(Controller):
        guards = [jwt_guard]
"""

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler


def jwt_guard(connection: ASGIConnection, handler: BaseRouteHandler) -> None:  # noqa: ARG001
    """Raise NotAuthorizedException if request carries no valid JWT."""
    auth_header = connection.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise NotAuthorizedException("Missing or invalid Authorization header")
    token = auth_header.removeprefix("Bearer ").strip()
    from backend.api.routes.auth import verify_token
    payload = verify_token(token)
    if not payload:
        raise NotAuthorizedException("Token invalid or expired")
    # Stash payload so route handlers can read user info without re-decoding
    connection.state.token_payload = payload


def admin_guard(connection: ASGIConnection, handler: BaseRouteHandler) -> None:  # noqa: ARG001
    """Require a valid JWT with role=admin."""
    jwt_guard(connection, handler)
    payload = getattr(connection.state, "token_payload", {})
    if payload.get("role") != "admin":
        raise NotAuthorizedException("Admin access required")


def is_admin_request(connection: ASGIConnection) -> bool:
    """Check if the request has a valid admin JWT. Does NOT raise — returns False if not."""
    try:
        auth_header = connection.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header.removeprefix("Bearer ").strip()
        from backend.api.routes.auth import verify_token
        payload = verify_token(token)
        return bool(payload and payload.get("role") == "admin")
    except Exception:
        return False
