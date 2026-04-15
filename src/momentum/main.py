"""Entry point. Init db + scheduler + telegram polling thread."""
from __future__ import annotations

import signal
import sys
import threading
import time

import structlog

from . import config, db, scheduler, telegram_bot
from .trader import Trader

log = structlog.get_logger()

_shutdown = threading.Event()


def telegram_loop():
    """Background thread polling telegram for commands."""
    while not _shutdown.is_set():
        telegram_bot.poll_commands(timeout=25)


def main():
    config.validate()
    db.init_db()
    log.info("momentum-bot starting", mode=config.MODE,
             capital=config.TOTAL_CAPITAL,
             universe_size=len(config.UNIVERSE),
             lookback=config.LOOKBACK_DAYS,
             hold=config.HOLD_DAYS,
             top_n=config.TOP_N,
             stop_pct=config.STOP_LOSS_PCT)

    trader = Trader()

    def shutdown(*_):
        log.info("shutdown signal received")
        _shutdown.set()
        telegram_bot.send("momentum-bot stopping (signal received)")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    telegram_bot.send(f"momentum-bot started ({config.MODE})")

    if config.MODE == "SCAN_ONLY":
        rb = scheduler.rebalance(trader)
        log.info("scan complete", **rb)
        telegram_bot.send(f"scan complete: {rb}")
        return

    # background telegram polling
    tg_thread = threading.Thread(target=telegram_loop, daemon=True)
    tg_thread.start()

    # main scheduler loop with pause/emergency hooks
    while not _shutdown.is_set():
        try:
            if telegram_bot.is_emergency():
                log.error("emergency_stop set in db — exiting")
                telegram_bot.send("emergency_stop triggered, stopping")
                break
            if telegram_bot.is_paused():
                log.info("paused")
                time.sleep(config.CHECK_INTERVAL_SEC)
                continue
            status = scheduler.run_once(trader)
            log.info("iter", **status)
            if status.get("action") == "emergency_stop":
                telegram_bot.alert(f"emergency: {status.get('reason')}")
                break
            if status.get("action") == "rebalance":
                telegram_bot.send(f"rebalance: opened {status.get('opened')} positions: "
                                  + ", ".join(p["symbol"] for p in status.get("picks", [])))
        except Exception as e:
            log.exception("main iter error", error=str(e))
            telegram_bot.alert(f"iter error: {e}")
        time.sleep(config.CHECK_INTERVAL_SEC)

    _shutdown.set()


if __name__ == "__main__":
    main()
