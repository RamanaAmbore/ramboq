"""
JWT auth endpoints.

POST /api/auth/login     — validate credentials, return access token + user info
POST /api/auth/register  — create a new user account (partner role by default)
POST /api/auth/logout    — client-side token discard (stateless)
GET  /api/auth/me        — decode token, return user profile

Users are stored in SQLAlchemy DB (data/ramboq.db).
On first startup with an empty DB, any non-empty credentials are accepted (stub mode)
so you can sign in immediately and create real users.
"""

import base64
import hashlib
import time
from typing import Optional

import jwt
import msgspec
from litestar import Controller, Request, get, post
from litestar.exceptions import HTTPException
from sqlalchemy import select

from api.auth_guard import jwt_guard
from api.database import async_session
from api.models import User
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import secrets

logger = get_logger(__name__)

_JWT_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 8 * 3600  # 8 hours


def _jwt_secret() -> str:
    secret = secrets.get("jwt_secret") or secrets.get("cookie_secret", "")
    if not secret:
        raise RuntimeError("jwt_secret / cookie_secret not set in secrets.yaml")
    return secret


def _make_token(username: str, role: str, display_name: str,
                contribution: float = 0) -> str:
    payload = {
        "sub":          username,
        "role":         role,
        "display_name": display_name,
        "contribution": contribution,
        "iat":          int(time.time()),
        "exp":          int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify a JWT and return the full payload dict. Returns None if invalid/expired."""
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Password hashing — PBKDF2-SHA256
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = base64.b64encode(
        hashlib.sha256(password.encode() + str(time.time()).encode()).digest()[:16]
    ).decode()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2_sha256$260000${salt}${base64.b64encode(dk).decode()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, stored_b64 = stored.split("$", 3)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return base64.b64encode(dk).decode() == stored_b64
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Schemas (msgspec)
# ---------------------------------------------------------------------------

class LoginRequest(msgspec.Struct):
    username: str
    password: str


class LoginResponse(msgspec.Struct):
    access_token: str
    username: str
    role: str
    display_name: str
    token_type: str = "bearer"
    expires_in: int = _TOKEN_TTL_SECONDS


class RegisterRequest(msgspec.Struct):
    username: str
    password: str
    display_name: str
    email: str = ""
    phone: str = ""
    pan: str = ""


class UserProfile(msgspec.Struct):
    username: str
    role: str
    display_name: str
    contribution: float


class LogoutResponse(msgspec.Struct):
    detail: str


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AuthController(Controller):
    path = "/api/auth"

    @post("/login")
    async def login(self, data: LoginRequest) -> LoginResponse:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.username == data.username, User.is_active == True)
            )
            user = result.scalar_one_or_none()

        if user and _check_password(data.password, user.password_hash):
            if not user.is_approved and user.role != "admin":
                raise HTTPException(status_code=403, detail="Account pending admin approval")
            token = _make_token(user.username, user.role, user.display_name,
                                user.contribution)
            logger.info(f"Auth: login OK for {data.username!r} role={user.role}")
            return LoginResponse(
                access_token=token,
                username=user.username,
                role=user.role,
                display_name=user.display_name,
            )

        # Stub mode: if no users in DB, accept any non-empty credentials
        async with async_session() as session:
            count = (await session.execute(select(User))).scalars().all()
        if not count and data.username and data.password:
            logger.warning("Auth: no users in DB — stub mode, accepting any credentials")
            token = _make_token(data.username, "admin", data.username)
            return LoginResponse(
                access_token=token,
                username=data.username,
                role="admin",
                display_name=data.username,
            )

        raise HTTPException(status_code=401, detail="Invalid username or password")

    @post("/register")
    async def register(self, data: RegisterRequest) -> LoginResponse:
        if len(data.password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

        async with async_session() as session:
            existing = await session.execute(
                select(User).where(User.username == data.username)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Username already exists")

            user = User(
                username=data.username,
                password_hash=hash_password(data.password),
                role="partner",
                display_name=data.display_name or data.username,
                email=data.email or None,
                phone=data.phone or None,
                pan=data.pan.upper() if data.pan else None,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        token = _make_token(user.username, user.role, user.display_name,
                            user.contribution)
        logger.info(f"Auth: registered {data.username!r}")
        return LoginResponse(
            access_token=token,
            username=user.username,
            role=user.role,
            display_name=user.display_name,
        )

    @get("/me", guards=[jwt_guard])
    async def me(self, request: Request) -> UserProfile:
        payload = request.state.token_payload
        return UserProfile(
            username=payload.get("sub", ""),
            role=payload.get("role", "partner"),
            display_name=payload.get("display_name", ""),
            contribution=payload.get("contribution", 0),
        )

    @post("/logout")
    async def logout(self) -> LogoutResponse:
        return LogoutResponse(detail="Logged out")
