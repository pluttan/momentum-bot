"""Compare 3 momentum variants:
- A: classic cross-sectional (current default) — pick top-N с highest lookback return
- B: dual momentum — top-N AND each must beat BTC return (relative + absolute)
- C: time-series — buy each asset с return > threshold, equal-weighted (no ranking)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from momentum import config

LOOKBACK = config.LOOKBACK_DAYS
HOLD = config.HOLD_DAYS
TOP_N = config.TOP_N
STOP = config.STOP_LOSS_PCT
FEE = config.effective_fee()
START = date(2022, 1, 1)
END = date(2026, 1, 1)


def load_panel():
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    series = {}
    cache = ROOT / "data"
    for sym in config.UNIVERSE:
        cf = cache / f"{sym.replace('/', '_')}_1d.parquet"
        if cf.exists():
            df = pd.read_parquet(cf)
        else:
            since = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
            all_bars = []
            cursor = since
            end_ts = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000)
            while cursor < end_ts:
                try:
                    batch = ex.fetch_ohlcv(sym, "1d", since=cursor, limit=1000)
                except Exception:
                    break
                if not batch: break
                all_bars.extend(batch)
                cursor = batch[-1][0] + 1
                if len(batch) < 1000: break
            if not all_bars: continue
            df = pd.DataFrame(all_bars, columns=["ts", "o", "h", "l", "c", "v"])
            df.to_parquet(cf, index=False)
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        series[sym] = df.set_index("dt")["c"]
    return pd.DataFrame(series).dropna(how="all")


def run(prices, variant: str):
    """HONEST: tracks equity daily within hold period (not only at rebalance)."""
    capital = 1000.0
    positions = {}
    trades = []
    cur = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    daily_eq = {}
    while cur < end:
        nxt = min(cur + timedelta(days=HOLD), end)
        if positions:
            for sym, (entry, units) in positions.items():
                w = prices.loc[cur:nxt, sym].dropna()
                if w.empty: continue
                stop_p = entry * (1 + STOP)
                exit_p = stop_p if (w <= stop_p).any() else w.iloc[-1]
                capital += units * exit_p * (1 - FEE)
                trades.append((exit_p / entry - 1) * 100)
        positions = {}
        lbs = cur - timedelta(days=LOOKBACK)
        lbw = prices.loc[lbs:cur].dropna(how="all", axis=1)
        if len(lbw) < 3: cur = nxt; continue
        rets = lbw.iloc[-1] / lbw.iloc[0] - 1

        if variant == "classic":
            picks = rets[rets > 0].nlargest(TOP_N)
        elif variant == "dual":
            btc_ret = rets.get("BTC/USDT", 0.0)
            picks = rets[(rets > 0) & (rets > btc_ret)].nlargest(TOP_N)
        elif variant == "timeseries":
            picks = rets[rets > 0]
        else:
            picks = pd.Series(dtype=float)

        if picks.empty:
            cur = nxt; continue
        per_pos = capital / len(picks)
        for sym in picks.index:
            p = prices.loc[cur:, sym].dropna()
            if p.empty: continue
            entry = p.iloc[0]
            units = (per_pos * (1 - FEE)) / entry
            positions[sym] = (entry, units)
            capital -= per_pos
        # daily equity tracking within hold period
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
    eq = pd.Series(daily_eq)
    dd_min = ((eq - eq.cummax()) / eq.cummax() * 100).min() if len(eq) > 0 else 0.0
    return {
        "final": capital, "annual": ann, "maxDD": dd_min,
        "trades": len(trades), "wins": wins,
        "wrate": wins / len(trades) * 100 if trades else 0,
    }


def main():
    prices = load_panel()
    print(f"[variants] panel {prices.shape}, lb={LOOKBACK} hold={HOLD} top={TOP_N}")
    print(f"\n{'variant':<14} {'final$':>9} {'annual%':>9} {'maxDD%':>8} {'trades':>7} {'wrate%':>7}")
    print("-" * 60)
    for v in ["classic", "dual", "timeseries"]:
        r = run(prices, v)
        print(f"{v:<14} ${r['final']:>8.0f} {r['annual']:>+8.1f}% {r['maxDD']:>+7.1f}% "
              f"{r['trades']:>7} {r['wrate']:>6.1f}%")


if __name__ == "__main__":
    main()
