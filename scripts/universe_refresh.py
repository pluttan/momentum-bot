"""Re-discover top USDT spot pairs с ≥4y history for momentum universe.

Usage: .venv/bin/python scripts/universe_refresh.py

Prints recommended UNIVERSE list. Quarterly task — paste output в config.py.
"""
from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import ccxt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from momentum import config

MIN_HISTORY_DAYS = 1460  # 4y
MIN_VOLUME_24H = 10_000_000
TARGET_SIZE = 20

BLACKLIST = {"USDC/USDT", "BUSD/USDT", "TUSD/USDT", "FDUSD/USDT", "DAI/USDT",
             "USDP/USDT", "USD1/USDT", "WBTC/USDT", "WBETH/USDT", "RLUSD/USDT"}


def main():
    print("[universe] scanning binance USDT-spot pairs...")
    ex = ccxt.binance({"enableRateLimit": True})
    ex.load_markets()
    tickers = ex.fetch_tickers()
    pairs = []
    for sym, t in tickers.items():
        if sym in BLACKLIST:
            continue
        m = ex.market(sym) if sym in ex.markets else None
        if not m or m["type"] != "spot" or not m["active"] or m["quote"] != "USDT":
            continue
        vol = t.get("quoteVolume") or 0
        if vol < MIN_VOLUME_24H:
            continue
        pairs.append((sym, vol))
    pairs.sort(key=lambda x: x[1], reverse=True)

    min_ts = int((datetime.now(UTC) - timedelta(days=MIN_HISTORY_DAYS)).timestamp() * 1000)
    qualified = []
    print(f"  checking history ≥ {MIN_HISTORY_DAYS}d for {len(pairs[:TARGET_SIZE * 3])} candidates...")
    for sym, vol in pairs[:TARGET_SIZE * 3]:
        try:
            first = ex.fetch_ohlcv(sym, "1d", since=0, limit=1)
            if first and first[0][0] <= min_ts:
                qualified.append((sym, vol))
                print(f"  ✓ {sym:<15} vol=${vol/1e6:>8.1f}M")
                if len(qualified) >= TARGET_SIZE:
                    break
            time.sleep(ex.rateLimit / 1000)
        except Exception as e:
            print(f"  skip {sym}: {e}")

    print(f"\n[result] {len(qualified)} pairs with ≥{MIN_HISTORY_DAYS}d history")
    print("\nUNIVERSE list для config.py (paste it):")
    print("UNIVERSE = [")
    for sym, _ in qualified:
        print(f'    "{sym}",')
    print("]")
    print(f"\nCurrent config.UNIVERSE has {len(config.UNIVERSE)} pairs.")
    in_current = set(config.UNIVERSE)
    in_new = {s for s, _ in qualified}
    added = in_new - in_current
    removed = in_current - in_new
    if added:
        print(f"To add: {sorted(added)}")
    if removed:
        print(f"To remove: {sorted(removed)}")
    if not added and not removed:
        print("Universe unchanged — no refresh needed.")


if __name__ == "__main__":
    main()
