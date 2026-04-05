"""
Expiry-day auto-close engine.

Identifies ITM/NTM option positions on expiry day and closes them using
the chase engine before market close.

Key rules:
  - Equity (NFO): close ALL ITM + NTM options (within buffer %)
  - Commodity (MCX): close only UNBALANCED ITM legs (hedged pairs are safe)
  - Expiry may shift due to holidays — use instrument expiry date, not weekday
  - NSE and MCX have different expiry schedules and market hours
  - Re-scan every 30 min for positions that become ITM during the day

Usage:
    engine = ExpiryEngine(on_event=callback)
    await engine.run()  # blocks until market close
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable, Optional

from backend.shared.helpers import broker_apis
from backend.shared.helpers.connections import Connections
from backend.shared.helpers.date_time_utils import timestamp_indian, timestamp_display, is_market_open
from backend.shared.helpers.ramboq_logger import get_logger
from backend.shared.helpers.utils import config, mask_column

from backend.api.algo.chase import chase_order, ChaseConfig, ChaseResult, ChaseStatus

logger = get_logger(__name__)


@dataclass
class OptionPosition:
    account: str
    tradingsymbol: str
    exchange: str
    instrument_type: str     # CE or PE
    underlying: str          # NIFTY, BANKNIFTY, CRUDE, etc.
    strike: float
    expiry: date
    quantity: int            # positive = long, negative = short
    product: str
    ltp: float = 0.0
    underlying_ltp: float = 0.0
    moneyness: str = ""      # ITM, ATM, NTM, OTM
    needs_close: bool = False
    close_reason: str = ""


@dataclass
class ExpiryState:
    status: str = "idle"     # idle, scanning, closing, done
    positions: list = field(default_factory=list)
    pending_chases: dict = field(default_factory=dict)   # symbol → ChaseResult
    closed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    last_scan: str = ""
    total_slippage: float = 0.0


class ExpiryEngine:
    def __init__(self, on_event: Callable | None = None):
        self.state = ExpiryState()
        self.on_event = on_event
        self._algo_cfg = config.get("algo", {})
        self._ntm_buffer = self._algo_cfg.get("expiry_ntm_buffer_pct", 2.0)
        self._start_offset_h = self._algo_cfg.get("expiry_start_offset_hours", 2)
        self._rescan_min = self._algo_cfg.get("expiry_rescan_minutes", 30)
        self._chase_cfg = ChaseConfig(
            interval_seconds=self._algo_cfg.get("chase_interval_seconds", 20),
            aggression_step=self._algo_cfg.get("aggression_step", 0.10),
            max_attempts=self._algo_cfg.get("max_attempts", 20),
        )
        self._instruments_cache: dict = {}  # exchange → list of instruments

    def _emit(self, event_type: str, detail: dict = None):
        if self.on_event:
            try:
                self.on_event(event_type, detail or {})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Instrument cache (loaded once per day per exchange)
    # ------------------------------------------------------------------

    def _load_instruments(self, exchange: str) -> list:
        """Load instruments for an exchange. Cached for the day."""
        if exchange in self._instruments_cache:
            return self._instruments_cache[exchange]

        conns = Connections()
        account = list(conns.conn.keys())[0]
        kite = conns.conn[account].kite
        instruments = kite.instruments(exchange)
        self._instruments_cache[exchange] = instruments
        logger.info(f"Expiry: loaded {len(instruments)} instruments for {exchange}")
        return instruments

    def _get_instrument_info(self, exchange: str, tradingsymbol: str) -> dict | None:
        """Find instrument details by tradingsymbol."""
        instruments = self._load_instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == tradingsymbol:
                return inst
        return None

    # ------------------------------------------------------------------
    # Position scanning
    # ------------------------------------------------------------------

    def _fetch_option_positions(self) -> list[OptionPosition]:
        """Fetch all option positions across all accounts with instrument metadata."""
        import pandas as pd

        raw_dfs = broker_apis.fetch_positions()
        all_positions = []

        for df in raw_dfs:
            if df.empty:
                continue
            for _, row in df.iterrows():
                exchange = row.get("exchange", "")
                symbol = row.get("tradingsymbol", "")
                qty = int(row.get("quantity", 0))

                if qty == 0:
                    continue

                # Look up instrument to get expiry, strike, type
                inst_exchange = "NFO" if exchange in ("NSE", "NFO") else "MCX"
                inst = self._get_instrument_info(inst_exchange, symbol)
                if not inst:
                    continue

                inst_type = inst.get("instrument_type", "")
                if inst_type not in ("CE", "PE"):
                    continue  # not an option

                all_positions.append(OptionPosition(
                    account=row.get("account", ""),
                    tradingsymbol=symbol,
                    exchange=inst_exchange,
                    instrument_type=inst_type,
                    underlying=inst.get("name", ""),
                    strike=float(inst.get("strike", 0)),
                    expiry=inst.get("expiry"),
                    quantity=qty,
                    product=row.get("product", "NRML"),
                ))

        return all_positions

    def _classify_moneyness(self, pos: OptionPosition) -> str:
        """Classify option as ITM, ATM, NTM, or OTM based on underlying LTP."""
        if pos.underlying_ltp <= 0:
            return "UNKNOWN"

        if pos.instrument_type == "CE":
            diff_pct = (pos.underlying_ltp - pos.strike) / pos.strike * 100
        else:  # PE
            diff_pct = (pos.strike - pos.underlying_ltp) / pos.strike * 100

        if diff_pct > self._ntm_buffer:
            return "ITM"
        elif diff_pct > 0:
            return "NTM"  # near the money — within buffer
        elif abs(diff_pct) < 0.5:
            return "ATM"
        else:
            return "OTM"

    def _fetch_underlying_ltps(self, positions: list[OptionPosition]) -> dict:
        """Fetch LTPs for all unique underlyings."""
        conns = Connections()
        account = list(conns.conn.keys())[0]
        kite = conns.conn[account].kite

        # Map underlying name to its index/futures symbol for LTP
        # For equity indices: use NSE:NIFTY 50, NSE:NIFTY BANK, etc.
        # For commodities: use MCX:CRUDE, MCX:GOLD, etc.
        symbols = set()
        for p in positions:
            if p.exchange == "NFO":
                # Try NSE:<underlying> for index
                symbols.add(f"NSE:{p.underlying}")
            else:
                symbols.add(f"MCX:{p.underlying}")

        if not symbols:
            return {}

        try:
            data = kite.ltp(list(symbols))
            return {k.split(":")[-1]: v.get("last_price", 0) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Expiry: LTP fetch failed: {e}")
            return {}

    def scan_positions(self) -> list[OptionPosition]:
        """
        Scan all option positions and identify those expiring today that need closing.

        Rules:
          - Equity (NFO): close ALL ITM + NTM positions expiring today
          - Commodity (MCX): close only UNBALANCED ITM positions expiring today
        """
        today = timestamp_indian().date()
        self.state.status = "scanning"
        self._emit("scan_start", {"date": str(today)})

        # Fetch positions
        all_opts = self._fetch_option_positions()
        logger.info(f"Expiry: found {len(all_opts)} option positions total")

        # Filter to today's expiry
        expiring = [p for p in all_opts if p.expiry == today]
        logger.info(f"Expiry: {len(expiring)} positions expiring today ({today})")

        if not expiring:
            self.state.status = "idle"
            self._emit("scan_complete", {"count": 0})
            return []

        # Fetch underlying LTPs
        ltps = self._fetch_underlying_ltps(expiring)

        # Classify moneyness
        for p in expiring:
            p.underlying_ltp = ltps.get(p.underlying, 0)
            p.moneyness = self._classify_moneyness(p)

        # Determine which positions need closing
        # Equity: all ITM + NTM
        for p in expiring:
            if p.exchange == "NFO" and p.moneyness in ("ITM", "NTM"):
                p.needs_close = True
                p.close_reason = f"Equity {p.moneyness} — must close before expiry"

        # Commodity: only unbalanced ITM
        mcx_expiring = [p for p in expiring if p.exchange == "MCX" and p.moneyness in ("ITM", "NTM")]
        # Group by underlying + expiry to find balanced pairs
        mcx_groups: dict[str, list] = {}
        for p in mcx_expiring:
            key = f"{p.underlying}_{p.expiry}"
            mcx_groups.setdefault(key, []).append(p)

        for key, group in mcx_groups.items():
            # Net quantity per CE/PE
            ce_qty = sum(p.quantity for p in group if p.instrument_type == "CE")
            pe_qty = sum(p.quantity for p in group if p.instrument_type == "PE")

            # If perfectly hedged (equal and opposite), skip
            if ce_qty + pe_qty == 0:
                logger.info(f"Expiry: MCX {key} is balanced — skipping")
                continue

            # Flag unbalanced legs
            for p in group:
                if p.moneyness in ("ITM", "NTM"):
                    p.needs_close = True
                    p.close_reason = f"MCX unbalanced {p.moneyness} (CE net={ce_qty}, PE net={pe_qty})"

        to_close = [p for p in expiring if p.needs_close]
        self.state.positions = expiring
        self.state.last_scan = timestamp_display()

        self._emit("scan_complete", {
            "total_expiring": len(expiring),
            "to_close": len(to_close),
            "positions": [
                {"account": p.account, "symbol": p.tradingsymbol,
                 "exchange": p.exchange, "qty": p.quantity,
                 "moneyness": p.moneyness, "strike": p.strike,
                 "underlying_ltp": p.underlying_ltp}
                for p in to_close
            ],
        })

        logger.info(f"Expiry: {len(to_close)} positions to close")
        return to_close

    # ------------------------------------------------------------------
    # Closing orchestration
    # ------------------------------------------------------------------

    async def close_positions(self, positions: list[OptionPosition]):
        """Chase-close all flagged positions concurrently."""
        self.state.status = "closing"

        tasks = []
        for pos in positions:
            # Determine transaction type: close long → SELL, close short → BUY
            txn = "SELL" if pos.quantity > 0 else "BUY"
            qty = abs(pos.quantity)

            cfg = ChaseConfig(
                interval_seconds=self._chase_cfg.interval_seconds,
                aggression_step=self._chase_cfg.aggression_step,
                max_attempts=self._chase_cfg.max_attempts,
                exchange=pos.exchange,
                product=pos.product,
            )

            async def _chase_one(p=pos, t=txn, q=qty, c=cfg):
                result = await chase_order(
                    account=p.account,
                    symbol=p.tradingsymbol,
                    transaction_type=t,
                    quantity=q,
                    cfg=c,
                    on_event=self.on_event,
                )
                if result.status == ChaseStatus.FILLED:
                    self.state.closed.append(result)
                    self.state.total_slippage += result.slippage
                else:
                    self.state.failed.append(result)
                return result

            self.state.pending_chases[pos.tradingsymbol] = ChaseResult(
                account=pos.account, symbol=pos.tradingsymbol,
                transaction_type=txn, quantity=qty,
                status=ChaseStatus.PENDING,
            )
            tasks.append(_chase_one())

        # Run all chases concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Expiry: chase exception: {r}")
            elif isinstance(r, ChaseResult):
                # Remove from pending
                self.state.pending_chases.pop(r.symbol, None)

        self.state.status = "done"
        self._emit("close_complete", {
            "closed": len(self.state.closed),
            "failed": len(self.state.failed),
            "total_slippage": self.state.total_slippage,
        })

    # ------------------------------------------------------------------
    # Main run loop (called by background task on expiry days)
    # ------------------------------------------------------------------

    async def run(self):
        """
        Full expiry-day workflow:
        1. Morning scan at 09:15
        2. Wait until T-2h before close
        3. Start closing
        4. Re-scan every 30 min for new ITM positions
        5. Continue until all closed or market close
        """
        now = timestamp_indian()
        today = now.date()

        # Determine market close times per exchange
        segments = config.get("market_segments", {})
        equity_close = dtime(15, 30)
        mcx_close = dtime(23, 30)
        for name, seg in segments.items():
            h, m = map(int, seg.get("hours_end", "15:30").split(":"))
            if name == "equity":
                equity_close = dtime(h, m)
            elif name == "commodity":
                mcx_close = dtime(h, m)

        # Morning scan
        logger.info("Expiry: starting morning scan")
        to_close = self.scan_positions()

        if not to_close:
            logger.info("Expiry: no positions need closing today")
            self._emit("no_positions", {"date": str(today)})
            return

        # Send morning alert
        self._emit("morning_alert", {
            "count": len(to_close),
            "positions": [
                f"{p.account} {p.tradingsymbol} qty={p.quantity} {p.moneyness}"
                for p in to_close
            ],
        })

        # Determine when to start closing based on exchange
        nfo_positions = [p for p in to_close if p.exchange == "NFO"]
        mcx_positions = [p for p in to_close if p.exchange == "MCX"]

        # Close NFO positions (start 2h before equity close)
        if nfo_positions:
            nfo_start = (datetime.combine(today, equity_close) -
                         timedelta(hours=self._start_offset_h)).time()
            now_t = timestamp_indian().time()
            if now_t < nfo_start:
                wait = (datetime.combine(today, nfo_start) -
                        datetime.combine(today, now_t)).total_seconds()
                logger.info(f"Expiry: waiting {wait/60:.0f} min until NFO close phase starts at {nfo_start}")
                self._emit("waiting", {"exchange": "NFO", "start_time": str(nfo_start)})
                await asyncio.sleep(max(wait, 0))

            logger.info(f"Expiry: starting NFO close for {len(nfo_positions)} positions")
            await self.close_positions(nfo_positions)

        # Close MCX positions (start 2h before commodity close)
        if mcx_positions:
            mcx_start = (datetime.combine(today, mcx_close) -
                         timedelta(hours=self._start_offset_h)).time()
            now_t = timestamp_indian().time()
            if now_t < mcx_start:
                wait = (datetime.combine(today, mcx_start) -
                        datetime.combine(today, now_t)).total_seconds()
                logger.info(f"Expiry: waiting {wait/60:.0f} min until MCX close phase starts at {mcx_start}")
                self._emit("waiting", {"exchange": "MCX", "start_time": str(mcx_start)})
                await asyncio.sleep(max(wait, 0))

            # Re-scan MCX positions (market may have moved)
            logger.info("Expiry: re-scanning MCX positions before closing")
            fresh = self.scan_positions()
            mcx_fresh = [p for p in fresh if p.exchange == "MCX" and p.needs_close]
            if mcx_fresh:
                logger.info(f"Expiry: starting MCX close for {len(mcx_fresh)} positions")
                await self.close_positions(mcx_fresh)

        # Summary
        logger.info(f"Expiry: complete — closed {len(self.state.closed)}, "
                     f"failed {len(self.state.failed)}, "
                     f"slippage ₹{self.state.total_slippage:.2f}")
        self._emit("expiry_complete", {
            "closed": len(self.state.closed),
            "failed": len(self.state.failed),
            "total_slippage": self.state.total_slippage,
        })
