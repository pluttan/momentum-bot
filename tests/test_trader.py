"""Tests для Trader (PAPER mode mostly — no real binance calls)."""
import pytest


@pytest.fixture
def paper_trader(monkeypatch):
    """Trader в PAPER mode с stubbed ccxt."""
    from momentum import config
    monkeypatch.setattr(config, "MODE", "PAPER")
    monkeypatch.setattr(config, "TOTAL_CAPITAL", 1000.0)

    class FakeCcxt:
        markets = {
            "BTC/USDT": {"symbol": "BTC/USDT", "precision": {"amount": 8}},
            "ETH/USDT": {"symbol": "ETH/USDT", "precision": {"amount": 8}},
        }

        def __init__(self, *args, **kwargs):
            self.rateLimit = 0

        def load_markets(self):
            return self.markets

        def fetch_ticker(self, sym):
            return {"last": 100.0, "symbol": sym}

        def fetch_ohlcv(self, sym, tf, limit=100):
            return [[i * 86400000, 100, 101, 99, 100.5, 1000] for i in range(limit)]

        def amount_to_precision(self, sym, amt):
            return f"{amt:.8f}"

    monkeypatch.setattr("momentum.trader.ccxt.binance", FakeCcxt)
    from momentum.trader import Trader
    return Trader()


def test_paper_buy_decrements_usdt(paper_trader):
    initial = paper_trader.get_balance_usdt()
    order = paper_trader.market_buy("BTC/USDT", 100)
    assert order["side"] == "buy"
    assert order["filled_units"] > 0
    after = paper_trader.get_balance_usdt()
    assert after == initial - 100


def test_paper_sell_returns_usdt(paper_trader):
    paper_trader.market_buy("BTC/USDT", 100)
    btc_units = paper_trader.get_balance("BTC")
    assert btc_units > 0
    order = paper_trader.market_sell("BTC/USDT", btc_units)
    assert order["side"] == "sell"
    assert paper_trader.get_balance("BTC") == 0


def test_get_price_returns_float(paper_trader):
    p = paper_trader.get_price("BTC/USDT")
    assert isinstance(p, float)
    assert p > 0


def test_buy_zero_units_raises(paper_trader, monkeypatch):
    # set price huge so usdt/price → 0 after rounding
    monkeypatch.setattr(paper_trader, "get_price", lambda s: 1e20)
    from momentum.trader import TraderError
    with pytest.raises(TraderError):
        paper_trader.market_buy("BTC/USDT", 1.0)
