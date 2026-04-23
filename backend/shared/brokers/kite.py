"""
Zerodha Kite implementation of the `Broker` interface.

Wraps the existing `KiteConnection` (see
`backend/shared/helpers/connections.py`) so auth, token caching, 23 h
refresh, multi-account IPv6 binding, and the parallel-login lock all
keep working exactly as they do today — this module is a thin typed
facade over that machinery.
"""

from __future__ import annotations

from typing import Any

from backend.shared.brokers.base import Broker
from backend.shared.helpers.connections import KiteConnection


class KiteBroker(Broker):
    broker_id = "kite"

    def __init__(self, conn: KiteConnection) -> None:
        self._conn = conn

    # ── Identity + escape hatch ───────────────────────────────────────

    @property
    def account(self) -> str:
        return self._conn.account

    @property
    def kite(self):
        """
        Underlying KiteConnect SDK handle. Re-validates the token on
        every access (via `get_kite_conn(test_conn=False)`), so cheap
        after the singleton is warmed. Prefer the typed methods below
        — this property is the escape hatch for operations that
        haven't been lifted into `Broker` yet.
        """
        return self._conn.get_kite_conn()

    # ── Account state ─────────────────────────────────────────────────

    def profile(self) -> dict:
        return self.kite.profile()

    def holdings(self) -> list[dict]:
        return self.kite.holdings()

    def positions(self) -> dict:
        return self.kite.positions()

    def margins(self, segment: str | None = None) -> dict:
        return self.kite.margins(segment) if segment else self.kite.margins()

    def orders(self) -> list[dict]:
        return self.kite.orders()

    # ── Market data ───────────────────────────────────────────────────

    def ltp(self, symbols: list[str]) -> dict:
        return self.kite.ltp(symbols)

    def quote(self, symbols: list[str]) -> dict:
        return self.kite.quote(symbols)

    def instruments(self, exchange: str | None = None) -> list[dict]:
        return self.kite.instruments(exchange) if exchange else self.kite.instruments()

    def holidays(self, exchange: str) -> set[str]:
        return self.kite.holidays(exchange)

    # ── Order entry ───────────────────────────────────────────────────

    def place_order(self, **kwargs: Any) -> str:
        return self.kite.place_order(**kwargs)

    def modify_order(self, order_id: str, **kwargs: Any) -> str:
        return self.kite.modify_order(order_id=order_id, **kwargs)

    def cancel_order(self, order_id: str, **kwargs: Any) -> str:
        return self.kite.cancel_order(order_id=order_id, **kwargs)
