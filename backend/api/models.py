"""
SQLAlchemy ORM models — user and partner management.
"""

import secrets as _secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


def _gen_account_id() -> str:
    """Generate a unique account key like rambo-a3f8b2."""
    return f"rambo-{_secrets.token_hex(3)}"

from backend.api.database import Base


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


# ---------------------------------------------------------------------------
# Algo — chase orders and events
# ---------------------------------------------------------------------------

class AlgoOrder(Base):
    __tablename__ = "algo_orders"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    account: Mapped[str]         = mapped_column(String(32), nullable=False)
    symbol: Mapped[str]          = mapped_column(String(64), nullable=False)
    exchange: Mapped[str]        = mapped_column(String(8), nullable=False, default="NFO")
    transaction_type: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY/SELL
    quantity: Mapped[int]        = mapped_column(Integer, nullable=False)
    initial_price: Mapped[float] = mapped_column(Float, nullable=True)
    fill_price: Mapped[float]    = mapped_column(Float, nullable=True)
    attempts: Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    slippage: Mapped[float]      = mapped_column(Float, nullable=True)
    status: Mapped[str]          = mapped_column(String(16), nullable=False, default="pending")
    engine: Mapped[str]          = mapped_column(String(16), nullable=False, default="expiry")  # expiry/manual/interpreter
    mode: Mapped[str]            = mapped_column(String(8), nullable=False, default="live")     # live/sim
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AlgoEvent(Base):
    __tablename__ = "algo_events"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    algo_order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("algo_orders.id"), nullable=True)
    event_type: Mapped[str]      = mapped_column(String(32), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime]  = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Agent Framework — Conditions → Alerts → Actions
# ---------------------------------------------------------------------------

class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str]            = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str]            = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Condition tree (AND/OR/NOT with account selection)
    conditions: Mapped[dict]     = mapped_column(JSONB, nullable=False, default=dict)

    # Alert channels
    events: Mapped[list]         = mapped_column(JSONB, nullable=False, default=list)

    # Actions (empty list = alert-only)
    actions: Mapped[list]        = mapped_column(JSONB, nullable=False, default=list)

    # Evaluation config
    scope: Mapped[str]           = mapped_column(String(16), nullable=False, default="per_account")
    schedule: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default="market_hours")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Runtime state
    status: Mapped[str]          = mapped_column(String(16), nullable=False, default="inactive")
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger_count: Mapped[int]   = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Meta
    is_system: Mapped[bool]      = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[int]              = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int]        = mapped_column(Integer, ForeignKey("agents.id"), nullable=False)
    event_type: Mapped[str]      = mapped_column(String(32), nullable=False)
    trigger_condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sim_mode: Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)
    timestamp: Mapped[datetime]  = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Market report — single-row cache (id=1). Reused across deploys when <24h old.
# ---------------------------------------------------------------------------

class MarketReport(Base):
    __tablename__ = "market_report"

    id: Mapped[int]            = mapped_column(Integer, primary_key=True)
    content: Mapped[str]       = mapped_column(Text, nullable=False)
    cycle_date: Mapped[str]    = mapped_column(String(32), nullable=False)
    refreshed_at: Mapped[str]  = mapped_column(String(128), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Agent grammar — the extensible token catalog that defines every condition,
# notify channel, and action available to the Agent engine. Built-in tokens
# are seeded at startup with is_system=True; operators add/tune runtime
# tokens via the admin UI (planned) without restarting.
# ---------------------------------------------------------------------------

class GrammarToken(Base):
    __tablename__ = "grammar_tokens"

    id: Mapped[int]           = mapped_column(primary_key=True, autoincrement=True)

    # Three grammar domains — each has its own token namespace:
    #   'condition' : metric, scope, operator, function
    #   'notify'    : channel, format, template
    #   'action'    : action_type
    grammar_kind: Mapped[str] = mapped_column(String(16),  nullable=False, index=True)
    token_kind: Mapped[str]   = mapped_column(String(32),  nullable=False, index=True)
    token: Mapped[str]        = mapped_column(String(128), nullable=False)

    # Semantic classification of the value the token produces or accepts.
    # 'number' | 'string' | 'boolean' | 'enum' | 'array' | 'object' | 'void'
    value_type: Mapped[Optional[str]] = mapped_column(String(16),  nullable=True)
    # Human-readable unit for numeric metrics: "₹", "%", "₹/min", "%/min", "min", ...
    units: Mapped[Optional[str]]      = mapped_column(String(16),  nullable=True)
    description: Mapped[str]          = mapped_column(Text,        nullable=False, default="")

    # Dispatch pointer. For metric/scope/operator/action_type/function: dotted
    # path to a Python resolver/handler function. For channel/format: dotted
    # path to a class or callable. The engine imports by name at reload time.
    resolver: Mapped[Optional[str]]   = mapped_column(String(256), nullable=True)

    # Structured schema describing expected params — used by the admin UI to
    # render forms and by the runtime to validate. Shape:
    #   {"param_name": {"type": "number|string|enum|...", "required": true,
    #                    "enum": [...], "default": ..., "token_ref_ok": true}}
    params_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # For enum value_types: list of legal string values.
    enum_values: Mapped[Optional[list]]   = mapped_column(JSONB, nullable=True)
    # For notify template tokens: the template body with ${placeholder} syntax.
    template_body: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    # System tokens ship with the code and are regenerated from seeds each boot.
    # Operators cannot delete them; they can only deactivate. Custom tokens have
    # is_system=False and are freely editable/deletable via the admin UI.
    is_system: Mapped[bool]   = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool]   = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint('grammar_kind', 'token_kind', 'token',
                         name='uq_grammar_token'),
    )


# ---------------------------------------------------------------------------
# News headlines — accumulated throughout the day, truncated at 07:00 IST
# ---------------------------------------------------------------------------

class NewsHeadline(Base):
    __tablename__ = "news_headlines"

    link: Mapped[str]          = mapped_column(Text, primary_key=True)
    title: Mapped[str]         = mapped_column(Text, nullable=False)
    source: Mapped[str]        = mapped_column(String(128), nullable=False, default="")
    timestamp_display: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
