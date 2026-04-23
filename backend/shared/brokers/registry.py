"""
Broker registry — routes an account to its `Broker` adapter.

Today every account is Zerodha Kite, so the registry always returns a
`KiteBroker`. The shape is future-proofed: each account in
`secrets.yaml` can tag its vendor via a `broker:` key (defaults to
"kite"), and new vendors just need to land an adapter + one line in
`_ADAPTERS` below. No caller change anywhere.
"""

from __future__ import annotations

from backend.shared.brokers.base import Broker
from backend.shared.brokers.kite import KiteBroker
from backend.shared.helpers.connections import Connections


# Broker id → factory (connection → Broker). Extend here when a new
# vendor adapter lands — e.g. `"upstox": UpstoxBroker`.
_ADAPTERS: dict[str, type[Broker]] = {
    "kite": KiteBroker,
}


def _broker_id_for(account: str) -> str:
    """
    Broker vendor for a given account. Today everything routes to
    Kite; once secrets.yaml starts tagging accounts with a `broker`
    key, read it here.
    """
    from backend.shared.helpers.utils import secrets
    accts = secrets.get("kite_accounts") or {}
    return str((accts.get(account) or {}).get("broker") or "kite")


def get_broker(account: str) -> Broker:
    """
    Return the `Broker` adapter for `account`. Under the hood this
    asks the `Connections` singleton for the per-account client and
    wraps it in the right adapter class. Calling this on a hot path
    is fine — no re-auth happens here, and adapter construction is a
    two-attribute object that reuses the cached connection.
    """
    conn = Connections().conn.get(account)
    if conn is None:
        raise KeyError(f"No broker client configured for account {account!r}")
    broker_id = _broker_id_for(account)
    adapter_cls = _ADAPTERS.get(broker_id)
    if adapter_cls is None:
        raise ValueError(
            f"Account {account!r} is tagged broker={broker_id!r} but no "
            f"adapter is registered. Add it under "
            f"backend/shared/brokers/{broker_id}.py and register in "
            f"_ADAPTERS in this file."
        )
    # KiteBroker expects a KiteConnection. Future adapters may expect a
    # different client type — that's wrapped in the same dict today
    # because every account is Kite, but when a second vendor lands the
    # `Connections` class should hold broker-specific clients keyed by
    # account and this line will pass the right type through.
    return adapter_cls(conn)


def all_brokers() -> list[Broker]:
    """Every configured broker adapter, one per account."""
    return [get_broker(acct) for acct in Connections().conn.keys()]
