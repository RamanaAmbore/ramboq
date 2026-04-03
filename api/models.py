"""
SQLAlchemy ORM models — user and partner management.
"""

import secrets as _secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column


def _gen_account_id() -> str:
    """Generate a unique account key like rambo-a3f8b2."""
    return f"rambo-{_secrets.token_hex(3)}"

from api.database import Base


class User(Base):
    __tablename__ = "users"

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[int]             = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[str]     = mapped_column(String(16), unique=True, nullable=False, default=_gen_account_id, index=True)
    username: Mapped[str]       = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str]  = mapped_column(Text, nullable=False)
    role: Mapped[str]           = mapped_column(String(16), nullable=False, default="partner")
    display_name: Mapped[str]   = mapped_column(String(128), nullable=False, default="")
    email: Mapped[Optional[str]]       = mapped_column(String(128), nullable=True)
    phone: Mapped[Optional[str]]       = mapped_column(String(20), nullable=True)

    # ── KYC / compliance ──────────────────────────────────────────────────────
    pan: Mapped[Optional[str]]         = mapped_column(String(10), nullable=True)   # Indian PAN
    aadhaar_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)  # last 4 digits only
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    kyc_verified: Mapped[bool]  = mapped_column(Boolean, nullable=False, default=False)

    # ── Address ───────────────────────────────────────────────────────────────
    address_line1: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    city: Mapped[Optional[str]]          = mapped_column(String(64), nullable=True)
    state: Mapped[Optional[str]]         = mapped_column(String(64), nullable=True)
    pincode: Mapped[Optional[str]]       = mapped_column(String(10), nullable=True)

    # ── Investment / partnership ───────────────────────────────────────────────
    contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    contribution_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    share_pct: Mapped[float]    = mapped_column(Float, nullable=False, default=0.0)

    # ── Bank details (for payouts) ────────────────────────────────────────────
    bank_name: Mapped[Optional[str]]     = mapped_column(String(128), nullable=True)
    bank_account: Mapped[Optional[str]]  = mapped_column(String(32), nullable=True)
    bank_ifsc: Mapped[Optional[str]]     = mapped_column(String(16), nullable=True)

    # ── Nominee ───────────────────────────────────────────────────────────────
    nominee_name: Mapped[Optional[str]]     = mapped_column(String(128), nullable=True)
    nominee_relation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    nominee_phone: Mapped[Optional[str]]    = mapped_column(String(20), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    is_approved: Mapped[bool]   = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True)
    join_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # admin notes

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
