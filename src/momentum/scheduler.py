"""Main rebalance loop. Polls для rebalance trigger, executes strategy."""
from __future__ import annotations

import time

import pandas as pd
import structlog

from . import config, db, strategy
from .strategy import Pick, Position
from .trader import Trader

log = structlog.get_logger()


def fetch_lookback_panel(trader: Trader, symbols: list[str], lookback_days: int) -> pd.DataFrame:
    """Fetch daily close prices для всех symbols за lookback_days+5 (buffer).

    Returns DataFrame with index=dates(UTC), columns=symbols, values=close prices.
    """
    series = {}
    for sym in symbols:
        try:
            ohlcv = trader.fetch_ohlcv(sym, "1d", limit=lookback_days + 5)
            if not ohlcv:
                log.warning("no ohlcv", symbol=sym)
                continue
            df = pd.DataFrame(ohlcv, columns=["ts", "o", "h", "low", "c", "v"])
            df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            series[sym] = df.set_index("dt")["c"]
        except Exception as e:
            log.warning("fetch_ohlcv error", symbol=sym, error=str(e))
    if not series:
        return pd.DataFrame()
    panel = pd.DataFrame(series).dropna(how="all")
    return panel


def db_pos_to_position(row: dict) -> Position:
    return Position(
        symbol=row["symbol"],
        entry_price=row["entry_price"],
        units=row["units"],
        entry_ts=pd.Timestamp(row["entry_ts"], unit="s", tz="UTC"),
        capital_at_entry=row["capital_at_entry"],
    )


def close_all_positions(trader: Trader, reason: str) -> float:
    """Close all open positions. Returns USDT received total."""
    total_received = 0.0
    open_pos = db.get_open_positions()
    for row in open_pos:
        try:
            order = trader.market_sell(row["symbol"], row["units"])
            db.log_trade(order["symbol"], order["side"], order["filled_units"],
                         order["filled_price"], order["fee_usdt"], order["ts"])
            db.close_position(row["id"], order["filled_price"], reason)
            received = order["filled_units"] * order["filled_price"] * (1 - trader.fee)
            total_received += received
        except Exception as e:
            log.error("close failed", symbol=row["symbol"], error=str(e))
    return total_received


def open_picks(trader: Trader, picks: list[Pick], capital_per_pos: float) -> int:
    """Open positions for each pick. Returns count opened."""
    opened = 0
    for pick in picks:
        try:
            order = trader.market_buy(pick.symbol, capital_per_pos)
            db.log_trade(order["symbol"], order["side"], order["filled_units"],
                         order["filled_price"], order["fee_usdt"], order["ts"])
            db.add_position(
                symbol=order["symbol"],
                entry_price=order["filled_price"],
                units=order["filled_units"],
                capital_at_entry=capital_per_pos,
                entry_ts=order["ts"],
            )
            opened += 1
        except Exception as e:
            log.error("open failed", symbol=pick.symbol, error=str(e))
    return opened


def check_stops(trader: Trader) -> int:
    """Check open positions for stop-loss trigger. Close if hit. Returns count stopped."""
    stopped = 0
    for row in db.get_open_positions():
        pos = db_pos_to_position(row)
        price = trader.get_price(pos.symbol)
        if price is None:
            continue
        if strategy.should_stop(pos, price):
            log.info("stop hit", symbol=pos.symbol, entry=pos.entry_price,
                     stop=pos.stop_price, current=price)
            try:
                order = trader.market_sell(pos.symbol, pos.units)
                db.log_trade(order["symbol"], order["side"], order["filled_units"],
                             order["filled_price"], order["fee_usdt"], order["ts"])
                db.close_position(row["id"], order["filled_price"], "stop_loss")
                stopped += 1
            except Exception as e:
                log.error("stop close failed", symbol=pos.symbol, error=str(e))
    return stopped


def update_equity(trader: Trader):
    """Snapshot current equity = USDT balance + sum(positions value)."""
    usdt = trader.get_balance_usdt()
    positions_val = 0.0
    for row in db.get_open_positions():
        price = trader.get_price(row["symbol"])
        if price:
            positions_val += row["units"] * price
    db.log_equity(usdt, positions_val)
    return usdt + positions_val


def check_emergency_stop() -> tuple[bool, str | None]:
    """Check risk caps. Returns (should_halt, reason)."""
    dd = db.get_max_drawdown_pct()
    if dd <= -config.MAX_DRAWDOWN_PCT * 100:
        return True, f"maxDD {dd:.1f}% ≤ -{config.MAX_DRAWDOWN_PCT*100:.0f}%"
    return False, None


def rebalance(trader: Trader) -> dict:
    """Run full rebalance: close all, rank, open top N. Returns summary."""
    log.info("rebalance start")
    # close existing positions
    close_all_positions(trader, "rebalance")
    # fetch daily panel
    panel = fetch_lookback_panel(trader, config.UNIVERSE, config.LOOKBACK_DAYS)
    if panel.empty:
        log.warning("empty panel — skip rebalance")
        return {"opened": 0, "skipped": "no data"}
    asof = panel.index[-1]
    # rank
    picks = strategy.rank_universe(panel, asof, config.LOOKBACK_DAYS,
                                    config.MIN_POSITIVE_RETURN)
    top = strategy.select_top_n(picks, config.TOP_N)
    if not top:
        log.warning("no positive momentum picks — staying в USDT")
        db.set_last_rebalance_ts(int(time.time()))
        return {"opened": 0, "skipped": "no positives"}
    # open new positions
    capital = trader.get_balance_usdt()
    per_pos = strategy.equal_weight_sizing(capital, len(top), trader.fee)
    opened = open_picks(trader, top, per_pos)
    db.set_last_rebalance_ts(int(time.time()))
    log.info("rebalance done", opened=opened, picks=[p.symbol for p in top])
    return {
        "opened": opened,
        "picks": [{"symbol": p.symbol, "lookback_pct": p.lookback_return_pct} for p in top],
        "per_position_usdt": per_pos,
    }


def run_once(trader: Trader) -> dict:
    """One iteration of main loop. Returns status dict."""
    # emergency check
    halt, reason = check_emergency_stop()
    if halt:
        log.error("EMERGENCY STOP", reason=reason)
        return {"action": "emergency_stop", "reason": reason}

    # check stops on existing positions
    stopped = check_stops(trader)

    # update equity
    eq = update_equity(trader)

    # rebalance check
    last_ts = db.get_last_rebalance_ts()
    last = pd.Timestamp(last_ts, unit="s", tz="UTC") if last_ts else None
    now = pd.Timestamp.now(tz="UTC")
    if strategy.should_rebalance(now, last, config.HOLD_DAYS, config.REBALANCE_DAY_OF_MONTH):
        rb = rebalance(trader)
        return {"action": "rebalance", "stops_hit": stopped, "equity": eq, **rb}
    return {"action": "monitor", "stops_hit": stopped, "equity": eq, "open": len(db.get_open_positions())}


def main_loop(trader: Trader, interval_sec: int = None):
    """Loop forever. Check stops + rebalance + log equity."""
    interval = interval_sec or config.CHECK_INTERVAL_SEC
    log.info("scheduler start", mode=config.MODE, interval_sec=interval)
    while True:
        try:
            status = run_once(trader)
            log.info("iter done", **status)
            if status.get("action") == "emergency_stop":
                break
        except Exception as e:
            log.exception("iter error", error=str(e))
        time.sleep(interval)
