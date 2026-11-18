"""Read-only MetaTrader 5 connection check. It places NO orders.

Run it while MetaTrader 5 is open and logged in:
    python check_connection.py
The result is printed and also saved to check_connection_result.txt
"""

import datetime
import platform
import sys
from pathlib import Path

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def main() -> int:
    out(f"SNova Grid Trader - MT5 connection check ({datetime.datetime.now():%Y-%m-%d %H:%M:%S})")
    out(f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()} "
        f"({platform.architecture()[0]})")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        out("FAIL: MetaTrader5 package not installed. Run: pip install MetaTrader5")
        return 1
    out(f"MetaTrader5 package {getattr(mt5, '__version__', '?')}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app.mt5_client import MT5Client, MT5Error
    from app.bot import pip_size, grid_prices

    client = MT5Client()
    try:
        acc = client.connect()  # attach to the account already logged in
    except MT5Error as exc:
        out(f"FAIL: {exc}")
        out("Is MetaTrader 5 open and logged in to an account?")
        return 1
    try:
        modes = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
        out("OK: connected")
        out(f"  Account  : #{acc['login']}  {acc.get('name', '')}")
        out(f"  Server   : {acc['server']}   Company: {acc.get('company', '')}")
        out(f"  Type     : {modes.get(acc.get('trade_mode'), acc.get('trade_mode'))}")
        out(f"  Balance  : {acc['balance']} {acc['currency']}   Leverage 1:{acc['leverage']}")
        term = mt5.terminal_info()
        out(f"  Terminal : {getattr(term, 'name', '?')} build {getattr(term, 'build', '?')}")
        out(f"  Algo Trading button ON : {client.algo_trading_enabled()}")
        out(f"  Account allows trading : {bool(acc.get('trade_allowed', True))}")

        for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
            try:
                info = client.ensure_symbol(symbol)
            except MT5Error:
                # some brokers add a suffix, e.g. EURUSDm / EURUSD.r
                found = [s.name for s in (mt5.symbols_get(f"*{symbol}*") or ())][:5]
                out(f"  {symbol}: not found. Similar symbols: {found or 'none'}")
                continue
            tick = client.tick(symbol)
            fill = client.filling_mode(symbol)
            fill_name = {mt5.ORDER_FILLING_FOK: "FOK", mt5.ORDER_FILLING_IOC: "IOC",
                         mt5.ORDER_FILLING_RETURN: "RETURN"}.get(fill, fill)
            margin = client.margin(mt5.ORDER_TYPE_BUY, symbol, 0.01, tick.ask)
            step = pip_size(info.point, info.digits)
            sells, buys = grid_prices((tick.bid + tick.ask) / 2, step, 2, info.digits)
            out(f"  {symbol}: bid {tick.bid} ask {tick.ask} | digits {info.digits} | "
                f"filling {fill_name} | margin 0.01 lot = {margin} | "
                f"grid preview sells {sells} buys {buys}")
        out("RESULT: connection check passed (no orders were placed).")
        return 0
    finally:
        client.shutdown()


if __name__ == "__main__":
    code = main()
    Path(__file__).with_name("check_connection_result.txt").write_text("\n".join(lines),
                                                                        encoding="utf-8")
    sys.exit(code)
