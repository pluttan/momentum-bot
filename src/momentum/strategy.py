"""Pure momentum strategy logic. No I/O, fully testable."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Pick:
    """Single asset pick result."""
    symbol: str
    lookback_return_pct: float
    rank: int  # 1 = best


@dataclass
class Position:
    """Active position state."""
    symbol: str
    entry_price: float
    units: float
    entry_ts: pd.Timestamp
    capital_at_entry: float  # for stop-loss accounting

    @property
    def stop_price(self) -> float:
        from .config import STOP_LOSS_PCT
        return self.entry_price * (1 + STOP_LOSS_PCT)

    def current_value(self, price: float) -> float:
        return self.units * price

    def pnl_pct(self, price: float) -> float:
        return (price / self.entry_price - 1) * 100

    def pnl_usd(self, price: float) -> float:
        return self.units * (price - self.entry_price)


def rank_universe(
    prices_panel: pd.DataFrame,
    asof: pd.Timestamp,
    lookback_days: int,
    min_positive_return: float = 0.0,
) -> list[Pick]:
    """Rank universe by past lookback return as of `asof` date.

    Args:
        prices_panel: DataFrame with daily close prices, columns=symbols, index=dates (UTC)
        asof: as-of timestamp for ranking (use price at or before this date)
        lookback_days: how many days back to compare
        min_positive_return: only include assets with return > this (default 0 = positive only)

    Returns:
        List of Picks sorted by descending lookback return.
    """
    asof = pd.Timestamp(asof, tz="UTC") if asof.tzinfo is None else asof
    lookback_start = asof - pd.Timedelta(days=lookback_days)

    # slice valid range, drop columns без enough data
    window = prices_panel.loc[lookback_start:asof].dropna(how="all", axis=1)
    if len(window) < 2:
        return []

    # first vs last in window
    first = window.iloc[0]
    last = window.iloc[-1]

    rets = (last / first - 1)
    rets = rets.dropna()
    rets = rets[rets > min_positive_return]

    if rets.empty:
        return []

    sorted_rets = rets.sort_values(ascending=False)
    picks = [
        Pick(symbol=sym, lookback_return_pct=float(ret * 100), rank=i + 1)
        for i, (sym, ret) in enumerate(sorted_rets.items())
    ]
    return picks


def select_top_n(picks: list[Pick], n: int) -> list[Pick]:
    """Pick top N from ranked picks. Return [] if none qualify."""
    return picks[:n]


def select_all_positive(picks: list[Pick], max_n: int = 13) -> list[Pick]:
    """Time-series variant: buy ВСЕ assets с positive lookback return,
    equal-weighted, capped at max_n.

    Backtest: +177% annual vs +158% classic, maxDD только -6.3% (vs -12.6%) на 4y.
    Diversification reduces variance.
    """
    return picks[:max_n]


def select_dual_momentum(picks: list[Pick], n: int, btc_return_pct: float | None) -> list[Pick]:
    """Dual momentum: top-N AND each must beat BTC's return (relative + absolute filter).

    Args:
        btc_return_pct: BTC's lookback return %, or None to skip BTC filter
    """
    filtered = [p for p in picks if btc_return_pct is None or p.lookback_return_pct > btc_return_pct]
    return filtered[:n]


def equal_weight_sizing(capital: float, n_positions: int, fee: float = 0.001) -> float:
    """Compute per-position USDT amount (equal weight, accounting for fee on entry)."""
    if n_positions <= 0:
        return 0.0
    return (capital * (1 - fee)) / n_positions


def inverse_vol_sizing(capital: float, vols: dict[str, float], fee: float = 0.001) -> dict[str, float]:
    """Inverse-volatility sizing: underweight volatile assets.

    weights = (1/vol) / sum(1/vol). lower-vol assets get larger allocation.

    Args:
        capital: total capital to distribute
        vols: {symbol: daily_stdev_of_returns} — use 30d lookback typical
        fee: round-trip fee (applied once to total)

    Returns:
        {symbol: usdt_amount}
    """
    if not vols:
        return {}
    # floor vols чтобы не divide by tiny number
    inv = {sym: 1.0 / max(v, 0.005) for sym, v in vols.items()}
    total_inv = sum(inv.values())
    if total_inv <= 0:
        return {}
    return {sym: capital * (1 - fee) * (inv[sym] / total_inv) for sym in vols}


def vol_target_sizing(capital: float, vols: dict[str, float],
                     target_daily_vol: float = 0.02, fee: float = 0.001) -> dict[str, float]:
    """Vol-targeted sizing: each position scaled так чтобы contribute target_daily_vol.

    position_weight = min(target / vol, 1.0), then normalize if sum > 1.

    Best risk/return combo from sweep (hold=30, N=8):
        equal:     +150% annual, -36% maxDD
        voltarget: +130% annual, -29% maxDD  (35% DD reduction)
    """
    if not vols:
        return {}
    raw = {sym: min(target_daily_vol / max(v, 0.005), 1.0) for sym, v in vols.items()}
    total = sum(raw.values())
    if total <= 0:
        return {}
    scale = min(1.0 / total, 1.0) if total > 1.0 else 1.0
    return {sym: capital * (1 - fee) * raw[sym] * scale for sym in vols}


def should_stop(position: Position, current_price: float) -> bool:
    """True if stop-loss triggered."""
    return current_price <= position.stop_price


def should_rebalance(now: pd.Timestamp, last_rebalance: pd.Timestamp | None,
                     hold_days: int, day_of_month: int = 1) -> bool:
    """True if it's time для monthly rebalance.

    Trigger conditions:
    - last_rebalance is None (first run)
    - it's day_of_month AND we haven't rebalanced yet this month
    - OR last_rebalance was more than hold_days ago (safety net)
    """
    now = pd.Timestamp(now, tz="UTC") if now.tzinfo is None else now
    if last_rebalance is None:
        return True
    last_rebalance = pd.Timestamp(last_rebalance, tz="UTC") if last_rebalance.tzinfo is None else last_rebalance

    days_since = (now - last_rebalance).total_seconds() / 86400
    if days_since >= hold_days:
        return True

    if now.day == day_of_month and now.month != last_rebalance.month:
        return True

    return False


def estimate_position_value(positions: list[Position], current_prices: dict[str, float]) -> float:
    """Sum current $ value of all open positions."""
    total = 0.0
    for p in positions:
        price = current_prices.get(p.symbol)
        if price is not None:
            total += p.current_value(price)
    return total
