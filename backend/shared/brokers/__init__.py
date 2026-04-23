"""
Broker abstraction layer.

Every broker-specific client lives behind the `Broker` interface defined
in `base.py`. The rest of the codebase (routes, background tasks, agent
engine, actions, the simulator) asks for a `Broker` via the registry
and never imports broker-specific SDKs directly — so adding a second
broker (Upstox, Angel One, Fyers, Dhan…) is "implement Broker, register
it" and nothing else changes.

Public API:

    from backend.shared.brokers import Broker, get_broker, all_brokers

    broker = get_broker("ZG0790")       # Broker for that account
    broker.ltp(["NSE:NIFTY 50"])        # broker-agnostic call
    for b in all_brokers():             # every configured broker
        b.holdings()

Adding a new broker:
  1. Create `backend/shared/brokers/<name>.py` with a class that
     implements every method of `Broker` (see base.py) for that
     vendor's SDK.
  2. Register it in `registry.py` under the broker identifier you
     pick (e.g. "upstox"). Tag the relevant accounts in secrets.yaml
     with `broker: upstox` and the registry will route to the new
     adapter automatically.
"""

from backend.shared.brokers.base     import Broker
from backend.shared.brokers.registry import get_broker, all_brokers

__all__ = ["Broker", "get_broker", "all_brokers"]
