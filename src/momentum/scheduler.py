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
    # fetch enough для vol calculation (max of lookback and vol lookback)
    fetch_days = max(lookback_days, config.VOL_LOOKBACK_DAYS) + 5
    series = {}
    for sym in symbols:
        try:
            ohlcv = trader.fetch_ohlcv(sym, "1d", limit=fetch_days)
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


def calc_vols(panel: pd.DataFrame, symbols: list[str], lookback_days: int) -> dict[str, float]:
    """Compute daily return stdev для each symbol over lookback_days."""
    vols = {}
    if panel.empty:
        return vols
    asof = panel.index[-1]
    start = asof - pd.Timedelta(days=lookback_days)
    window = panel.loc[start:asof]
    for sym in symbols:
        if sym not in window.columns:
            continue
        p = window[sym].dropna()
        if len(p) < 5:
            continue
        rets = p.pct_change().dropna()
        if len(rets) > 0:
            vols[sym] = float(rets.std())
    return vols


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
    """Open positions for each pick (equal-weight). Returns count opened."""
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


def open_picks_custom_sizing(trader: Trader, picks: list[Pick], sizes: dict[str, float]) -> int:
    """Open positions с per-symbol USDT amounts (от vol/invvol sizing)."""
    opened = 0
    for pick in picks:
        usdt = sizes.get(pick.symbol, 0)
        # cap at MAX_POSITION_USD
        if usdt > config.MAX_POSITION_USD:
            log.info("cap position at max", symbol=pick.symbol,
                     requested=usdt, capped=config.MAX_POSITION_USD)
            usdt = config.MAX_POSITION_USD
        if usdt < 10:  # binance min notional ~$10
            log.warning("size below min notional, skip", symbol=pick.symbol, usdt=usdt)
            continue
        try:
            order = trader.market_buy(pick.symbol, usdt)
            db.log_trade(order["symbol"], order["side"], order["filled_units"],
                         order["filled_price"], order["fee_usdt"], order["ts"])
            db.add_position(
                symbol=order["symbol"],
                entry_price=order["filled_price"],
                units=order["filled_units"],
                capital_at_entry=usdt,
                entry_ts=order["ts"],
            )
            opened += 1
        except Exception as e:
            log.error("open failed", symbol=pick.symbol, error=str(e))
    return opened


def _stop_reference_price(trader: Trader, symbol: str) -> float | None:
    """Price used for the stop check. close mode: last CLOSED daily bar (matches
    backtest); tick mode: live price (legacy — killed the paper run via intraday noise)."""
    if config.STOP_CHECK_MODE == "tick":
        return trader.get_price(symbol)
    try:
        bars = trader.fetch_ohlcv(symbol, "1d", limit=2)
        if len(bars) >= 2:
            return float(bars[-2][4])  # close of last finished day
    except Exception as e:
        log.warning("stop ref fetch failed", symbol=symbol, error=str(e))
    return None


def check_stops(trader: Trader) -> int:
    """Check open positions for stop-loss trigger. Close if hit. Returns count stopped."""
    stopped = 0
    for row in db.get_open_positions():
        pos = db_pos_to_position(row)
        price = _stop_reference_price(trader, pos.symbol)
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
    # apply variant
    if config.VARIANT == "timeseries":
        top = strategy.select_all_positive(picks, config.TIMESERIES_MAX_N)
    elif config.VARIANT == "dual":
        # find BTC return для absolute filter
        btc_pick = next((p for p in picks if p.symbol == "BTC/USDT"), None)
        btc_ret = btc_pick.lookback_return_pct if btc_pick else 0
        top = strategy.select_dual_momentum(picks, config.TOP_N, btc_ret)
    else:
        top = strategy.select_top_n(picks, config.TOP_N)
    if not top:
        log.warning("no positive momentum picks — staying в USDT")
        db.set_last_rebalance_ts(int(time.time()))
        return {"opened": 0, "skipped": "no positives"}
    # open new positions с выбранным sizing
    capital = trader.get_balance_usdt()
    if config.SIZING in ("invvol", "voltarget"):
        vols = calc_vols(panel, [p.symbol for p in top], config.VOL_LOOKBACK_DAYS)
        if config.SIZING == "voltarget":
            sizes = strategy.vol_target_sizing(capital, vols,
                                               target_daily_vol=config.VOL_TARGET_DAILY,
                                               fee=trader.fee)
        else:
            sizes = strategy.inverse_vol_sizing(capital, vols, fee=trader.fee)
        opened = open_picks_custom_sizing(trader, top, sizes)
    else:
        per_pos = strategy.equal_weight_sizing(capital, len(top), trader.fee)
        per_pos = min(per_pos, config.MAX_POSITION_USD)
        opened = open_picks(trader, top, per_pos)
    db.set_last_rebalance_ts(int(time.time()))
    log.info("rebalance done", opened=opened, picks=[p.symbol for p in top])
    pick_details = [{"symbol": p.symbol, "lookback_pct": p.lookback_return_pct} for p in top]
    # telegram trade summary
    from . import telegram_bot
    lines = [f"rebalance: {opened} positions opened"]
    for p in top:
        sz_info = f"${per_pos:.0f}" if config.SIZING == "equal" else ""
        lines.append(f"  {p.symbol} ({p.lookback_return_pct:+.1f}% {config.LOOKBACK_DAYS}d) {sz_info}")
    lines.append(f"capital after: ${trader.get_balance_usdt():.2f} USDT free")
    telegram_bot.send("\n".join(lines))

    return {
        "opened": opened,
        "picks": pick_details,
    }


def build_daily_report(trader: Trader) -> str:
    """Сводка: что держим, unrealized PnL, активность за сутки.
    Используется ежедневным отчётом и командой /report."""
    now = pd.Timestamp.now(tz="UTC")
    rows = db.get_open_positions()
    lines = [f"🦊 daily [{config.MODE}] {now:%Y-%m-%d}"]
    pos_val = 0.0
    if rows:
        lines.append("держим:")
        for r in rows:
            price = trader.get_price(r["symbol"]) or r["entry_price"]
            val = r["units"] * price
            pos_val += val
            pnl = (price / r["entry_price"] - 1) * 100
            entry_d = pd.Timestamp(r["entry_ts"], unit="s", tz="UTC")
            lines.append(f"  {r['symbol']} {pnl:+.1f}%"
                         f" (${r['capital_at_entry']:.0f} → ${val:.0f}) с {entry_d:%d.%m}")
    else:
        lines.append("позиций нет — сидим в USDT (нет положительного momentum)")
    usdt = trader.get_balance_usdt()
    lines.append(f"equity: ${usdt + pos_val:.2f} (USDT ${usdt:.2f} + позиции ${pos_val:.2f})")
    realized, fees = db.get_realized_pnl(), db.get_total_fees()
    lines.append(f"realized: ${realized:+.2f} | fees: ${fees:.2f}")
    day_ago = time.time() - 86400
    closed_24h = [r for r in db.get_closed_positions(limit=30)
                  if r.get("closed_ts") and r["closed_ts"] >= day_ago]
    if closed_24h:
        lines.append("закрыто за 24ч:")
        for r in closed_24h:
            lines.append(f"  {r['symbol']} {r['pnl_pct']:+.1f}% [{r['close_reason']}]")
    last_rb = db.get_last_rebalance_ts()
    if last_rb:
        lines.append(f"последний ребаланс: {pd.Timestamp(last_rb, unit='s', tz='UTC'):%d.%m}"
                     f" (день ребаланса: {config.REBALANCE_DAY_OF_MONTH}-е число)")
    return "\n".join(lines)


def send_daily_report(trader: Trader):
    from . import telegram_bot
    telegram_bot.send(build_daily_report(trader))


def run_once(trader: Trader) -> dict:
    """One iteration of main loop. Returns status dict."""
    # emergency check
    halt, reason = check_emergency_stop()
    if halt:
        log.error("EMERGENCY STOP", reason=reason)
        return {"action": "emergency_stop", "reason": reason}

    # check stops on existing positions
    stopped = check_stops(trader)

    # sentinel: DeepSeek negative-news check on held positions
    if config.SENTINEL_ENABLED and config.DEEPSEEK_API_KEY:
        last_sent = db.get_state("last_sentinel_ts")
        now_ts = time.time()
        if last_sent is None or now_ts - float(last_sent) >= config.SENTINEL_INTERVAL_HOURS * 3600:
            from . import sentinel
            try:
                sentinel.run_sentinel(trader)
            except Exception as e:
                log.error("sentinel error", error=str(e))
            db.set_state("last_sentinel_ts", now_ts)

    # daily report at DAILY_REPORT_HOUR UTC (9 UTC = 12:00 MSK)
    now_utc = pd.Timestamp.now(tz="UTC")
    today = str(now_utc.date())
    if now_utc.hour >= config.DAILY_REPORT_HOUR and db.get_state("last_daily_report") != today:
        try:
            send_daily_report(trader)
        except Exception as e:
            log.error("daily report error", error=str(e))
        db.set_state("last_daily_report", today)

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
