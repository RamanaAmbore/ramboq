"""
Market-price simulation driver for /api/simulator/*.

The driver feeds fabricated per-symbol holdings / positions into the running
agent engine so operators can exercise the full alert + action pipeline
without touching the real broker.

Design goals
  1. **Price-driver, not aggregate-driver.** Each tick moves per-symbol
     `last_price`; all derived fields (`cur_val`, `pnl`, `day_change_val`,
     `day_change_percentage`, per-account aggregates, TOTAL rows) are
     recomputed from the raw symbol state via `summarise_holdings` /
     `summarise_positions`. This gives the agent engine exactly the same
     DataFrame shape it receives in production.
  2. **No code branches in the hot path.** The agent engine, dispatcher and
     action handlers are unaware that data came from here — they read
     `sim_mode` off `alert_state` and prepend `[SIMULATOR]` where needed.
  3. **Branch-gated.** `assert_enabled()` requires `cap_in_<branch>.simulator
     = True`. Default shipped values: dev on, prod off. Auto-stops after 30
     minutes so a forgotten sim can't bleed forever.
  4. **Deterministic replay.** `step()` applies exactly one tick; `start()`
     runs the scenario at a user-set cadence via asyncio. `random_walk`
     moves accept a `seed` so the tick stream is reproducible.

The driver is a module-level singleton because only one simulation can run
per process — concurrent sims would race for the same `_sim_alert_state`
and emit confusing alerts.
"""

from __future__ import annotations

import asyncio
import copy
import fnmatch
import random
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


def assert_enabled() -> None:
    """
    Branch-aware simulator gate.

    The simulator runs only when the capability flag for the current branch
    allows it. Default shipping values:
      - cap_in_prod.simulator: False  (prod won't run sim by default)
      - cap_in_dev.simulator:  True   (dev runs sim by default)
    """
    from backend.shared.helpers.utils import is_enabled
    if is_enabled("simulator"):
        return
    branch = config.get("deploy_branch", "dev")
    section = "cap_in_prod" if branch == "main" else "cap_in_dev"
    raise SimGuardError(
        f"Market simulator is disabled. Set {section}.simulator: True in "
        f"backend_config.yaml (branch: {branch})."
    )


# Back-compat alias used by older callers.
assert_dev = assert_enabled


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


# ═════════════════════════════════════════════════════════════════════════
#  Per-row math — LTP changes drive every derived field.
# ═════════════════════════════════════════════════════════════════════════

def _recompute_holding_row(row: dict) -> None:
    """
    Mutate a holdings row in-place: recompute derived fields from the current
    `last_price`. Matches the shape broker_apis.fetch_holdings produces, so
    the downstream summarise_holdings call sees identical input.
    """
    qty  = float(row.get("opening_quantity") or 0)
    avg  = float(row.get("average_price")    or 0)
    lp   = float(row.get("last_price")       or 0)
    cp   = float(row.get("close_price")      or 0)
    inv  = avg * qty
    cur  = lp  * qty
    pnl  = cur - inv
    dchg = lp  - cp
    row["inv_val"]        = inv
    row["cur_val"]        = cur
    row["pnl"]            = pnl
    row["day_change"]     = dchg
    row["day_change_val"] = dchg * qty
    row["pnl_percentage"] = (pnl / inv * 100) if inv else 0.0


def _recompute_position_row(row: dict) -> None:
    """
    Mutate a positions row in-place: keep `pnl` consistent with the current
    `last_price`. Real Kite `pnl` includes realised + m2m; for the simulator
    we use the simple model `(last_price - average_price) × quantity` because
    that's what the loss-* agents read.
    """
    qty = float(row.get("quantity")       or 0)
    avg = float(row.get("average_price")  or 0)
    lp  = float(row.get("last_price")     or 0)
    row["pnl"] = (lp - avg) * qty


# ═════════════════════════════════════════════════════════════════════════
#  Glob scope matching — section.account.tradingsymbol
# ═════════════════════════════════════════════════════════════════════════

def _match_glob(glob: str, section: str, account: str, symbol: str) -> bool:
    """
    Match a glob like `holdings.**` / `holdings.ZG*.*` / `positions.*.NIFTY*`
    against a (section, account, symbol) triple. `*` matches any run of
    characters within one segment; `**` matches everything remaining.
    """
    target = f"{section}.{account}.{symbol}"
    # `**` as a stand-alone segment matches any remaining path.
    norm = glob.replace(".**", ".*")
    if glob.endswith(".**"):
        norm = glob[:-3] + ".*"
    # Apply fnmatch segment-wise so `*` doesn't eat dots.
    g_parts = norm.split(".")
    t_parts = target.split(".")
    if len(g_parts) != len(t_parts):
        # Handle `**` at the tail: glob has fewer parts — expand.
        if glob.endswith(".**") and len(t_parts) >= len(g_parts) - 1:
            g_parts = g_parts[:-1]
            t_parts = t_parts[:len(g_parts)]
        else:
            return False
    return all(fnmatch.fnmatchcase(tp, gp) for gp, tp in zip(g_parts, t_parts))


class SimDriver:
    """
    Singleton simulation driver. Keeps the running per-symbol state and
    applies scenario moves tick-by-tick. Also exposes a "seed from live
    book" entrypoint so the operator can stress-test their actual positions.
    """

    _instance: Optional["SimDriver"] = None

    def __init__(self) -> None:
        self.active: bool = False
        self.scenario_slug: Optional[str] = None
        self.scenario: Optional[dict] = None
        self.seed_mode: str = "scripted"       # scripted | live | live+scenario
        self.started_at: Optional[datetime] = None
        self.tick_index: int = 0
        self.rate_ms: int = 2000
        # Optional: list of agent IDs to restrict this sim to — lets the
        # operator dry-fire a single agent from the /algo page.
        self.only_agent_ids: list[int] | None = None
        self._task: Optional[asyncio.Task] = None

        # Running per-symbol state (copied from scenario + / or live book).
        self._holdings_rows: list[dict] = []
        self._positions_rows: list[dict] = []
        self._margins_rows: list[dict] = []

        # Cached snapshot of the most recently fetched live book — lets the
        # UI preview "Load live book" before committing to Start.
        self._live_snapshot: Optional[dict] = None

        # Per-move random generator so random_walk scenarios are reproducible
        # across runs. Re-seeded on every start() from scenario config.
        self._rng: random.Random = random.Random()

        # Rolling buffer of recent ticks surfaced via /api/simulator/ticks/recent.
        self._tick_log: deque[dict] = deque(maxlen=TICK_LOG_LIMIT)

    @classmethod
    def instance(cls) -> "SimDriver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public state snapshot ─────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "active":           self.active,
            "scenario":         self.scenario_slug,
            "seed_mode":        self.seed_mode,
            "tick_index":       self.tick_index,
            "rate_ms":          self.rate_ms,
            "started_at":       self.started_at.isoformat() if self.started_at else None,
            "total_ticks":      len(self.scenario.get("ticks", [])) if self.scenario else 0,
            "holdings_count":   len(self._holdings_rows),
            "positions_count":  len(self._positions_rows),
            "margins_count":    len(self._margins_rows),
            "only_agent_ids":   list(self.only_agent_ids) if self.only_agent_ids else [],
            "live_snapshot_at": (self._live_snapshot or {}).get("snapshot_at"),
        }

    # ── DataFrame builder the agent engine consumes ───────────────────

    def dataframes(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Return (sum_holdings, sum_positions, df_margins) in the exact shape
        the real background task feeds into run_cycle — per-account rows + a
        TOTAL row. We call the same summarise helpers the live path uses so
        any rounding / derived-column quirks are identical.
        """
        from backend.shared.helpers.summarise import (
            summarise_holdings, summarise_positions,
        )

        df_h_raw = pd.DataFrame(self._holdings_rows) if self._holdings_rows else pd.DataFrame()
        df_p_raw = pd.DataFrame(self._positions_rows) if self._positions_rows else pd.DataFrame()

        # summarise_holdings takes an optional full-summary frame for cash
        # columns — we don't have that at sim-time, so pass an empty frame.
        empty = pd.DataFrame(columns=["account"])
        sum_h = summarise_holdings(df_h_raw, empty) if not df_h_raw.empty \
                else pd.DataFrame(columns=["account", "inv_val", "cur_val", "pnl", "day_change_val"])
        sum_p = summarise_positions(df_p_raw) if not df_p_raw.empty \
                else pd.DataFrame(columns=["account", "pnl"])

        # df_margins: build per-account + TOTAL with the same columns the
        # real path produces. Flat passthrough with a computed TOTAL row.
        if self._margins_rows:
            df_m = pd.DataFrame(self._margins_rows)
            numeric = df_m.select_dtypes(include="number").sum()
            total   = numeric.to_dict()
            total["account"] = "TOTAL"
            df_m = pd.concat([df_m, pd.DataFrame([total])], ignore_index=True)
        else:
            df_m = pd.DataFrame(columns=["account"])

        return sum_h, sum_p, df_m

    # ── Control ───────────────────────────────────────────────────────

    def start(self, scenario_slug: str, rate_ms: int = 2000,
              *, seed_mode: str = "scripted",
              only_agent_ids: list[int] | None = None) -> dict:
        assert_enabled()
        if self.active:
            raise SimGuardError("Sim is already running — stop it first.")
        scen = get_scenario(scenario_slug)
        if not scen:
            raise SimGuardError(f"Unknown scenario '{scenario_slug}'")

        self.scenario_slug  = scenario_slug
        self.scenario       = scen
        self.seed_mode      = seed_mode
        self.rate_ms        = max(200, int(rate_ms))
        self.tick_index     = 0
        self.started_at     = datetime.now()
        self.only_agent_ids = list(only_agent_ids) if only_agent_ids else None

        # Seed the running state — either from scenario.initial, the live-book
        # snapshot, or both stacked.
        if seed_mode in ("live", "live+scenario"):
            if not self._live_snapshot:
                raise SimGuardError(
                    "seed_mode requires a live-book snapshot. "
                    "POST /api/simulator/seed-live first.")
            self._holdings_rows  = copy.deepcopy(self._live_snapshot["holdings"])
            self._positions_rows = copy.deepcopy(self._live_snapshot["positions"])
            self._margins_rows   = copy.deepcopy(self._live_snapshot["margins"])

        if seed_mode in ("scripted", "live+scenario"):
            initial = scen.get("initial") or {}
            if seed_mode == "scripted":
                self._holdings_rows  = copy.deepcopy(initial.get("holdings", []))
                self._positions_rows = copy.deepcopy(initial.get("positions", []))
                self._margins_rows   = copy.deepcopy(initial.get("margins", []))
            else:
                # live+scenario — scripted initial rows are layered on top of
                # the live snapshot (useful for injecting a specific symbol).
                self._holdings_rows.extend(copy.deepcopy(initial.get("holdings", [])))
                self._positions_rows.extend(copy.deepcopy(initial.get("positions", [])))
                self._margins_rows.extend(copy.deepcopy(initial.get("margins", [])))

        # Recompute derived fields on every row so scripted YAML authors
        # can just specify quantity + average_price + last_price + close_price.
        for r in self._holdings_rows:
            _recompute_holding_row(r)
        for r in self._positions_rows:
            _recompute_position_row(r)

        rng_seed = scen.get("seed")
        self._rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

        self._tick_log.clear()
        self._record_tick(
            kind="started", moves=[], changes=[],
            note=(f"{scenario_slug} · seed={seed_mode} · "
                  f"{len(self._holdings_rows)} holdings · "
                  f"{len(self._positions_rows)} positions"),
        )
        self.active = True
        logger.warning(
            f"[SIMULATOR] Started scenario={scenario_slug} seed={seed_mode} "
            f"rate={self.rate_ms}ms agents={self.only_agent_ids or 'all'}"
        )
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
            kind="stopped", moves=[], changes=[],
            note=f"Stopped after {self.tick_index} ticks",
        )
        logger.warning(f"[SIMULATOR] Stopped after {self.tick_index} ticks")
        return self.snapshot()

    def step(self) -> dict:
        """Apply one tick (for deterministic debugging)."""
        assert_enabled()
        if not self.scenario:
            raise SimGuardError("No scenario loaded. Call start(...) first.")
        self._apply_next_tick()
        return self.snapshot()

    async def _run_loop(self) -> None:
        """Async loop driving the scenario at `rate_ms` cadence."""
        try:
            while self.active:
                if datetime.now() - self.started_at > AUTO_STOP_AFTER:
                    logger.warning("[SIMULATOR] Auto-stop after 30 min")
                    self.stop()
                    return
                self._apply_next_tick()
                await self._run_cycle_once()
                await asyncio.sleep(self.rate_ms / 1000)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SIMULATOR] Loop crashed: {e}")
            self.active = False

    # Long-lived alert_state for the simulator — kept separate from the real
    # background task's state so rate-history and suppression don't cross.
    _sim_alert_state: dict = {"sim_mode": True}

    async def _run_cycle_once(self) -> None:
        """Invoke the agent engine against the current sim state."""
        try:
            from backend.api.algo.agent_engine import run_cycle
            from backend.api.routes.algo import _broadcast_event
            from backend.shared.helpers.date_time_utils import (
                timestamp_display, timestamp_indian,
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
                "sim_mode":       True,
            }
            await run_cycle(
                ctx, _broadcast_event,
                only_agent_ids=self.only_agent_ids,
                bypass_schedule=True,   # sim is always "out of hours" for market_hours agents
            )
        except Exception as e:
            logger.error(f"[SIMULATOR] run_cycle failed: {e}")

    # ── Tick + move application ──────────────────────────────────────

    def _apply_next_tick(self) -> None:
        """Apply the next tick in the scenario (wraps at end)."""
        if not self.scenario:
            return
        ticks = self.scenario.get("ticks", []) or []
        if not ticks:
            return
        tick = ticks[self.tick_index % len(ticks)]

        # A tick may carry `moves` (Model B, price-level) or `patch` (legacy
        # aggregate). We support both — moves take precedence.
        moves = tick.get("moves") or []
        if not moves and tick.get("patch"):
            # Legacy aggregate patch — apply directly to matching account row.
            changes = self._apply_legacy_patch(tick["patch"])
        else:
            changes = self._apply_moves(moves)

        self.tick_index += 1
        self._record_tick(kind="tick", moves=moves, changes=changes)

    def _iter_rows(self, section: str):
        """Yield (row, section) pairs for a given section name."""
        if section == "holdings":
            return self._holdings_rows
        if section == "positions":
            return self._positions_rows
        if section == "margins":
            return self._margins_rows
        return []

    def _apply_moves(self, moves: list[dict]) -> list[dict]:
        """Apply a list of price moves and return change diffs for the tick log."""
        changes: list[dict] = []
        for move in moves:
            mtype = (move.get("type") or "").lower()
            scope = move.get("scope") or ""
            if mtype == "set_margin":
                changes.extend(self._apply_set_margin(scope, move))
                continue
            matched = self._scope_matches(scope)
            if not matched:
                logger.info(f"[SIMULATOR] move {mtype} scope='{scope}' matched nothing")
                continue
            if mtype == "pct":
                changes.extend(self._apply_pct(matched, float(move.get("value") or 0)))
            elif mtype == "abs":
                changes.extend(self._apply_abs(matched, float(move.get("value") or 0)))
            elif mtype == "random_walk":
                drift = float(move.get("drift") or 0.0)
                vol   = float(move.get("vol")   or 0.0)
                changes.extend(self._apply_random_walk(matched, drift, vol))
            elif mtype == "target_pnl":
                target = float(move.get("value") or 0)
                changes.extend(self._apply_target_pnl(matched, target))
            else:
                logger.warning(f"[SIMULATOR] unknown move type '{mtype}'")
        return changes

    def _scope_matches(self, scope: str) -> list[tuple[str, dict]]:
        """Return every (section, row) pair whose path matches the glob."""
        out: list[tuple[str, dict]] = []
        section = scope.split(".", 1)[0]
        for row in self._iter_rows(section):
            acct = str(row.get("account", ""))
            sym  = str(row.get("tradingsymbol", ""))
            if _match_glob(scope, section, acct, sym):
                out.append((section, row))
        return out

    def _apply_pct(self, matched: list[tuple[str, dict]], pct: float) -> list[dict]:
        changes = []
        for section, row in matched:
            prev = float(row.get("last_price") or 0)
            new  = prev * (1.0 + pct)
            row["last_price"] = new
            self._refresh(section, row)
            changes.append(self._change(section, row, prev, new, reason=f"pct {pct*100:+.2f}%"))
        return changes

    def _apply_abs(self, matched: list[tuple[str, dict]], delta: float) -> list[dict]:
        changes = []
        for section, row in matched:
            prev = float(row.get("last_price") or 0)
            new  = prev + delta
            row["last_price"] = new
            self._refresh(section, row)
            changes.append(self._change(section, row, prev, new, reason=f"abs {delta:+.2f}"))
        return changes

    def _apply_random_walk(self, matched: list[tuple[str, dict]],
                            drift: float, vol: float) -> list[dict]:
        changes = []
        for section, row in matched:
            prev = float(row.get("last_price") or 0)
            shock = drift + vol * self._rng.gauss(0.0, 1.0)
            new  = prev * (1.0 + shock)
            row["last_price"] = new
            self._refresh(section, row)
            changes.append(self._change(section, row, prev, new,
                                        reason=f"walk drift={drift:+.4f} vol={vol:.4f}"))
        return changes

    def _apply_target_pnl(self, matched: list[tuple[str, dict]], target: float) -> list[dict]:
        """
        Drive the matched rows' aggregate pnl toward `target` by moving each
        LTP uniformly. Solves `ΔLTP × Σqty = target − currentPnl`. Rejects
        mixed-sign position sets (long + short) where a uniform ΔLTP makes
        no physical sense — documented in the Model-B plan.
        """
        if not matched:
            return []
        qty_sum = 0.0
        cur_pnl_sum = 0.0
        signs = set()
        for _, row in matched:
            q = float(row.get("quantity") or row.get("opening_quantity") or 0)
            qty_sum += q
            cur_pnl_sum += float(row.get("pnl") or 0)
            if q != 0:
                signs.add(1 if q > 0 else -1)
        if len(signs) > 1:
            logger.warning("[SIMULATOR] target_pnl refused — scope has mixed long/short")
            return []
        if qty_sum == 0:
            return []
        delta_ltp = (target - cur_pnl_sum) / qty_sum
        changes = []
        for section, row in matched:
            prev = float(row.get("last_price") or 0)
            new  = prev + delta_ltp
            row["last_price"] = new
            self._refresh(section, row)
            changes.append(self._change(section, row, prev, new,
                                        reason=f"target_pnl={target:.0f}"))
        return changes

    def _apply_set_margin(self, scope: str, move: dict) -> list[dict]:
        """
        Direct margin patch — price-decoupled by design. `scope` is
        `margins.<account>` and `fields` is a dict of column overrides.
        """
        changes = []
        parts = scope.split(".", 1)
        if len(parts) != 2 or parts[0] != "margins":
            logger.warning(f"[SIMULATOR] set_margin bad scope '{scope}'")
            return changes
        acct_glob = parts[1]
        fields = move.get("fields") or {}
        for row in self._margins_rows:
            if not fnmatch.fnmatchcase(str(row.get("account", "")), acct_glob):
                continue
            for k, v in fields.items():
                prev = row.get(k)
                row[k] = v
                changes.append({
                    "section": "margins", "account": row.get("account"), "symbol": "",
                    "col": k, "prev": prev, "next": v,
                    "delta": (v - prev) if isinstance(prev, (int, float)) and isinstance(v, (int, float)) else None,
                    "reason": "set_margin",
                })
        return changes

    def _refresh(self, section: str, row: dict) -> None:
        if section == "holdings":
            _recompute_holding_row(row)
        elif section == "positions":
            _recompute_position_row(row)

    def _change(self, section: str, row: dict, prev: float, new: float,
                *, reason: str) -> dict:
        return {
            "section": section,
            "account": row.get("account"),
            "symbol":  row.get("tradingsymbol", ""),
            "col":     "last_price",
            "prev":    prev,
            "next":    new,
            "delta":   new - prev,
            "reason":  reason,
        }

    # ── Legacy aggregate patch (kept so older scenarios still work) ───

    def _apply_legacy_patch(self, patch: dict) -> list[dict]:
        """
        Apply a flat-dotted-key patch (old Model-A shape). Kept so scenarios
        written before the price-driver cutover keep working — the sim
        mutates the per-symbol state if the row exists, else synthesises an
        aggregate stub row.
        """
        changes: list[dict] = []
        for key, val in patch.items():
            parts = key.split(".", 2)
            if len(parts) != 3:
                logger.warning(f"[SIMULATOR] malformed legacy patch key '{key}'")
                continue
            section, account, col = parts
            rows = {
                "holdings":  self._holdings_rows,
                "positions": self._positions_rows,
                "margins":   self._margins_rows,
            }.get(section)
            if rows is None:
                logger.warning(f"[SIMULATOR] unknown section '{section}' in patch")
                continue
            match = next((r for r in rows if r.get("account") == account), None)
            if match is None:
                match = {"account": account}
                rows.append(match)
            prev = match.get(col)
            match[col] = val
            changes.append({
                "section": section, "account": account, "symbol": "",
                "col": col, "prev": prev, "next": val,
                "delta": (val - prev) if isinstance(prev, (int, float)) and isinstance(val, (int, float)) else None,
                "reason": "legacy-patch",
            })
        return changes

    # ── Live-book seeding ────────────────────────────────────────────

    def seed_live(self) -> dict:
        """
        Snapshot the real book (fresh broker fetch, bypass cache) into the
        driver's `_live_snapshot` field so a subsequent start(..., seed_mode=
        'live'|'live+scenario') can use it as the initial state. Returns a
        small manifest (counts + timestamp) for the UI preview.
        """
        assert_enabled()
        from backend.shared.helpers import broker_apis
        from backend.shared.helpers.utils import mask_column

        try:
            df_h = pd.concat(broker_apis.fetch_holdings(),  ignore_index=True)
            df_p = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
            df_m = pd.concat(broker_apis.fetch_margins(),   ignore_index=True)
        except Exception as e:
            raise SimGuardError(f"Live-book fetch failed: {e}")

        for df in (df_h, df_p, df_m):
            if not df.empty and "account" in df.columns:
                df["account"] = mask_column(df["account"])

        holdings  = df_h.fillna(0).to_dict(orient="records")  if not df_h.empty else []
        positions = df_p.fillna(0).to_dict(orient="records") if not df_p.empty else []
        margins   = df_m.fillna(0).to_dict(orient="records") if not df_m.empty else []

        # Holdings / positions rely on `last_price`, `average_price`,
        # `close_price`, `opening_quantity` or `quantity`. Coerce missing
        # numeric fields to zero so recompute_* doesn't blow up.
        for row in holdings:
            row.setdefault("opening_quantity", row.get("quantity") or 0)
            row.setdefault("close_price", row.get("last_price") or 0)
            _recompute_holding_row(row)
        for row in positions:
            _recompute_position_row(row)

        self._live_snapshot = {
            "holdings":    holdings,
            "positions":   positions,
            "margins":     margins,
            "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        }
        logger.info(
            f"[SIMULATOR] seed-live: {len(holdings)} holdings / "
            f"{len(positions)} positions / {len(margins)} margins snapshotted"
        )
        return {
            "snapshot_at":     self._live_snapshot["snapshot_at"],
            "holdings_count":  len(holdings),
            "positions_count": len(positions),
            "margins_count":   len(margins),
            "accounts":        sorted({str(r.get("account", "")) for r in holdings + positions + margins if r.get("account")}),
        }

    # ── Tick log ─────────────────────────────────────────────────────

    def _record_tick(self, *, kind: str, moves: list, changes: list[dict],
                     note: str = "") -> None:
        self._tick_log.append({
            "ts":         datetime.now().isoformat(timespec="seconds"),
            "tick_index": self.tick_index,
            "scenario":   self.scenario_slug,
            "kind":       kind,
            "moves":      moves,
            "changes":    changes,
            "note":       note,
        })

    def recent_ticks(self, limit: int = 100) -> list[dict]:
        """Return the most recent `limit` ticks (oldest-first)."""
        limit = max(1, min(int(limit), TICK_LOG_LIMIT))
        return list(self._tick_log)[-limit:]

    # ── Convenience ──────────────────────────────────────────────────

    def scenarios_manifest(self) -> list[dict]:
        out = []
        for s in load_scenarios():
            out.append({
                "slug":        s.get("slug"),
                "name":        s.get("name") or s.get("slug"),
                "description": s.get("description", ""),
                "mode":        s.get("mode") or ("symbol" if s.get("ticks", [{}])[0].get("moves") else "aggregate"),
                "ticks":       len(s.get("ticks", []) or []),
            })
        return out


def get_driver() -> SimDriver:
    return SimDriver.instance()
