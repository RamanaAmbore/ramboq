"""
Settings admin API — `/api/admin/settings/*`.

Reads and writes the `settings` table (DB-backed tunables). Paired with
the `/admin/settings` page. All endpoints admin-guarded.

Endpoints
  GET   /api/admin/settings                    — list all, grouped by category
  GET   /api/admin/settings/{key}              — read a single key
  PATCH /api/admin/settings/{key}              — update `value` (validated against value_type + schema)
  POST  /api/admin/settings/{key}/reset        — reset `value` back to `default_value`
"""

from __future__ import annotations

import msgspec
from litestar import Controller, get, patch, post
from litestar.exceptions import HTTPException
from sqlalchemy import select

from backend.api.auth_guard import admin_guard
from backend.api.database import async_session
from backend.api.models import Setting
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.settings import invalidate_cache

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SettingInfo(msgspec.Struct):
    id: int
    category: str
    key: str
    value_type: str
    value: str
    default_value: str
    description: str
    schema: dict | None
    units: str | None
    updated_at: str


class SettingPatch(msgspec.Struct):
    value: str   # always sent as string; server casts per value_type


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(value_type: str, raw: str, schema: dict | None) -> str:
    """
    Validate + normalise an incoming string value against the stored
    value_type and optional schema. Returns the canonical string form;
    raises HTTPException(400) with a helpful message on any failure.
    """
    raw = (raw or "").strip()
    if value_type == "bool":
        if raw.lower() in ("1", "true", "yes", "on"):  return "true"
        if raw.lower() in ("0", "false", "no", "off"): return "false"
        raise HTTPException(status_code=400, detail=f"Expected bool; got {raw!r}")
    if value_type == "int":
        try:
            n = int(float(raw))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Expected integer; got {raw!r}")
        if schema:
            if "min" in schema and n < schema["min"]:
                raise HTTPException(status_code=400, detail=f"Minimum is {schema['min']}")
            if "max" in schema and n > schema["max"]:
                raise HTTPException(status_code=400, detail=f"Maximum is {schema['max']}")
        return str(n)
    if value_type == "float":
        try:
            f = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Expected number; got {raw!r}")
        if schema:
            if "min" in schema and f < schema["min"]:
                raise HTTPException(status_code=400, detail=f"Minimum is {schema['min']}")
            if "max" in schema and f > schema["max"]:
                raise HTTPException(status_code=400, detail=f"Maximum is {schema['max']}")
        return str(f)
    if value_type == "enum":
        allowed = (schema or {}).get("enum") or []
        if raw not in allowed:
            raise HTTPException(status_code=400,
                                detail=f"Must be one of {allowed}; got {raw!r}")
        return raw
    # string — free-form
    return raw


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

def _to_info(r: Setting) -> SettingInfo:
    return SettingInfo(
        id=r.id, category=r.category, key=r.key, value_type=r.value_type,
        value=r.value, default_value=r.default_value,
        description=r.description, schema=r.schema, units=r.units,
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


class SettingsController(Controller):
    path = "/api/admin/settings"
    guards = [admin_guard]

    @get("/")
    async def list_all(self) -> list[SettingInfo]:
        async with async_session() as s:
            rows = (await s.execute(
                select(Setting).order_by(Setting.category, Setting.key)
            )).scalars().all()
        return [_to_info(r) for r in rows]

    @get("/{key:str}")
    async def read_one(self, key: str) -> SettingInfo:
        async with async_session() as s:
            row = (await s.execute(
                select(Setting).where(Setting.key == key)
            )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail=f"Setting {key!r} not found")
        return _to_info(row)

    @patch("/{key:str}")
    async def update(self, key: str, data: SettingPatch) -> SettingInfo:
        async with async_session() as s:
            row = (await s.execute(
                select(Setting).where(Setting.key == key)
            )).scalar_one_or_none()
            if not row:
                raise HTTPException(status_code=404, detail=f"Setting {key!r} not found")
            row.value = _validate(row.value_type, data.value, row.schema)
            await s.commit()
            await s.refresh(row)
        invalidate_cache()
        logger.info(f"Settings: {key} updated to {row.value!r}")
        return _to_info(row)

    @post("/{key:str}/reset")
    async def reset(self, key: str) -> SettingInfo:
        async with async_session() as s:
            row = (await s.execute(
                select(Setting).where(Setting.key == key)
            )).scalar_one_or_none()
            if not row:
                raise HTTPException(status_code=404, detail=f"Setting {key!r} not found")
            row.value = row.default_value
            await s.commit()
            await s.refresh(row)
        invalidate_cache()
        logger.info(f"Settings: {key} reset to default {row.value!r}")
        return _to_info(row)
