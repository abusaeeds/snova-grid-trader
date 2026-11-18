"""A tiny offline MetaTrader 5 simulator used for Demo mode and unit tests.

It implements only the part of the ``MetaTrader5`` API this app uses, with
the same function names, constants and return shapes (named tuples). Prices
follow a mean-reverting random walk, i.e. a *ranging* market, which is the
market type a grid strategy is designed for.

No real money, no broker, no internet: perfect for showing the app to someone
who does not have MetaTrader 5 installed.
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from collections import namedtuple

AccountInfo = namedtuple(
    "AccountInfo",
    "login name server currency company leverage balance equity margin margin_free profit",
)
SymbolInfo = namedtuple(
    "SymbolInfo", "name point digits filling_mode visible trade_contract_size volume_min"
)
Tick = namedtuple("Tick", "time bid ask")
Position = namedtuple(
    "Position", "ticket symbol type volume price_open price_current profit magic comment time"
)
Order = namedtuple("Order", "ticket symbol type volume_initial price_open magic comment time_setup")
TradeResult = namedtuple("TradeResult", "retcode comment order deal volume price")
TerminalInfo = namedtuple("TerminalInfo", "trade_allowed connected name")

# start price and spread (in price units) for the simulated symbols
_SYMBOLS = {
    "EURUSD": (1.08500, 5, 0.00008),
    "GBPUSD": (1.27000, 5, 0.00012),
    "AUDUSD": (0.65500, 5, 0.00010),
    "USDJPY": (150.000, 3, 0.012),
}


class SimulatedMT5:
    """Drop-in stand-in for the ``MetaTrader5`` module."""

    # --- constants (same values as the real package) ---
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_INVALID = 10013

    LEVERAGE = 100
    CONTRACT = 100_000

    def __init__(self, seed: int | None = None, volatility: float = 1.0,
                 tick_seconds: float = 0.25, auto_advance: bool = True) -> None:
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self._tickets = itertools.count(100001)
        self.volatility = volatility
        self.tick_seconds = tick_seconds
        self.auto_advance = auto_advance
        self._connected = False
        self._balance = 5000.0
        self._mid = {s: v[0] for s, v in _SYMBOLS.items()}
        self._anchor = dict(self._mid)
        self._positions: dict[int, dict] = {}
        self._orders: dict[int, dict] = {}
        self._last_step = time.monotonic()
        self._error = (1, "Success")

    # ---------------------------------------------------------------- terminal
    def initialize(self, login=None, password=None, server=None, path=None, **_):
        with self._lock:
            if not password:
                self._error = (-6, "Terminal: Authorization failed")
                return False
            self._login, self._server = int(login or 0), server or "SNova-Demo"
            self._connected = True
            self._error = (1, "Success")
            return True

    def shutdown(self):
        self._connected = False

    def last_error(self):
        return self._error

    def terminal_info(self):
        return TerminalInfo(True, self._connected, "SNova Simulator")

    # ------------------------------------------------------------ price engine
    def _spread(self, symbol):
        return _SYMBOLS[symbol][2]

    def _step_once(self):
        for symbol in self._mid:
            pip = 0.01 if _SYMBOLS[symbol][1] == 3 else 0.0001
            pull = (self._anchor[symbol] - self._mid[symbol]) * 0.02  # mean reversion
            shock = self._rng.gauss(0, 0.6 * pip * self.volatility)
            self._mid[symbol] += pull + shock
        self._match_orders()

    def advance(self, steps: int = 1):
        """Move prices forward by ``steps`` ticks (used by tests)."""
        with self._lock:
            for _ in range(steps):
                self._step_once()

    def set_price(self, symbol: str, mid: float):
        """Force a price (used by tests) and trigger matching pending orders."""
        with self._lock:
            self._mid[symbol] = mid
            self._match_orders()

    def _auto(self):
        if not self.auto_advance:
            return
        now = time.monotonic()
        steps = int((now - self._last_step) / self.tick_seconds)
        if steps:
            self._last_step += steps * self.tick_seconds
            for _ in range(min(steps, 200)):
                self._step_once()

    def _bid_ask(self, symbol):
        half = self._spread(symbol) / 2
        digits = _SYMBOLS[symbol][1]
        return round(self._mid[symbol] - half, digits), round(self._mid[symbol] + half, digits)

    def _match_orders(self):
        for ticket, o in list(self._orders.items()):
            bid, ask = self._bid_ask(o["symbol"])
            hit = (o["type"] == self.ORDER_TYPE_BUY_LIMIT and ask <= o["price"]) or (
                o["type"] == self.ORDER_TYPE_SELL_LIMIT and bid >= o["price"]
            )
            if hit:
                del self._orders[ticket]
                ptype = self.POSITION_TYPE_BUY if o["type"] == self.ORDER_TYPE_BUY_LIMIT else self.POSITION_TYPE_SELL
                self._positions[ticket] = dict(o, type=ptype, time=int(time.time()))

    def _profit(self, symbol, ptype, volume, price_open):
        bid, ask = self._bid_ask(symbol)
        current = bid if ptype == self.POSITION_TYPE_BUY else ask
        diff = (current - price_open) if ptype == self.POSITION_TYPE_BUY else (price_open - current)
        value = diff * self.CONTRACT * volume
        if symbol.endswith("JPY"):
            value /= current
        return round(value, 2), current

    # --------------------------------------------------------------- account
    def account_info(self):
        with self._lock:
            if not self._connected:
                return None
            self._auto()
            floating = sum(self._profit(p["symbol"], p["type"], p["volume"], p["price"])[0]
                           for p in self._positions.values())
            margin = sum(self.order_calc_margin(p["type"], p["symbol"], p["volume"], p["price"])
                         for p in self._positions.values())
            equity = self._balance + floating
            return AccountInfo(self._login, "Demo Trader", self._server, "USD", "SNova Simulator",
                               self.LEVERAGE, round(self._balance, 2), round(equity, 2),
                               round(margin, 2), round(equity - margin, 2), round(floating, 2))

    # --------------------------------------------------------------- symbols
    def symbol_info(self, symbol):
        if symbol not in _SYMBOLS:
            return None
        digits = _SYMBOLS[symbol][1]
        return SymbolInfo(symbol, 10 ** -digits, digits, 3, True, self.CONTRACT, 0.01)

    def symbol_select(self, symbol, enable=True):
        return symbol in _SYMBOLS

    def symbol_info_tick(self, symbol):
        with self._lock:
            if symbol not in _SYMBOLS:
                return None
            self._auto()
            bid, ask = self._bid_ask(symbol)
            return Tick(int(time.time()), bid, ask)

    # ----------------------------------------------------------------- trading
    def order_calc_margin(self, order_type, symbol, volume, price):
        value = self.CONTRACT * volume / self.LEVERAGE
        if not symbol.startswith("USD"):
            value *= price
        return round(value, 2)

    def positions_get(self, symbol=None):
        with self._lock:
            self._auto()
            out = []
            for t, p in self._positions.items():
                if symbol and p["symbol"] != symbol:
                    continue
                profit, current = self._profit(p["symbol"], p["type"], p["volume"], p["price"])
                out.append(Position(t, p["symbol"], p["type"], p["volume"], p["price"], current,
                                    profit, p["magic"], p["comment"], p["time"]))
            return tuple(out)

    def orders_get(self, symbol=None):
        with self._lock:
            self._auto()
            return tuple(
                Order(t, o["symbol"], o["type"], o["volume"], o["price"], o["magic"], o["comment"], 0)
                for t, o in self._orders.items() if not symbol or o["symbol"] == symbol
            )

    def _result(self, code, comment, order=0, volume=0.0, price=0.0):
        return TradeResult(code, comment, order, order, volume, price)

    def order_send(self, request):
        with self._lock:
            if not self._connected:
                self._error = (-10004, "No connection")
                return None
            action = request.get("action")
            if action == self.TRADE_ACTION_PENDING:
                ticket = next(self._tickets)
                self._orders[ticket] = {
                    "symbol": request["symbol"], "type": request["type"],
                    "volume": request["volume"], "price": request["price"],
                    "magic": request.get("magic", 0), "comment": request.get("comment", ""),
                }
                self._match_orders()
                return self._result(self.TRADE_RETCODE_DONE, "Request executed", ticket,
                                    request["volume"], request["price"])
            if action == self.TRADE_ACTION_REMOVE:
                if self._orders.pop(request["order"], None) is None:
                    return self._result(self.TRADE_RETCODE_INVALID, "Invalid order")
                return self._result(self.TRADE_RETCODE_DONE, "Request executed", request["order"])
            if action == self.TRADE_ACTION_DEAL and "position" in request:
                p = self._positions.pop(request["position"], None)
                if p is None:
                    return self._result(self.TRADE_RETCODE_INVALID, "Invalid position")
                profit, current = self._profit(p["symbol"], p["type"], p["volume"], p["price"])
                self._balance += profit
                return self._result(self.TRADE_RETCODE_DONE, "Request executed",
                                    request["position"], p["volume"], current)
            return self._result(self.TRADE_RETCODE_INVALID, "Unsupported request")
