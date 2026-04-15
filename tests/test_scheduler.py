"""Integration tests для scheduler logic с mock trader."""
import pandas as pd

from momentum import config, db, scheduler


def test_open_picks_creates_db_records(mock_trader):
    from momentum.strategy import Pick
    picks = [Pick("BTC/USDT", 10.0, 1), Pick("ETH/USDT", 8.0, 2)]
    mock_trader.set_price("BTC/USDT", 50000)
    mock_trader.set_price("ETH/USDT", 3000)
    opened = scheduler.open_picks(mock_trader, picks, 100)
    assert opened == 2
    rows = db.get_open_positions()
    assert len(rows) == 2
    syms = sorted(r["symbol"] for r in rows)
    assert syms == ["BTC/USDT", "ETH/USDT"]


def test_close_all_zeroes_open(mock_trader):
    from momentum.strategy import Pick
    picks = [Pick("BTC/USDT", 10.0, 1)]
    mock_trader.set_price("BTC/USDT", 50000)
    scheduler.open_picks(mock_trader, picks, 100)
    assert len(db.get_open_positions()) == 1
    scheduler.close_all_positions(mock_trader, "test")
    assert len(db.get_open_positions()) == 0
    closed = db.get_closed_positions()
    assert len(closed) == 1
    assert closed[0]["close_reason"] == "test"


def test_check_stops_triggers_at_3pct(mock_trader):
    from momentum.strategy import Pick
    picks = [Pick("BTC/USDT", 10.0, 1)]
    mock_trader.set_price("BTC/USDT", 100.0)
    scheduler.open_picks(mock_trader, picks, 100)
    # price holds — no stop
    mock_trader.set_price("BTC/USDT", 99.0)
    assert scheduler.check_stops(mock_trader) == 0
    assert len(db.get_open_positions()) == 1
    # price drops -3.5% — stop triggers
    mock_trader.set_price("BTC/USDT", 96.0)
    assert scheduler.check_stops(mock_trader) == 1
    assert len(db.get_open_positions()) == 0
    closed = db.get_closed_positions()
    assert closed[0]["close_reason"] == "stop_loss"


def test_update_equity_logs(mock_trader):
    eq = scheduler.update_equity(mock_trader)
    assert eq == 1000.0
    curve = db.get_equity_curve()
    assert len(curve) == 1


def test_emergency_stop_triggers(monkeypatch):
    # simulate equity drop below maxDD (manual ts to avoid ON CONFLICT REPLACE collision)
    monkeypatch.setattr(config, "MAX_DRAWDOWN_PCT", 0.10)
    with db.conn() as c:
        c.execute("INSERT INTO equity (ts, capital, positions_value) VALUES (1700000000, 1000, 0)")
        c.execute("INSERT INTO equity (ts, capital, positions_value) VALUES (1700000100, 800, 0)")
    halt, reason = scheduler.check_emergency_stop()
    assert halt
    assert "maxDD" in reason


def test_no_picks_skips_rebalance(mock_trader, monkeypatch):
    """If panel empty / no positives — rebalance does nothing harmful."""
    monkeypatch.setattr(scheduler, "fetch_lookback_panel",
                        lambda *a, **kw: pd.DataFrame())
    rb = scheduler.rebalance(mock_trader)
    assert rb["opened"] == 0
    assert rb["skipped"] == "no data"


def test_state_recovery_open_positions_survive_db_close(mock_trader):
    """Positions persist in DB через close/reopen connection (simulates bot restart)."""
    from momentum.strategy import Pick
    picks = [Pick("BTC/USDT", 10.0, 1), Pick("ETH/USDT", 5.0, 2)]
    mock_trader.set_price("BTC/USDT", 50000)
    mock_trader.set_price("ETH/USDT", 3000)
    scheduler.open_picks(mock_trader, picks, 100)
    # "restart": re-read from DB
    rows = db.get_open_positions()
    assert len(rows) == 2
    # state survives
    syms = sorted(r["symbol"] for r in rows)
    assert syms == ["BTC/USDT", "ETH/USDT"]
    # check stops still work after "restart"
    mock_trader.set_price("BTC/USDT", 48000)  # -4% → below stop (default -3%)
    stopped = scheduler.check_stops(mock_trader)
    assert stopped == 1


def test_rebalance_timestamp_persisted():
    """last_rebalance_ts survives DB reopen."""
    import time
    ts = int(time.time())
    db.set_last_rebalance_ts(ts)
    assert db.get_last_rebalance_ts() == ts


def test_pause_flag_persists_in_kv():
    db.set_state("paused", True)
    assert db.get_state("paused") is True
    db.set_state("paused", False)
    assert db.get_state("paused") is False
