"""
Replay / backtest engine — feeds historical Kite OHLCV candles through the
agent engine as if they were live ticks.

Public API:

    from backend.api.algo.replay import ReplayDriver, get_replay_driver
"""

from backend.api.algo.replay.driver import ReplayDriver, get_replay_driver

__all__ = ["ReplayDriver", "get_replay_driver"]
