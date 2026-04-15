"""Shared pytest fixtures."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Each test gets fresh sqlite DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("momentum.config.DB_PATH", path)
    from momentum import db as db_mod
    db_mod.init_db()
    yield path
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


@pytest.fixture
def mock_trader():
    """In-memory mock trader (no real binance calls)."""
    from momentum import config

    class MockTrader:
        def __init__(self):
            self.mode = "PAPER"
            self.fee = config.effective_fee()
            self._balance = {"USDT": 1000.0}
            self._prices = {}
            self.orders = []  # log of all orders

        def get_price(self, sym):
            return self._prices.get(sym, 100.0)

        def fetch_ohlcv(self, sym, tf="1d", limit=20):
            # synthetic: linearly increasing prices
            base = 100.0
            return [[i * 86400 * 1000, base, base * 1.01, base * 0.99, base * 1.005, 1000]
                    for i in range(limit)]

        def market_buy(self, sym, usdt):
            price = self.get_price(sym)
            units = (usdt * (1 - self.fee)) / price
            self._balance["USDT"] -= usdt
            base = sym.split("/")[0]
            self._balance[base] = self._balance.get(base, 0) + units
            order = {"symbol": sym, "side": "buy", "filled_units": units,
                     "filled_price": price, "fee_usdt": usdt * self.fee, "ts": 1700000000}
            self.orders.append(order)
            return order

        def market_sell(self, sym, units):
            price = self.get_price(sym)
            usdt = units * price * (1 - self.fee)
            base = sym.split("/")[0]
            self._balance[base] = max(0, self._balance.get(base, 0) - units)
            self._balance["USDT"] = self._balance.get("USDT", 0) + usdt
            order = {"symbol": sym, "side": "sell", "filled_units": units,
                     "filled_price": price, "fee_usdt": units * price * self.fee, "ts": 1700000001}
            self.orders.append(order)
            return order

        def get_balance_usdt(self):
            return self._balance.get("USDT", 0)

        def get_balance(self, asset):
            return self._balance.get(asset, 0)

        def set_price(self, sym, price):
            self._prices[sym] = price

    return MockTrader()
