"""One-shot scan: print current ranking + top-N picks для universe.
Doesn't trade. Used для daily preview.

Usage: .venv/bin/python scripts/scan.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from momentum import config, scheduler, strategy
from momentum.trader import Trader


def main():
    print(f"[scan] universe={len(config.UNIVERSE)} pairs, "
          f"lookback={config.LOOKBACK_DAYS}d, top_n={config.TOP_N}")
    trader = Trader()
    panel = scheduler.fetch_lookback_panel(trader, config.UNIVERSE, config.LOOKBACK_DAYS)
    if panel.empty:
        print("no data fetched")
        return
    asof = panel.index[-1]
    picks = strategy.rank_universe(panel, asof, config.LOOKBACK_DAYS, config.MIN_POSITIVE_RETURN)
    if not picks:
        print(f"\n[scan] no positive-momentum assets at {asof.date()} — bot would stay в USDT")
        return
    print(f"\n=== ranking as of {asof.date()} ===")
    print(f"{'rank':>4} {'symbol':<14} {'lookback%':>10}")
    for p in picks:
        marker = "★" if p.rank <= config.TOP_N else " "
        print(f"{p.rank:>3}{marker} {p.symbol:<14} {p.lookback_return_pct:>+9.2f}%")

    print(f"\n=== top {config.TOP_N} picks (would be bought) ===")
    for p in strategy.select_top_n(picks, config.TOP_N):
        print(f"  {p.symbol:<14} +{p.lookback_return_pct:.2f}%")


if __name__ == "__main__":
    main()
