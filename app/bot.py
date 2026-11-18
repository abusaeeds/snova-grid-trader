"""The grid trading bot.

Strategy (as taught in the SLIPD Academy Advanced Python course)
----------------------------------------------------------------
1. Read the current price  (bid + ask) / 2.
2. Place ``levels`` SELL LIMIT orders above it and ``levels`` BUY LIMIT
   orders below it, each ``step`` away from the previous one (a "grid").
3. When the market moves and comes back (a ranging market), triggered orders
   end up in profit overall.
4. When the profit of the triggered orders, as a percentage of the margin
   they use, reaches the take-profit target, close them all and delete the
   pending orders that were never triggered.
5. Repeat for the number of cycles chosen.

Each bot runs in its own thread and has its own *magic number*, so several
bots can trade different (or even the same) symbols at the same time without
touching each other's orders.
"""

from __future__ import annotations

import itertools
import threading
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from .mt5_client import MT5Client, MT5Error

MAGIC_BASE = 770_000


@dataclass
class BotConfig:
    symbol: str = "EURUSD"
    volume: float = 0.01          # lot size of every grid order
    step_pips: float = 1.0        # distance between grid levels, in pips
    levels: int = 5               # orders on each side of the price
    take_profit_pct: float = 0.2  # close when profit / margin * 100 >= this
    stop_loss_pct: float = 0.0    # close when profit / margin * 100 <= -this (0 = off)
    cycles: int = 1               # how many grids to run one after another
    poll_seconds: float = 1.0     # how often to check the positions

    def validate(self) -> None:
        if not self.symbol.strip():
            raise ValueError("Symbol is required.")
        if self.volume <= 0:
            raise ValueError("Volume must be greater than 0.")
        if self.step_pips <= 0:
            raise ValueError("Grid step must be greater than 0.")
        if not 1 <= self.levels <= 50:
            raise ValueError("Levels must be between 1 and 50.")
        if self.take_profit_pct <= 0:
            raise ValueError("Take profit % must be greater than 0.")
        if self.stop_loss_pct < 0:
            raise ValueError("Stop loss % cannot be negative (use 0 to turn it off).")
        if self.cycles < 1:
            raise ValueError("Cycles must be at least 1.")


def pip_size(point: float, digits: int) -> float:
    """One pip. 5- and 3-digit quotes have an extra 'pipette' digit."""
    return point * 10 if digits in (3, 5) else point


def grid_prices(mid: float, step: float, levels: int, digits: int) -> tuple[list, list]:
    """Return (sell_limit_prices, buy_limit_prices) around ``mid``."""
    sells = [round(mid + step * i, digits) for i in range(1, levels + 1)]
    buys = [round(mid - step * i, digits) for i in range(1, levels + 1)]
    return sells, buys


class GridBot:
    """One grid bot = one symbol + one config + one worker thread."""

    _ids = itertools.count(1)

    IDLE, STARTING, WAITING, IN_TRADE, STOPPING, STOPPED, FINISHED, ERROR = (
        "Idle", "Starting", "Waiting", "In trade", "Stopping", "Stopped", "Finished", "Error",
    )

    def __init__(self, client: MT5Client, config: BotConfig,
                 on_event: Optional[Callable[["GridBot", str, str], None]] = None) -> None:
        config.validate()
        self.client = client
        self.config = config
        self.id = next(GridBot._ids)
        self.magic = MAGIC_BASE + self.id
        self.name = f"Bot {self.id}"
        self.on_event = on_event
        self.status = self.IDLE
        self.cycle = 0
        self.floating = 0.0     # profit of currently open positions
        self.realized = 0.0     # profit already banked by closed cycles
        self.open_positions = 0
        self.pending_orders = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ----------------------------------------------------------------- control
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the bot to stop. It flattens (closes) its own trades on exit."""
        if self.running:
            self._set_status(self.STOPPING)
            self._stop.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # ----------------------------------------------------------------- helpers
    def _emit(self, message: str, level: str = "info") -> None:
        if self.on_event:
            try:
                self.on_event(self, message, level)
            except Exception:  # noqa: BLE001 - never let the UI kill the bot
                pass

    def _set_status(self, status: str) -> None:
        self.status = status
        self._emit("", "status")

    def side_percent(self, positions: list) -> float:
        """Profit of the given positions as a % of the margin they use."""
        if not positions:
            return 0.0
        m = self.client.mt5
        profit = sum(p.profit for p in positions)
        margin = 0.0
        for p in positions:
            order_type = m.ORDER_TYPE_BUY if p.type == m.POSITION_TYPE_BUY else m.ORDER_TYPE_SELL
            margin += self.client.margin(order_type, p.symbol, p.volume, p.price_open)
        return profit / margin * 100 if margin else 0.0

    # ------------------------------------------------------------------ trading
    def place_grid(self) -> int:
        cfg = self.config
        info = self.client.ensure_symbol(cfg.symbol)
        step = pip_size(info.point, info.digits) * cfg.step_pips
        mid = self.client.mid_price(cfg.symbol)
        sells, buys = grid_prices(mid, step, cfg.levels, info.digits)
        placed = 0
        for i, price in enumerate(sells, 1):
            self.client.sell_limit(cfg.symbol, cfg.volume, price, self.magic, f"{self.name} S{i}")
            placed += 1
        for i, price in enumerate(buys, 1):
            self.client.buy_limit(cfg.symbol, cfg.volume, price, self.magic, f"{self.name} B{i}")
            placed += 1
        self._emit(f"Grid placed around {mid:.{info.digits}f}: {cfg.levels} sell limits above, "
                   f"{cfg.levels} buy limits below, step {cfg.step_pips:g} pip(s).")
        return placed

    def close_all_positions(self) -> float:
        banked = 0.0
        for p in self.client.positions(self.config.symbol, self.magic):
            try:
                self.client.close_position(p)
                banked += p.profit
            except MT5Error as exc:
                self._emit(f"Could not close position #{p.ticket}: {exc}", "error")
        return banked

    def cancel_pending(self) -> int:
        removed = 0
        for o in self.client.orders(self.config.symbol, self.magic):
            try:
                self.client.cancel_order(o)
                removed += 1
            except MT5Error as exc:
                self._emit(f"Could not delete order #{o.ticket}: {exc}", "error")
        return removed

    def flatten(self) -> float:
        """Close every position and delete every pending order of this bot."""
        removed = self.cancel_pending()
        banked = self.close_all_positions()
        self.realized += banked
        self.floating = 0.0
        self.open_positions = self.pending_orders = 0
        if removed or banked:
            self._emit(f"Flattened: {removed} pending order(s) deleted, P/L banked {banked:+.2f}.")
        return banked

    def check_once(self) -> Optional[str]:
        """One monitoring pass. Returns 'tp' / 'sl' when the cycle should end."""
        cfg = self.config
        positions = self.client.positions(cfg.symbol, self.magic)
        self.open_positions = len(positions)
        self.pending_orders = len(self.client.orders(cfg.symbol, self.magic))
        self.floating = sum(p.profit for p in positions)
        if not positions:
            if self.status != self.WAITING:
                self._set_status(self.WAITING)
            return None
        if self.status != self.IN_TRADE:
            self._set_status(self.IN_TRADE)
        pct = self.side_percent(positions)
        self._emit("", "status")
        if pct >= cfg.take_profit_pct:
            self._emit(f"Take profit hit: {pct:.2f}% of margin (target {cfg.take_profit_pct:g}%).",
                       "success")
            return "tp"
        if cfg.stop_loss_pct and pct <= -cfg.stop_loss_pct:
            self._emit(f"Stop loss hit: {pct:.2f}% of margin (limit -{cfg.stop_loss_pct:g}%).",
                       "warning")
            return "sl"
        return None

    # ------------------------------------------------------------- the thread
    def _run(self) -> None:
        cfg = self.config
        self._set_status(self.STARTING)
        self._emit(f"Started on {cfg.symbol} | lot {cfg.volume} | step {cfg.step_pips:g} pip | "
                   f"{cfg.levels} levels | TP {cfg.take_profit_pct:g}% | cycles {cfg.cycles}")
        try:
            for cycle in range(1, cfg.cycles + 1):
                if self._stop.is_set():
                    break
                self.cycle = cycle
                self._emit(f"Cycle {cycle}/{cfg.cycles} starting.")
                self.place_grid()
                self._set_status(self.WAITING)
                while not self._stop.is_set():
                    if self.check_once():
                        banked = self.flatten()
                        self._emit(f"Cycle {cycle} closed with {banked:+.2f}.", "success")
                        break
                    self._stop.wait(cfg.poll_seconds)
            if self._stop.is_set():
                self.flatten()
                self._set_status(self.STOPPED)
                self._emit("Stopped by user.", "warning")
            else:
                self._set_status(self.FINISHED)
                self._emit(f"All {cfg.cycles} cycle(s) finished. Total P/L {self.realized:+.2f}.",
                           "success")
        except Exception as exc:  # noqa: BLE001 - one bot's crash must not stop the others
            self._set_status(self.ERROR)
            self._emit(f"Error: {exc}", "error")
            self._emit(traceback.format_exc(), "debug")
            try:
                self.flatten()
            except Exception:  # noqa: BLE001
                pass
