"""Thread-safe wrapper around the MetaTrader5 Python package.

The official ``MetaTrader5`` package talks to one terminal through a single
connection and is not safe to call from several threads at the same time.
Every call in this module goes through one shared lock, so many bots (each in
its own thread) can trade through the same terminal safely.

The client also accepts any object with the same API as ``MetaTrader5``,
which is how the built-in simulator (demo mode) and the unit tests plug in.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

try:  # MetaTrader5 is Windows-only; the app still runs in demo mode without it.
    import MetaTrader5 as _mt5  # type: ignore
except ImportError:  # pragma: no cover - depends on the platform
    _mt5 = None


class MT5Error(Exception):
    """Raised when the terminal refuses a request or is not connected."""


class MT5Client:
    """Small, thread-safe facade over the MetaTrader5 API."""

    def __init__(self, backend: Any = None) -> None:
        self.mt5 = backend if backend is not None else _mt5
        self._lock = threading.RLock()
        self.connected = False

    # ------------------------------------------------------------------ helpers
    def _require_backend(self) -> None:
        if self.mt5 is None:
            raise MT5Error(
                "The MetaTrader5 package is not installed.\n"
                "Install it with:  pip install MetaTrader5\n"
                "(or start the app in Demo mode)."
            )

    def _last_error(self) -> str:
        try:
            code, message = self.mt5.last_error()
            return f"{message} (code {code})"
        except Exception:  # noqa: BLE001 - best effort only
            return "unknown error"

    # --------------------------------------------------------------- connection
    def connect(self, login: Optional[int] = None, password: str = "", server: str = "",
                path: Optional[str] = None) -> dict:
        """Start the terminal and log in. Returns the account information.

        With no login, it attaches to the account already logged in to the
        running MetaTrader 5 terminal (no password needed).
        """
        self._require_backend()
        with self._lock:
            kwargs = {}
            if login:
                kwargs = {"login": int(login), "password": password, "server": server}
            if path:
                kwargs["path"] = path
            if not self.mt5.initialize(**kwargs):
                error = self._last_error()
                self.mt5.shutdown()
                raise MT5Error(f"Login failed: {error}")
            self.connected = True
            info = self.mt5.account_info()
            if info is None:
                raise MT5Error(f"Connected, but no account information: {self._last_error()}")
            return info._asdict()

    def shutdown(self) -> None:
        with self._lock:
            if self.mt5 is not None and self.connected:
                self.mt5.shutdown()
            self.connected = False

    def account_info(self) -> Optional[dict]:
        with self._lock:
            info = self.mt5.account_info() if self.connected else None
            return info._asdict() if info is not None else None

    def algo_trading_enabled(self) -> bool:
        """True when the 'Algo Trading' button in the terminal is switched on."""
        with self._lock:
            info = self.mt5.terminal_info()
            return bool(getattr(info, "trade_allowed", True)) if info is not None else False

    # ------------------------------------------------------------- market data
    def ensure_symbol(self, symbol: str):
        """Make sure the symbol exists and is shown in Market Watch."""
        with self._lock:
            info = self.mt5.symbol_info(symbol)
            if info is None:
                raise MT5Error(f"Symbol '{symbol}' was not found on this server.")
            if not info.visible and not self.mt5.symbol_select(symbol, True):
                raise MT5Error(f"Could not add '{symbol}' to Market Watch.")
            return self.mt5.symbol_info(symbol)

    def tick(self, symbol: str):
        with self._lock:
            tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"No price for '{symbol}': {self._last_error()}")
        return tick

    def mid_price(self, symbol: str) -> float:
        """Current price = (bid + ask) / 2."""
        tick = self.tick(symbol)
        return (tick.bid + tick.ask) / 2

    def positions(self, symbol: str, magic: Optional[int] = None) -> list:
        with self._lock:
            items = self.mt5.positions_get(symbol=symbol) or ()
        return [p for p in items if magic is None or p.magic == magic]

    def orders(self, symbol: str, magic: Optional[int] = None) -> list:
        with self._lock:
            items = self.mt5.orders_get(symbol=symbol) or ()
        return [o for o in items if magic is None or o.magic == magic]

    def margin(self, order_type: int, symbol: str, volume: float, price: float) -> float:
        with self._lock:
            value = self.mt5.order_calc_margin(order_type, symbol, volume, price)
        return float(value or 0.0)

    # ------------------------------------------------------------------ trading
    def filling_mode(self, symbol: str) -> int:
        """Pick an order filling mode the broker accepts for this symbol.

        Brokers differ here; sending the wrong one gives the classic
        "Unsupported filling mode" error.
        """
        m = self.mt5
        with self._lock:
            info = m.symbol_info(symbol)
        flags = getattr(info, "filling_mode", 0) if info is not None else 0
        if flags & 1:
            return m.ORDER_FILLING_FOK
        if flags & 2:
            return m.ORDER_FILLING_IOC
        return m.ORDER_FILLING_RETURN

    def _send(self, request: dict, ok_codes: tuple) -> Any:
        with self._lock:
            result = self.mt5.order_send(request)
        if result is None:
            raise MT5Error(f"order_send failed: {self._last_error()}")
        if result.retcode not in ok_codes:
            raise MT5Error(f"Request rejected: {result.comment} (retcode {result.retcode})")
        return result

    def place_limit(self, symbol: str, order_type: int, volume: float, price: float,
                    magic: int, comment: str = "") -> Any:
        m = self.mt5
        request = {
            "action": m.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "deviation": 20,
            "magic": magic,
            "comment": comment[:31],
            "type_time": m.ORDER_TIME_GTC,
            "type_filling": self.filling_mode(symbol),
        }
        return self._send(request, (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_PLACED))

    def buy_limit(self, symbol, volume, price, magic, comment=""):
        return self.place_limit(symbol, self.mt5.ORDER_TYPE_BUY_LIMIT, volume, price, magic, comment)

    def sell_limit(self, symbol, volume, price, magic, comment=""):
        return self.place_limit(symbol, self.mt5.ORDER_TYPE_SELL_LIMIT, volume, price, magic, comment)

    def close_position(self, position) -> Any:
        """Close one open position with an opposite market deal."""
        m = self.mt5
        tick = self.tick(position.symbol)
        is_buy = position.type == m.POSITION_TYPE_BUY
        request = {
            "action": m.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": float(position.volume),
            "type": m.ORDER_TYPE_SELL if is_buy else m.ORDER_TYPE_BUY,
            "position": position.ticket,
            "price": tick.bid if is_buy else tick.ask,
            "deviation": 20,
            "magic": position.magic,
            "comment": "grid close",
            "type_time": m.ORDER_TIME_GTC,
            "type_filling": self.filling_mode(position.symbol),
        }
        return self._send(request, (m.TRADE_RETCODE_DONE,))

    def cancel_order(self, order) -> Any:
        """Delete one pending (not yet triggered) order."""
        m = self.mt5
        request = {"action": m.TRADE_ACTION_REMOVE, "order": order.ticket}
        return self._send(request, (m.TRADE_RETCODE_DONE,))
