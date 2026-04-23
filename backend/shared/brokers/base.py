"""
Broker abstract base. See `backend/shared/brokers/__init__.py` for the
extension contract. Every method here corresponds to a capability the
rest of the codebase depends on — if a new vendor doesn't natively
expose one, the adapter should either synthesise the result or raise a
clear `NotImplementedError` with a pointer to what the caller needs to
handle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Broker(ABC):
    """
    Broker-agnostic interface.

    Conventions shared by every adapter:
      - `account` is the RamboQuant-internal account code (e.g. "ZG0790").
      - Every method returns broker-native response shapes that the
        codebase already consumes. Specifically:
          * holdings / positions / margins / orders — list[dict] or
            dict matching the Zerodha Kite shape the summarise helpers
            expect. Adapters for other brokers normalise to this shape
            so callers don't branch per vendor.
          * ltp / quote — dict keyed by broker-formatted symbol.
          * instruments — list[dict] with tradingsymbol / instrument_token
            / exchange / expiry / strike / lot_size columns.
          * holidays — set[str] of ISO dates.
      - Re-authentication / token refresh is owned by the adapter; the
        caller should never have to check connection health.

    Escape hatch: adapters may expose an underlying SDK handle (e.g.
    `KiteBroker.kite`) for features that haven't been lifted into the
    interface yet. Any new use of that handle is a smell — prefer to
    add the operation to this ABC.
    """

    # Identifiers
    broker_id: str = "unknown"

    @property
    @abstractmethod
    def account(self) -> str:
        """RamboQuant account code (e.g. "ZG0790")."""

    # ── Account state ─────────────────────────────────────────────────

    @abstractmethod
    def profile(self) -> dict: ...

    @abstractmethod
    def holdings(self) -> list[dict]: ...

    @abstractmethod
    def positions(self) -> dict:
        """Return positions (typically keyed by `net` / `day` buckets)."""

    @abstractmethod
    def margins(self, segment: str | None = None) -> dict: ...

    @abstractmethod
    def orders(self) -> list[dict]: ...

    # ── Market data ───────────────────────────────────────────────────

    @abstractmethod
    def ltp(self, symbols: list[str]) -> dict: ...

    @abstractmethod
    def quote(self, symbols: list[str]) -> dict: ...

    @abstractmethod
    def instruments(self, exchange: str | None = None) -> list[dict]: ...

    @abstractmethod
    def holidays(self, exchange: str) -> set[str]: ...

    # ── Order entry ───────────────────────────────────────────────────

    @abstractmethod
    def place_order(self, **kwargs: Any) -> str:
        """Returns the broker order id."""

    @abstractmethod
    def modify_order(self, order_id: str, **kwargs: Any) -> str: ...

    @abstractmethod
    def cancel_order(self, order_id: str, **kwargs: Any) -> str: ...
