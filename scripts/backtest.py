"""Re-run momentum backtest from scratch на cached daily data.

Reuses prices fetched через scan or live ohlcv. Accepts custom params via env.

Usage:
  .venv/bin/python scripts/backtest.py
  START=2023-01-01 END=2026-01-01 LOOKBACK=14 HOLD=60 TOP_N=3 STOP=-0.03 \
    .venv/bin/python scripts/backtest.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from momentum import config

START = date.fromisoformat(os.getenv("START", "2022-01-01"))
END = date.fromisoformat(os.getenv("END", "2026-01-01"))
LOOKBACK = int(os.getenv("LOOKBACK", str(config.LOOKBACK_DAYS)))
HOLD = int(os.getenv("HOLD", str(config.HOLD_DAYS)))
TOP_N = int(os.getenv("TOP_N", str(config.TOP_N)))
STOP = float(os.getenv("STOP", str(config.STOP_LOSS_PCT)))
FEE = config.effective_fee()


def fetch_to_panel():
    """Fetch daily prices via ccxt для full universe. Cache в data/."""
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    series = {}
    cache_dir = ROOT / "data"
    cache_dir.mkdir(exist_ok=True)
    for sym in config.UNIVERSE:
        cache_file = cache_dir / f"{sym.replace('/', '_')}_1d.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            print(f"  fetching {sym}...")
            since = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
            all_bars = []
            cursor = since
            end_ts = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000)
            while cursor < end_ts:
                try:
                    batch = ex.fetch_ohlcv(sym, "1d", since=cursor, limit=1000)
                except Exception as e:
                    print(f"    err {e}")
                    break
                if not batch: break
                all_bars.extend(batch)
                cursor = batch[-1][0] + 1
                if len(batch) < 1000: break
            if not all_bars:
                continue
            df = pd.DataFrame(all_bars, columns=["ts", "o", "h", "l", "c", "v"])
            df.to_parquet(cache_file, index=False)
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        series[sym] = df.set_index("dt")["c"]
    return pd.DataFrame(series).dropna(how="all")


def run_backtest(prices: pd.DataFrame) -> dict:
    """Run backtest. IMPORTANT: tracks equity daily within hold periods (honest maxDD).

    Prior bug: measuring eq only at rebalance points hid ~50% intra-period drawdowns.
    """
    capital = 1000.0
    positions = {}  # {sym: (entry_price, units)}
    trades = []
    cur = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    daily_eq = {}  # daily equity marks (for honest DD)

    while cur < end:
        nxt = min(cur + timedelta(days=HOLD), end)
        # close existing
        if positions:
            for sym, (entry, units) in positions.items():
                w = prices.loc[cur:nxt, sym].dropna()
                if w.empty: continue
                stop_price = entry * (1 + STOP)
                if (w <= stop_price).any():
                    exit_p = stop_price
                else:
                    exit_p = w.iloc[-1]
                capital += units * exit_p * (1 - FEE)
                trades.append((exit_p / entry - 1) * 100)
        positions = {}
        # rank
        lbs = cur - timedelta(days=LOOKBACK)
        lbw = prices.loc[lbs:cur].dropna(how="all", axis=1)
        if len(lbw) < 3:
            cur = nxt; continue
        rets = lbw.iloc[-1] / lbw.iloc[0] - 1
        rets = rets[rets > config.MIN_POSITIVE_RETURN]
        if rets.empty:
            cur = nxt; continue
        top = rets.nlargest(min(TOP_N, len(rets)))
        per_pos = capital / len(top)
        for sym in top.index:
            p = prices.loc[cur:, sym].dropna()
            if p.empty: continue
            entry = p.iloc[0]
            units = (per_pos * (1 - FEE)) / entry
            positions[sym] = (entry, units)
            capital -= per_pos
        # track equity daily within hold period
        for day in pd.date_range(cur, nxt, freq="D"):
            if day > end: break
            val = capital
            for sym, (_e, u) in positions.items():
                p = prices.loc[:day, sym].dropna()
                if not p.empty: val += u * p.iloc[-1]
            daily_eq[day] = val
        cur = nxt

    if positions:
        for sym, (_e, u) in positions.items():
            w = prices.loc[:end, sym].dropna()
            if not w.empty:
                capital += u * w.iloc[-1] * (1 - FEE)

    years = (END - START).days / 365
    ann = ((capital / 1000) ** (1/years) - 1) * 100 if capital > 0 else -100
    wins = sum(1 for t in trades if t > 0)
    eq_series = pd.Series(daily_eq)
    if len(eq_series) > 0:
        peak = eq_series.cummax()
        dd_min = ((eq_series - peak) / peak * 100).min()
    else:
        dd_min = 0.0
    return {
        "final": capital, "annual_pct": ann, "max_dd": dd_min,
        "trades": len(trades), "wins": wins,
        "winrate": wins / len(trades) * 100 if trades else 0,
    }


def main():
    print(f"[backtest] {START} → {END}, lookback={LOOKBACK}, hold={HOLD}, top={TOP_N}, stop={STOP}")
    print(f"  universe: {len(config.UNIVERSE)} symbols")
    prices = fetch_to_panel()
    print(f"  panel: {prices.shape}")
    r = run_backtest(prices)
    print("\n=== RESULT ===")
    print(f"  $1000 → ${r['final']:.2f}")
    print(f"  annualized: {r['annual_pct']:+.1f}%")
    print(f"  maxDD: {r['max_dd']:.1f}%")
    print(f"  trades: {r['trades']} (wins {r['winrate']:.1f}%)")


if __name__ == "__main__":
    main()
