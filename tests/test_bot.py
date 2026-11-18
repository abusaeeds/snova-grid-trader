"""Unit tests - run with:  python -m pytest -q

They use the built-in simulator, so no MetaTrader 5 terminal is needed.
"""

import pytest

from app.bot import BotConfig, GridBot, grid_prices, pip_size
from app.mt5_client import MT5Client, MT5Error
from app.simulator import SimulatedMT5


@pytest.fixture
def client():
    sim = SimulatedMT5(seed=1, auto_advance=False)
    c = MT5Client(sim)
    c.connect(12345, "demo", "SNova-Demo")
    return c


def test_pip_size():
    assert pip_size(0.00001, 5) == pytest.approx(0.0001)
    assert pip_size(0.001, 3) == pytest.approx(0.01)
    assert pip_size(0.0001, 4) == pytest.approx(0.0001)


def test_grid_prices_are_symmetric():
    sells, buys = grid_prices(1.10000, 0.0001, 3, 5)
    assert sells == [1.1001, 1.1002, 1.1003]
    assert buys == [1.0999, 1.0998, 1.0997]


def test_config_validation():
    with pytest.raises(ValueError):
        BotConfig(volume=0).validate()
    with pytest.raises(ValueError):
        BotConfig(levels=0).validate()
    BotConfig().validate()


def test_login_fails_without_password():
    with pytest.raises(MT5Error):
        MT5Client(SimulatedMT5()).connect(1, "", "x")


def test_place_grid_puts_orders_both_sides(client):
    bot = GridBot(client, BotConfig(symbol="EURUSD", levels=5))
    assert bot.place_grid() == 10
    orders = client.orders("EURUSD", bot.magic)
    types = sorted(o.type for o in orders)
    assert types.count(client.mt5.ORDER_TYPE_SELL_LIMIT) == 5
    assert types.count(client.mt5.ORDER_TYPE_BUY_LIMIT) == 5


def test_bots_do_not_touch_each_other(client):
    a = GridBot(client, BotConfig(symbol="EURUSD", levels=2))
    b = GridBot(client, BotConfig(symbol="EURUSD", levels=3))
    a.place_grid()
    b.place_grid()
    a.flatten()
    assert client.orders("EURUSD", a.magic) == []
    assert len(client.orders("EURUSD", b.magic)) == 6


def test_ranging_market_cycle_takes_profit(client):
    """Price drops through 2 buy levels and comes back -> net profit -> close."""
    sim = client.mt5
    sim.set_price("EURUSD", 1.08500)
    bot = GridBot(client, BotConfig(symbol="EURUSD", levels=5, step_pips=1, take_profit_pct=0.2))
    bot.place_grid()
    sim.set_price("EURUSD", 1.08475)          # falls ~2.5 pips: 2 buy limits fill
    assert bot.check_once() is None           # in loss for now
    assert bot.open_positions == 2
    sim.set_price("EURUSD", 1.08520)          # comes back above the start
    assert bot.check_once() == "tp"
    banked = bot.flatten()
    assert banked > 0
    assert client.positions("EURUSD", bot.magic) == []
    assert client.orders("EURUSD", bot.magic) == []


def test_stop_loss(client):
    sim = client.mt5
    sim.set_price("EURUSD", 1.08500)
    bot = GridBot(client, BotConfig(symbol="EURUSD", levels=3, stop_loss_pct=5))
    bot.place_grid()
    sim.set_price("EURUSD", 1.08300)          # strong trend down: every buy fills, deep loss
    assert bot.check_once() == "sl"


def test_thread_runs_and_stops_cleanly():
    sim = SimulatedMT5(seed=3, tick_seconds=0.01)
    c = MT5Client(sim)
    c.connect(1, "demo", "SNova-Demo")
    events = []
    bot = GridBot(c, BotConfig(symbol="EURUSD", cycles=3, poll_seconds=0.02),
                  on_event=lambda b, m, lvl: events.append(lvl))
    bot.start()
    bot.join(0.5)
    bot.stop()
    bot.join(5)
    assert not bot.running
    assert bot.status in (GridBot.STOPPED, GridBot.FINISHED)
    assert c.orders("EURUSD", bot.magic) == []
    assert c.positions("EURUSD", bot.magic) == []
    assert "error" not in events
