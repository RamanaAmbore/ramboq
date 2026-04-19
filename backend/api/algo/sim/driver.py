"""
Market-price simulation driver for /api/test.

The driver feeds fabricated holdings / positions / margins into the running
agent engine so operators can exercise the full alert + action pipeline
without touching the real broker. Design goals:

1. **No code branches in the hot path.** The agent engine, dispatcher and
   action handlers are unaware that data came from here — they read
   `test_mode` off `alert_state` and prepend `[TEST]` where appropriate.
2. **Branch-gated.** `assert_dev()` requires `cap_in_<branch>.simulator: True`.
   Default shipped values: dev on, prod off. Auto-stops after 30 minutes.
3. **Deterministic replay.** `step()` applies exactly one tick; `start()`
   runs the scenario at a user-set cadence via asyncio.

The driver is a module-level singleton because there is only ever one
simulation running per process — concurrent sims would race for the
same `alert_state` and emit confusing alerts.
"""

from __future__ import annotations

import asyncio
import copy
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config

logger = get_logger(__name__)

SCENARIOS_PATH = Path(__file__).parent / "scenarios.yaml"
AUTO_STOP_AFTER = timedelta(minutes=30)
TICK_LOG_LIMIT = 200


class SimGuardError(RuntimeError):
    """Raised when an operator tries to run the sim in a forbidden context."""


def assert_dev() -> None:
    """
    Branch-aware simulator gate.

    The simulator runs only when the capability flag for the current branch
    allows it. Default shipping values:
      - cap_in_prod.simulator: False  (explicit off — prod won't run sim)
      - cap_in_dev.simulator:  True   (explicit on — dev runs sim)

    Flipping cap_in_prod.simulator to True WILL enable the sim on main.
    That's intentional — the operator may want to exercise the pipeline
    against fabricated data on a freshly-promoted build before reverting.
    It is NOT the default.
    """
    from backend.shared.helpers.utils import is_enabled
    if is_enabled("simulator"):
        return
    branch = config.get("deploy_branch", "dev")
    section = "cap_in_prod" if branch == "main" else "cap_in_dev"
    raise SimGuardError(
        f"Market simulation is disabled. Set {section}.simulator: True in "
        f"backend_config.yaml (branch: {branch})."
    )


def load_scenarios() -> list[dict]:
    """Load scenarios.yaml. Empty list if the file is missing or malformed."""
    if not SCENARIOS_PATH.exists():
        return []
    try:
        with SCENARIOS_PATH.open() as fh:
            data = yaml.safe_load(fh) or []
        return [s for s in data if isinstance(s, dict) and s.get("slug")]
    except Exception as e:
        logger.error(f"Sim: failed to load scenarios.yaml: {e}")
        return []


def get_scenario(slug: str) -> Optional[dict]:
    for s in load_scenarios():
        if s.get("slug") == slug:
            return s
    return None


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame out of a list of account rows. Handles empty lists."""
    if not rows:
        return pd.DataFrame(columns=["account"])
    return pd.DataFrame(rows)


def _add_total_row(df: pd.DataFrame, sum_cols: list[str]) -> pd.DataFrame:
    """
    Append a TOTAL row with sums for the given columns. Mimics the shape
    `summarise_holdings` / `summarise_positions` produce on the real pipeline,
    so the dispatch formatters see identical input.
    """
    if df.empty:
        return df
    total = {"account": "TOTAL"}
    for col in sum_cols:
        if col in df.columns:
            total[col] = float(df[col].sum())
    # Derived percentage fields after the sum, so they aren't summed blindly.
    if "cur_val" in df.columns and "pnl" in df.columns and "TOTAL" in df["account"].values:
        pass  # placeholder; derived percentages computed below
    if {"cur_val", "day_change_val"}.issubset(df.columns) and total.get("cur_val"):
        total["day_change_percentage"] = total["day_change_val"] / total["cur_val"] * 100
    if {"cur_val", "pnl"}.issubset(df.columns) and total.get("cur_val"):
        total["pnl_percentage"] = total["pnl"] / total["cur_val"] * 100
    return pd.concat([df, pd.DataFrame([total])], ignore_index=True)


class SimDriver:
    """Singleton simulation driver. Keeps one scenario's running state."""

    _instance: Optional["SimDriver"] = None

    def __init__(self) -> None:
        self.active: bool = False
        self.scenario_slug: Optional[str] = None
        self.scenario: Optional[dict] = None
        self.started_at: Optional[datetime] = None
        self.tick_index: int = 0
        self.rate_ms: int = 2000
        self._task: Optional[asyncio.Task] = None
        # Running state — mutated by _apply_tick. Base rows are copied from
        # scenario.initial each start() so successive runs are independent.
        self._holdings_rows: list[dict] = []
        self._positions_rows: list[dict] = []
        self._margins_rows: list[dict] = []
        # Rolling buffer of recent ticks, surfaced via /api/test/ticks/recent
        # so the Simulator log tab can render a live timeline.
        self._tick_log: deque[dict] = deque(maxlen=TICK_LOG_LIMIT)

    @classmethod
    def instance(cls) -> "SimDriver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── state shape ────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "active": self.active,
            "scenario": self.scenario_slug,
            "tick_index": self.tick_index,
            "rate_ms": self.rate_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "total_ticks": len(self.scenario.get("ticks", [])) if self.scenario else 0,
            "holdings_count": len(self._holdings_rows),
            "positions_count": len(self._positions_rows),
            "margins_count": len(self._margins_rows),
        }

    def dataframes(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Return (sum_holdings, sum_positions, df_margins) suitable for
        dropping into the agent context. TOTAL rows are recomputed here.
        """
        sum_holdings  = _add_total_row(
            _rows_to_df(self._holdings_rows),
            ["inv_val", "cur_val", "pnl", "day_change_val"],
        )
        sum_positions = _add_total_row(
            _rows_to_df(self._positions_rows),
            ["pnl"],
        )
        df_margins    = _add_total_row(
            _rows_to_df(self._margins_rows),
            ["avail opening_balance", "net", "util debits", "avail collateral"],
        )
        return sum_holdings, sum_positions, df_margins

    # ── control ────────────────────────────────────────────────────────────

    def start(self, scenario_slug: str, rate_ms: int = 2000) -> dict:
        assert_dev()
        if self.active:
            raise SimGuardError("Sim is already running — stop it first.")
        scen = get_scenario(scenario_slug)
        if not scen:
            raise SimGuardError(f"Unknown scenario '{scenario_slug}'")
        self.scenario_slug = scenario_slug
        self.scenario = scen
        self.rate_ms = max(200, int(rate_ms))
        self.tick_index = 0
        self.started_at = datetime.now()
        self._holdings_rows  = copy.deepcopy(scen.get("initial", {}).get("holdings", []))
        self._positions_rows = copy.deepcopy(scen.get("initial", {}).get("positions", []))
        self._margins_rows   = copy.deepcopy(scen.get("initial", {}).get("margins", []))
        self._tick_log.clear()
        self._record_tick(
            kind="started",
            patch={},
            changes=[],
            note=f"Scenario loaded: {scenario_slug} @ {self.rate_ms}ms",
        )
        self.active = True
        logger.warning(f"[TEST] Sim started: {scenario_slug} @ {rate_ms}ms")
        self._task = asyncio.create_task(self._run_loop(), name="sim-driver")
        return self.snapshot()

    def stop(self) -> dict:
        if not self.active:
            return self.snapshot()
        self.active = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._record_tick(
            kind="stopped",
            patch={},
            changes=[],
            note=f"Stopped after {self.tick_index} ticks",
        )
        logger.warning(f"[TEST] Sim stopped after {self.tick_index} ticks")
        return self.snapshot()

    def step(self) -> dict:
        """Apply one tick (for deterministic debugging)."""
        assert_dev()
        if not self.scenario:
            raise SimGuardError("No scenario loaded. Call start(...) first.")
        self._apply_next_tick()
        return self.snapshot()

    async def _run_loop(self) -> None:
        """Async loop driving the scenario at `rate_ms` cadence."""
        try:
            while self.active:
                if datetime.now() - self.started_at > AUTO_STOP_AFTER:
                    logger.warning("[TEST] Sim auto-stop after 30 min")
                    self.stop()
                    return
                self._apply_next_tick()
                # After each tick, fire the agent engine so the simulated
                # state flows all the way through to alerts + actions. The
                # sim owns its own alert_state dict so real and simulated
                # suppression history never mix.
                await self._run_cycle_once()
                await asyncio.sleep(self.rate_ms / 1000)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[TEST] Sim loop crashed: {e}")
            self.active = False

    # Long-lived alert_state for the simulator — kept separate from the real
    # background task's state so rate-history and suppression don't cross.
    _sim_alert_state: dict = {"test_mode": True}

    async def _run_cycle_once(self) -> None:
        """Invoke the agent engine against the current sim state."""
        try:
            from backend.api.algo.agent_engine import run_cycle
            from backend.api.routes.algo import _broadcast_event
            from backend.shared.helpers.date_time_utils import (
                timestamp_display,
                timestamp_indian,
            )

            sum_h, sum_p, df_m = self.dataframes()
            ctx = {
                "sum_holdings":   sum_h,
                "sum_positions":  sum_p,
                "df_margins":     df_m,
                "now":            timestamp_indian(),
                "ist_display":    timestamp_display(),
                "seg_state":      {},
                "segments":       [],
                "alert_state":    self._sim_alert_state,
                "test_mode":      True,
            }
            await run_cycle(ctx, _broadcast_event)
        except Exception as e:
            logger.error(f"[TEST] Sim run_cycle failed: {e}")

    def _apply_next_tick(self) -> None:
        """Apply the next tick in the scenario (wraps at end)."""
        if not self.scenario:
            return
        ticks = self.scenario.get("ticks", []) or []
        if not ticks:
            return
        tick = ticks[self.tick_index % len(ticks)]
        patch = tick.get("patch") or {}
        changes = self._apply_patch(patch)
        self.tick_index += 1
        self._record_tick(kind="tick", patch=patch, changes=changes)

    def _apply_patch(self, patch: dict) -> list[dict]:
        """
        Apply a flat-dotted-key patch to the running state and return a list
        of diff entries (one per key that actually changed) for the tick log.

        Keys look like:
          holdings.<account>.<col>
          positions.<account>.<col>
          margins.<account>.<col>
        """
        changes: list[dict] = []
        for key, val in patch.items():
            parts = key.split(".", 2)
            if len(parts) != 3:
                logger.warning(f"[TEST] Sim: skipping malformed patch key '{key}'")
                continue
            section, account, col = parts
            rows = {
                "holdings":  self._holdings_rows,
                "positions": self._positions_rows,
                "margins":   self._margins_rows,
            }.get(section)
            if rows is None:
                logger.warning(f"[TEST] Sim: unknown section '{section}' in patch")
                continue
            match = next((r for r in rows if r.get("account") == account), None)
            if match is None:
                # Auto-create the row if the scenario omitted it.
                match = {"account": account}
                rows.append(match)
            prev = match.get(col)
            match[col] = val
            changes.append({
                "section": section,
                "account": account,
                "col":     col,
                "prev":    prev,
                "next":    val,
                "delta":   (val - prev) if isinstance(prev, (int, float)) and isinstance(val, (int, float)) else None,
            })
        return changes

    def _record_tick(self, *, kind: str, patch: dict, changes: list[dict],
                     note: str = "") -> None:
        """Append a row to the tick log. `kind` is tick / started / stopped."""
        self._tick_log.append({
            "ts":           datetime.now().isoformat(timespec="seconds"),
            "tick_index":   self.tick_index,
            "scenario":     self.scenario_slug,
            "kind":         kind,
            "patch":        patch,
            "changes":      changes,
            "note":         note,
        })

    def recent_ticks(self, limit: int = 100) -> list[dict]:
        """Return the most recent `limit` ticks (oldest-first)."""
        limit = max(1, min(int(limit), TICK_LOG_LIMIT))
        return list(self._tick_log)[-limit:]

    # ── convenience ────────────────────────────────────────────────────────

    def scenarios_manifest(self) -> list[dict]:
        """Lightweight list (slug / name / description / tick count) for the UI."""
        out = []
        for s in load_scenarios():
            out.append({
                "slug": s.get("slug"),
                "name": s.get("name") or s.get("slug"),
                "description": s.get("description", ""),
                "ticks": len(s.get("ticks", []) or []),
            })
        return out


# Module-level accessor — same style as Connections / REGISTRY elsewhere.
def get_driver() -> SimDriver:
    return SimDriver.instance()
