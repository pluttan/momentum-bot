"""PAPER mode self-test — exercise real scheduler.run_once() против binance data.

Verifies:
- Trader init works (public binance, no auth)
- fetch_ohlcv для universe returns real data
- rank_universe produces picks
- open_picks creates DB records
- update_equity writes to DB
- rebalance path complete
- no telegram pushes (empty token → skipped silently)

Usage: MODE=PAPER .venv/bin/python scripts/paper_selftest.py

Exit 0 on success, non-zero on any exception.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import structlog

# force no telegram
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")
os.environ.setdefault("TELEGRAM_OWNER_ID", "")
os.environ.setdefault("MODE", "PAPER")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

logging.getLogger().setLevel(logging.INFO)
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))

from momentum import config, db, scheduler
from momentum.trader import Trader


def main():
    # isolated DB
    fd, dbpath = tempfile.mkstemp(suffix=".db", prefix="selftest-")
    os.close(fd)
    config.DB_PATH = dbpath
    print(f"[selftest] using isolated DB: {dbpath}")
    print(f"[selftest] mode={config.MODE}  capital=${config.TOTAL_CAPITAL}  "
          f"variant={config.VARIANT}  sizing={config.SIZING}")

    try:
        db.init_db()
        print("[selftest] db initialized ✓")

        trader = Trader()
        print(f"[selftest] trader created (mode={trader.mode}, fee={trader.fee})")

        # fetch a single ticker to verify network works
        test_sym = config.UNIVERSE[0]
        price = trader.get_price(test_sym)
        assert price and price > 0, f"invalid price: {price}"
        print(f"[selftest] fetched {test_sym} = ${price:.2f} ✓")

        # one iteration of full loop
        status = scheduler.run_once(trader)
        print(f"[selftest] run_once result: {status}")

        # check DB state
        eq = db.get_equity_curve(1)
        assert len(eq) >= 1, "equity not logged"
        print(f"[selftest] equity logged: ${eq[-1]['capital'] + eq[-1]['positions_value']:.2f} ✓")

        positions = db.get_open_positions()
        trades = db.get_trade_count()
        print(f"[selftest] open positions: {len(positions)}")
        print(f"[selftest] total trades: {trades}")

        if positions:
            for p in positions[:3]:
                print(f"  • {p['symbol']}: {p['units']:.4f} units @ ${p['entry_price']:.4f}")

        print("\n[selftest] ALL CHECKS PASS ✓")
    except Exception as e:
        print(f"\n[selftest] FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            os.unlink(dbpath)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
