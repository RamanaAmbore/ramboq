"""
Market-price simulation driver for /api/simulator/*.

**Positions-only simulator.** Holdings are intentionally not part of the
simulation — intraday risk lives in F&O positions + fund negatives, which
is what this exercises end-to-end. Agents checking holdings metrics
(day_pct, day_rate_abs, day_rate_pct) run against live production data
only; the synthesizer refuses to build a scenario for them.

Design goals
  1. **Price-driver, not aggregate-driver.** Each tick moves per-symbol
     `last_price` on positions; `pnl` is recomputed from it. The agent
     engine sees `sum_positions` + `df_margins` in the same shape as the
     live path. `sum_holdings` is always an empty frame.
  2. **No code branches in the hot path.** The agent engine, dispatcher and
     action handlers are unaware that data came from here — they read
     `sim_mode` off `alert_state` and prepend `[SIM]` where needed.
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
TICK_LOG_LIMIT = 200


# Market-state presets the simulator exposes to scenarios + the UI. Each
# preset maps to the segment-flag + minutes-since-open/close overrides
# `_build_context()` will respect, so time-aware agents (rate rules with
# baseline gates, minutes_until_close conditions, expiry rules) fire
# against a simulated clock instead of wall-clock time.
MARKET_STATE_PRESETS: dict[str, dict] = {
    "pre_open":     {"nse_open": False, "mcx_open": False,
                     "minutes_since_nse_open": 0,   "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 0,   "minutes_since_mcx_close": 0,
                     "is_expiry_day": False},
    "at_open":      {"nse_open": True,  "mcx_open": True,
                     "minutes_since_nse_open": 1,   "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 1,   "minutes_since_mcx_close": 0,
                     "is_expiry_day": False},
    "mid_session":  {"nse_open": True,  "mcx_open": True,
                     "minutes_since_nse_open": 180, "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 180, "minutes_since_mcx_close": 0,
                     "is_expiry_day": False},
    "pre_close":    {"nse_open": True,  "mcx_open": True,
                     "minutes_since_nse_open": 360, "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 360, "minutes_since_mcx_close": 0,
                     "is_expiry_day": False},
    "at_close":     {"nse_open": False, "mcx_open": True,
                     "minutes_since_nse_open": 375, "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 375, "minutes_since_mcx_close": 0,
                     "is_expiry_day": False},
    "post_close":   {"nse_open": False, "mcx_open": False,
                     "minutes_since_nse_open": 375, "minutes_since_nse_close": 60,
                     "minutes_since_mcx_open": 375, "minutes_since_mcx_close": 60,
                     "is_expiry_day": False},
    # Thursday expiry scenario — mid-session on the day the weekly options
    # settle. Flips is_expiry_day so expiry auto-close agents engage.
    "expiry_day":   {"nse_open": True,  "mcx_open": True,
                     "minutes_since_nse_open": 240, "minutes_since_nse_close": 0,
                     "minutes_since_mcx_open": 240, "minutes_since_mcx_close": 0,
                     "is_expiry_day": True},
}


def _resolve_market_state(spec: dict | None) -> dict:
    """
    Turn a scenario's `market_state` block (or a runtime UI override)
    into a flat dict of overrides consumable by _build_context. Unknown
    presets fall back to mid_session and log a warning.
    """
    if not spec:
        return dict(MARKET_STATE_PRESETS["mid_session"])
    out: dict = {}
    preset = spec.get("preset") if isinstance(spec, dict) else None
    if preset:
        if preset not in MARKET_STATE_PRESETS:
            logger.warning(
                f"[SIM] Unknown market_state preset '{preset}' — "
                f"using mid_session. Valid: {list(MARKET_STATE_PRESETS)}"
            )
            preset = "mid_session"
        out.update(MARKET_STATE_PRESETS[preset])
    # Explicit fields in the spec override the preset (e.g. "use pre_close
    # but flip is_expiry_day").
    for k, v in (spec or {}).items():
        if k == "preset":
            continue
        out[k] = v
    return out


def _auto_stop_after() -> timedelta:
    """Read auto-stop window from DB settings each time (falls back to 30 min)."""
    from backend.shared.helpers.settings import get_int
    return timedelta(minutes=get_int("simulator.auto_stop_minutes", 30))


def _positions_every_default() -> int:
    from backend.shared.helpers.settings import get_int
    return get_int("simulator.positions_every_n_ticks", 1)


# Compatibility shim for callers that still reference the old name.
POSITIONS_UPDATE_EVERY_DEFAULT = 1
AUTO_STOP_AFTER                = timedelta(minutes=30)


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

def _recompute_position_row(row: dict, spread_pct: float = 0.0) -> None:
    """
    Mutate a positions row in-place: keep `pnl` / `bid` / `ask` consistent
    with the current `last_price`. Real Kite `pnl` includes realised + m2m;
    for the simulator we use the simple model
    `(last_price - average_price) × quantity` because that's what the
    loss-* agents read. `bid` / `ask` are derived from `spread_pct` (a
    decimal fraction — 0.001 = 0.10% spread) so paper-trade limit prices
    can pick the correct side of the market.
    """
    qty = float(row.get("quantity")       or 0)
    avg = float(row.get("average_price")  or 0)
    lp  = float(row.get("last_price")     or 0)
    row["pnl"] = (lp - avg) * qty
    half = max(0.0, float(spread_pct)) / 2.0
    row["bid"] = lp * (1.0 - half) if lp else 0.0
    row["ask"] = lp * (1.0 + half) if lp else 0.0


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
        # Positions tick cadence — how often positions' LTPs refresh. 1 =
        # every tick. Resolved at start() from request override, scenario
        # YAML, or DB setting `simulator.positions_every_n_ticks`.
        self.positions_every_n_ticks: int = POSITIONS_UPDATE_EVERY_DEFAULT
        # Simulated market state — dict of overrides passed into run_cycle's
        # _build_context so time-aware agents see a simulated clock. Keyed
        # by preset or explicit fields; see MARKET_STATE_PRESETS.
        self.market_state: dict = dict(MARKET_STATE_PRESETS["mid_session"])
        self.market_state_preset: str = "mid_session"
        self._task: Optional[asyncio.Task] = None

        # Running per-symbol state. Holdings is deliberately unused (empty
        # forever) — positions-only sim. Kept here so `dataframes()` can
        # still return a valid empty sum_holdings frame.
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

        # Bid/ask spread (decimal fraction — 0.001 = 0.10%). Applied on
        # every _recompute_position_row so every position carries per-side
        # prices. Resolved at start() from the request override or the DB
        # setting `simulator.default_spread_pct`.
        self.spread_pct: float = 0.0

        # Paper trade engine — owns the open-order book, fill / modify /
        # unfilled lifecycle, AlgoOrder DB writes. Fed by SimQuoteSource
        # so it reads bid/ask from this driver's `_positions_rows` (the
        # fabricated book). Mode 2 (real-data paper on prod) constructs
        # its own PaperTradeEngine fed by LiveQuoteSource — same engine,
        # different quote source.
        from backend.api.algo.paper      import PaperTradeEngine
        from backend.api.algo.quote      import SimQuoteSource
        self._paper = PaperTradeEngine(
            quote_source=SimQuoteSource(self),
            label="sim",
            on_event=self._forward_chase_event,
        )

    @classmethod
    def instance(cls) -> "SimDriver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public state snapshot ─────────────────────────────────────────

    def _tick_pcts_for_ui(self) -> list[float | None]:
        """
        Extract per-tick pct values from the currently-loaded scenario so
        the /admin/simulator page can render them as editable defaults.
        Returns a list the length of scenario.ticks; each entry is the
        first `pct`-move's value in that tick, or None when the tick has
        no pct move (e.g. the tick is target_pnl / set_margin).
        """
        if not self.scenario:
            return []
        out: list[float | None] = []
        for t in (self.scenario.get("ticks") or []):
            pct = None
            for m in (t.get("moves") or []):
                if (m.get("type") or "").lower() == "pct":
                    try:
                        pct = float(m.get("value"))
                    except (TypeError, ValueError):
                        pct = None
                    break
            out.append(pct)
        return out

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
            "positions_every_n_ticks": self.positions_every_n_ticks,
            "market_state_preset":     self.market_state_preset,
            "market_state":            dict(self.market_state),
            # Tick pct values actually running (after overrides applied) —
            # lets the UI reflect "what's active" even if the operator
            # changes the inputs after Start.
            "tick_pcts":               self._tick_pcts_for_ui(),
            "symbol_filter":           [r.get("tradingsymbol") for r in self._positions_rows]
                                        if self.scenario else [],
            # Distinct tradingsymbols currently loaded. Lets the UI keep the
            # Symbol picker fresh even when the operator started without
            # pressing "Load live book" first.
            "symbols":                 sorted({
                                           str(r.get("tradingsymbol", ""))
                                           for r in self._positions_rows
                                           if r.get("tradingsymbol")
                                       }),
            # Compact per-position snapshot — the Simulator page renders
            # this as a small pill list so operators see fills actually
            # remove rows from the book (not just a shrinking counter).
            "positions":               [
                {
                    "account":   r.get("account"),
                    "symbol":    r.get("tradingsymbol"),
                    "quantity":  r.get("quantity"),
                    "last_price": r.get("last_price"),
                    "bid":       r.get("bid"),
                    "ask":       r.get("ask"),
                    "pnl":       r.get("pnl"),
                }
                for r in self._positions_rows
            ],
            # Open-order snapshots — one per in-flight chase. Mirrors the
            # chase engine's internal state so the Simulator page can show
            # "NIFTY BUY 50 @ ₹21,800 · attempt 2/5" live.
            "open_order_details":      self._paper.open_order_details(),
            "spread_pct":              self.spread_pct,
            "open_orders":             len(self._paper.open_order_details()),
        }

    # ── DataFrame builder the agent engine consumes ───────────────────

    def dataframes(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Return (sum_holdings, sum_positions, df_margins) in the exact shape
        the real background task feeds into run_cycle. sum_holdings is
        always empty (positions-only sim); sum_positions uses the same
        summarise helper the live path uses so rounding matches.
        """
        from backend.shared.helpers.summarise import summarise_positions

        df_p_raw = pd.DataFrame(self._positions_rows) if self._positions_rows else pd.DataFrame()

        # Holdings-based agents (loss-hold-*) will see zero rows and
        # therefore never fire in the sim. That's the point — they're
        # untestable by design here; they only evaluate against live data.
        sum_h = pd.DataFrame(columns=["account", "inv_val", "cur_val", "pnl", "day_change_val"])
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
              only_agent_ids: list[int] | None = None,
              positions_every_n_ticks: int | None = None,
              market_state_override: dict | None = None,
              inline_scenario: dict | None = None,
              pct_overrides: list[float] | None = None,
              symbol_filter: list[str] | None = None,
              spread_pct: float | None = None) -> dict:
        """
        Start the sim against a named scenario from scenarios.yaml, or an
        `inline_scenario` dict (same shape) built at call time by the
        synthesiser. Inline scenarios do not live in the YAML catalog —
        useful for per-agent auto-generated tests.
        """
        assert_enabled()
        if self.active:
            raise SimGuardError("Sim is already running — stop it first.")
        if inline_scenario is not None:
            scen = inline_scenario
            scenario_slug = scen.get("slug") or scenario_slug
        else:
            scen = get_scenario(scenario_slug)
            if not scen:
                raise SimGuardError(f"Unknown scenario '{scenario_slug}'")

        # Apply pct_overrides into the scenario's ticks before we store
        # it. The shape we handle cleanly: every override slot [i] replaces
        # the `value` of every `pct`-typed move in ticks[i].moves. Scenarios
        # that don't match this shape (random_walk, target_pnl, set_margin)
        # are unaffected by pct_overrides — those moves are left alone.
        if pct_overrides:
            scen = copy.deepcopy(scen)
            for i, pct in enumerate(pct_overrides):
                if pct is None:
                    continue
                ticks = scen.get("ticks") or []
                if i >= len(ticks):
                    break
                for move in (ticks[i].get("moves") or []):
                    if (move.get("type") or "").lower() == "pct":
                        try:
                            move["value"] = float(pct)
                        except (TypeError, ValueError):
                            pass

        self.scenario_slug  = scenario_slug
        self.scenario       = scen
        self.seed_mode      = seed_mode
        self.rate_ms        = max(200, int(rate_ms))
        self.tick_index     = 0
        self.started_at     = datetime.now()
        self.only_agent_ids = list(only_agent_ids) if only_agent_ids else None
        self._paper.reset()

        # Spread — request override > scenario YAML > DB setting. Stored as
        # a decimal fraction internally (0.001 = 0.10%). The UI submits a
        # percent (0.10) which the route layer converts before calling us.
        from backend.shared.helpers.settings import get_float
        raw_sp = (spread_pct
                  if spread_pct is not None
                  else scen.get("spread_pct",
                                get_float("simulator.default_spread_pct", 0.10) / 100.0))
        try:
            self.spread_pct = max(0.0, float(raw_sp))
        except (TypeError, ValueError):
            self.spread_pct = 0.0

        # Positions cadence — request override > scenario YAML > DB default.
        # Clamped to >= 1 so nothing ever gets divided by zero or silenced.
        raw_pos = (positions_every_n_ticks
                   if positions_every_n_ticks is not None
                   else scen.get("positions_every_n_ticks", _positions_every_default()))
        try:
            self.positions_every_n_ticks = max(1, int(raw_pos))
        except (TypeError, ValueError):
            self.positions_every_n_ticks = _positions_every_default()

        # Market-state resolution — request override > scenario YAML > default.
        # Both accept the same shape: {preset: "…"} or explicit fields.
        spec = market_state_override if market_state_override else scen.get("market_state")
        self.market_state = _resolve_market_state(spec)
        self.market_state_preset = (
            (spec or {}).get("preset")
            if isinstance(spec, dict) and spec.get("preset") in MARKET_STATE_PRESETS
            else "mid_session"
        )

        # Seed the running state — either from scenario.initial, the live-book
        # snapshot, or both stacked. For the live modes, auto-snapshot if the
        # operator hasn't pressed "Load live book" yet. Holdings is a no-op
        # here (positions-only sim) — we ignore any `initial.holdings` the
        # scenario might still carry.
        self._holdings_rows = []   # always empty — positions-only sim
        if seed_mode in ("live", "live+scenario"):
            if not self._live_snapshot:
                try:
                    self.seed_live()
                except Exception as e:
                    raise SimGuardError(
                        f"Auto-seed of live book failed: {e}. "
                        f"Try POST /api/simulator/seed-live manually to surface "
                        f"the broker error."
                    )
            self._positions_rows = copy.deepcopy(self._live_snapshot["positions"])
            self._margins_rows   = copy.deepcopy(self._live_snapshot["margins"])

        if seed_mode in ("scripted", "live+scenario"):
            initial = scen.get("initial") or {}
            if seed_mode == "scripted":
                self._positions_rows = copy.deepcopy(initial.get("positions", []))
                self._margins_rows   = copy.deepcopy(initial.get("margins", []))
            else:
                # live+scenario — scripted initial rows are layered on top of
                # the live snapshot (useful for injecting a specific symbol).
                self._positions_rows.extend(copy.deepcopy(initial.get("positions", [])))
                self._margins_rows.extend(copy.deepcopy(initial.get("margins", [])))

        for r in self._positions_rows:
            _recompute_position_row(r, self.spread_pct)

        # Symbol filter — drop positions whose tradingsymbol isn't in the
        # requested allow-list. Operators use this to target a single
        # instrument (e.g. "simulate only my NIFTY short"). Empty / None
        # means no filter. Applied AFTER recompute so the filtered set
        # still has derived fields intact.
        if symbol_filter:
            allow = {str(s) for s in symbol_filter if s}
            if allow:
                self._positions_rows = [
                    r for r in self._positions_rows
                    if str(r.get("tradingsymbol", "")) in allow
                ]

        # When scripted seeding leaves the state empty (a scenario without
        # an `initial:` block — all 5 shipped ones + every synthesized
        # scenario), auto-upgrade to live+scenario and snapshot the real
        # book. Saves the operator from having to flip seed_mode manually
        # every time they press Start. Only reachable in `scripted` mode;
        # live / live+scenario paths already seeded earlier.
        if seed_mode == "scripted" and not (self._positions_rows or self._margins_rows):
            logger.info(
                f"[SIM] '{scenario_slug}' has no scripted initial — "
                f"auto-loading live book."
            )
            try:
                if not self._live_snapshot:
                    self.seed_live()
                self._positions_rows = copy.deepcopy(self._live_snapshot["positions"])
                self._margins_rows   = copy.deepcopy(self._live_snapshot["margins"])
                for r in self._positions_rows:
                    _recompute_position_row(r)
                self.seed_mode = "live"   # reflect what actually happened
            except Exception as e:
                self.scenario = None
                self.active   = False
                raise SimGuardError(
                    f"Scenario '{scenario_slug}' has no scripted initial state "
                    f"and auto-load of live book failed: {e}"
                )

        if not (self._positions_rows or self._margins_rows):
            self.scenario = None
            self.active   = False
            raise SimGuardError(
                f"Scenario '{scenario_slug}' has no initial state and the live "
                f"book returned no positions or margins. Nothing to simulate."
            )

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
            f"[SIM] Started scenario={scenario_slug} seed={seed_mode} "
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
        logger.warning(f"[SIM] Stopped after {self.tick_index} ticks")
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
            auto_stop = _auto_stop_after()
            while self.active:
                if datetime.now() - self.started_at > auto_stop:
                    logger.warning(f"[SIM] Auto-stop after {auto_stop}")
                    self.stop()
                    return
                self._apply_next_tick()
                await self._run_cycle_once()
                await asyncio.sleep(self.rate_ms / 1000)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SIM] Loop crashed: {e}")
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
                # Simulated clock + segment flags — picked up by run_cycle →
                # _build_context so time-aware agents evaluate against the
                # scenario's market state, not wall-clock time.
                "market_state":   dict(self.market_state),
            }
            # Isolated ("Run in Simulator" per-agent) runs want every tick
            # to fire so the operator gets immediate feedback — they bypass
            # suppression. General sim runs keep suppression on so the same
            # breach doesn't fire on every tick.
            isolated = bool(self.only_agent_ids)
            await run_cycle(
                ctx, _broadcast_event,
                only_agent_ids=self.only_agent_ids,
                bypass_schedule=True,
                bypass_suppression=isolated,
            )
        except Exception as e:
            logger.error(f"[SIM] run_cycle failed: {e}")

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
        # Run the chase engine against the new bid/ask state: fill any
        # orders whose limit crossed, otherwise re-quote them one step
        # closer to the opposite side.
        self._paper.step()
        # If every position has closed out (either via fills or because the
        # operator scoped the sim to an empty symbol list), there's nothing
        # left to simulate — halt cleanly with a terminal log entry so the
        # operator knows why the loop exited.
        self._check_auto_complete()

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
        # Positions-only sim: positions refresh every Nth tick per the
        # cadence setting; holdings scope globs are silently skipped (we
        # don't carry holdings state). Tick 0 always refreshes so market
        # open feels right.
        positions_tick = (self.tick_index % self.positions_every_n_ticks) == 0
        for move in moves:
            mtype = (move.get("type") or "").lower()
            scope = move.get("scope") or ""
            if mtype == "set_margin":
                changes.extend(self._apply_set_margin(scope, move))
                continue
            if scope.startswith("holdings."):
                logger.debug(f"[SIM] ignoring holdings scope '{scope}' (positions-only sim)")
                continue
            if scope.startswith("positions.") and not positions_tick:
                continue
            matched = self._scope_matches(scope)
            if not matched:
                logger.info(f"[SIM] move {mtype} scope='{scope}' matched nothing")
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
                logger.warning(f"[SIM] unknown move type '{mtype}'")
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
            logger.warning("[SIM] target_pnl refused — scope has mixed long/short")
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
            logger.warning(f"[SIM] set_margin bad scope '{scope}'")
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
        # holdings is never populated — positions-only sim. Any future
        # section gets silently ignored here.
        if section == "positions":
            _recompute_position_row(row, self.spread_pct)

    # ── Paper-trade chase engine (delegated to PaperTradeEngine) ─────

    def register_open_order(self, order: dict) -> None:
        """
        Called by `_sim_paper_trade` after the initial AlgoOrder row is
        persisted. Forwards into the PaperTradeEngine the driver was
        constructed with — kept on SimDriver as a thin facade so
        existing callers (`actions.py::_write_sim_order`) don't need to
        know the engine was lifted out.
        """
        self._paper.register_open_order(order)

    def _forward_chase_event(self, evt: dict) -> None:
        """
        Translate PaperTradeEngine events into the simulator's tick-log
        shape so the Simulator log panel keeps rendering chase progress
        the same way it always has. Mode 2's standalone PaperTradeEngine
        keeps its own buffer; only the simulator forwards into the
        scenario tick stream.
        """
        order = evt.get("order") or {}
        self._tick_log.append({
            "ts":         evt.get("ts") or datetime.now().isoformat(timespec="seconds"),
            "tick_index": self.tick_index,
            "scenario":   self.scenario_slug,
            "kind":       evt.get("kind"),
            "moves":      [],
            "changes":    [],
            "note":       evt.get("note"),
            "order":      order,
        })

    def _check_auto_complete(self) -> None:
        """
        Halt the sim when there's nothing left to simulate. Two triggers:
          - _positions_rows is empty (every position closed out — either
            via chase fills or a symbol filter that matched nothing), AND
          - no OPEN sim orders remain (so we're not mid-chase)
        Records a 'completed' entry in the tick log before stopping so the
        operator sees why the loop exited.
        """
        if not self.active:
            return
        if self._positions_rows or self._paper.has_open_orders():
            return
        self._record_tick(
            kind="completed", moves=[], changes=[],
            note="Simulation complete — no positions left to simulate.",
        )
        logger.warning("[SIM] Auto-completed — no positions remaining")
        self.active = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

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
            # Derived bid/ask included so the tick log panel can show the
            # spread that each position currently quotes.
            "bid":     row.get("bid"),
            "ask":     row.get("ask"),
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
                logger.warning(f"[SIM] malformed legacy patch key '{key}'")
                continue
            section, account, col = parts
            rows = {
                "holdings":  self._holdings_rows,
                "positions": self._positions_rows,
                "margins":   self._margins_rows,
            }.get(section)
            if rows is None:
                logger.warning(f"[SIM] unknown section '{section}' in patch")
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
        Snapshot positions + margins from the real book into the driver's
        `_live_snapshot` field. Holdings are NOT fetched — positions-only
        sim. Returns a small manifest for the UI preview.
        """
        assert_enabled()
        from backend.shared.helpers import broker_apis

        try:
            df_p = pd.concat(broker_apis.fetch_positions(), ignore_index=True)
            df_m = pd.concat(broker_apis.fetch_margins(),   ignore_index=True)
        except Exception as e:
            raise SimGuardError(f"Live-book fetch failed: {e}")

        # Keep real account codes in the sim book — Telegram + email sim
        # alerts go to the owner and reading `ZG####` everywhere made it
        # impossible to tell which account fired. Public sim endpoints
        # are admin-guarded, so there's no leak path.

        positions = df_p.fillna(0).to_dict(orient="records") if not df_p.empty else []
        margins   = df_m.fillna(0).to_dict(orient="records") if not df_m.empty else []

        for row in positions:
            _recompute_position_row(row)

        self._live_snapshot = {
            "holdings":    [],   # kept key for shape compatibility
            "positions":   positions,
            "margins":     margins,
            "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        }
        logger.info(
            f"[SIM] seed-live: {len(positions)} positions / "
            f"{len(margins)} margins snapshotted (holdings skipped — positions-only sim)"
        )
        return {
            "snapshot_at":     self._live_snapshot["snapshot_at"],
            "positions_count": len(positions),
            "margins_count":   len(margins),
            "accounts":        sorted({str(r.get("account", "")) for r in positions + margins if r.get("account")}),
            # Distinct tradingsymbols in the snapshot — populates the
            # Symbol picker on /admin/simulator.
            "symbols":         sorted({str(r.get("tradingsymbol", ""))
                                       for r in positions if r.get("tradingsymbol")}),
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
            initial = s.get("initial") or {}
            has_initial = bool(
                initial.get("holdings") or initial.get("positions") or initial.get("margins")
            )
            # Default tick pct values — same shape as _tick_pcts_for_ui
            # above. Lets the UI show editable defaults before Start.
            tick_pcts: list[float | None] = []
            for t in (s.get("ticks") or []):
                pct = None
                for m in (t.get("moves") or []):
                    if (m.get("type") or "").lower() == "pct":
                        try:
                            pct = float(m.get("value"))
                        except (TypeError, ValueError):
                            pass
                        break
                tick_pcts.append(pct)
            # Distinct symbols from the scenario's scripted initial
            # positions — lets the Symbol picker show picker options
            # even when the operator hasn't loaded the live book yet.
            init_syms = sorted({
                str(p.get("tradingsymbol", ""))
                for p in (initial.get("positions") or [])
                if p.get("tradingsymbol")
            })
            out.append({
                "slug":            s.get("slug"),
                "name":            s.get("name") or s.get("slug"),
                "description":     s.get("description", ""),
                "mode":            s.get("mode") or ("symbol" if s.get("ticks", [{}])[0].get("moves") else "aggregate"),
                "ticks":           len(s.get("ticks", []) or []),
                "has_initial":     has_initial,
                "tick_pcts":       tick_pcts,
                "initial_symbols": init_syms,
            })
        return out


def get_driver() -> SimDriver:
    return SimDriver.instance()
