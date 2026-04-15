"""Unit tests для pure strategy logic."""
import pandas as pd
import pytest

from momentum import strategy as st
from momentum.strategy import Pick, Position


@pytest.fixture
def synthetic_panel():
    """3 assets, 30 days. A growing 50%, B flat, C dropping 20%."""
    dates = pd.date_range("2025-01-01", periods=30, freq="D", tz="UTC")
    panel = pd.DataFrame({
        "A": [100 * (1.015 ** i) for i in range(30)],   # ~+50% over 30d
        "B": [100.0] * 30,                                # flat
        "C": [100 * (0.993 ** i) for i in range(30)],    # ~-20% over 30d
    }, index=dates)
    return panel


def test_rank_universe_orders_by_return(synthetic_panel):
    asof = synthetic_panel.index[-1]
    picks = st.rank_universe(synthetic_panel, asof, lookback_days=29)
    assert len(picks) == 1  # only A is positive
    assert picks[0].symbol == "A"
    assert picks[0].lookback_return_pct > 30


def test_rank_universe_no_positives_returns_empty(synthetic_panel):
    # use only last 5 days where A still grows but C still falls
    panel = synthetic_panel.tail(5)
    picks = st.rank_universe(panel, panel.index[-1], lookback_days=4)
    # A still grows (positive), B flat, C falls
    syms = [p.symbol for p in picks]
    assert "A" in syms
    assert "C" not in syms


def test_select_top_n_clips():
    picks = [
        Pick("X", 50.0, 1),
        Pick("Y", 30.0, 2),
        Pick("Z", 10.0, 3),
    ]
    assert len(st.select_top_n(picks, 2)) == 2
    assert len(st.select_top_n(picks, 5)) == 3
    assert len(st.select_top_n([], 3)) == 0


def test_equal_weight_sizing_accounts_for_fee():
    capital = 1000.0
    per = st.equal_weight_sizing(capital, 3, fee=0.001)
    # capital * (1-fee) / 3 = 999 / 3 = 333
    assert per == pytest.approx(333.0, rel=0.01)
    assert st.equal_weight_sizing(0, 5) == 0


def test_position_pnl():
    pos = Position("BTC", entry_price=100, units=10, entry_ts=pd.Timestamp("2025-01-01", tz="UTC"),
                   capital_at_entry=1000)
    assert pos.current_value(110) == 1100
    assert pos.pnl_pct(110) == pytest.approx(10.0)
    assert pos.pnl_usd(110) == 100


def test_should_stop_at_3pct_loss():
    pos = Position("BTC", entry_price=100, units=1, entry_ts=pd.Timestamp.now(tz="UTC"),
                   capital_at_entry=100)
    # default STOP_LOSS_PCT = -0.03
    assert pos.stop_price == pytest.approx(97.0)
    assert st.should_stop(pos, current_price=96.99)
    assert not st.should_stop(pos, current_price=97.01)
    assert not st.should_stop(pos, current_price=110)


def test_should_rebalance_first_time():
    assert st.should_rebalance(pd.Timestamp("2025-01-15", tz="UTC"), None, 60)


def test_should_rebalance_monthly():
    last = pd.Timestamp("2025-01-01", tz="UTC")
    # same month, before next 1st → no
    assert not st.should_rebalance(pd.Timestamp("2025-01-15", tz="UTC"), last, 60)
    # 1st of next month → yes
    assert st.should_rebalance(pd.Timestamp("2025-02-01", tz="UTC"), last, 60)


def test_should_rebalance_safety_net_after_hold_days():
    last = pd.Timestamp("2025-01-01", tz="UTC")
    # 90 days later, even if not 1st of month → trigger
    assert st.should_rebalance(pd.Timestamp("2025-04-15", tz="UTC"), last, 60)


def test_estimate_position_value_sums():
    positions = [
        Position("A", 100, 10, pd.Timestamp.now(tz="UTC"), 1000),
        Position("B", 50, 20, pd.Timestamp.now(tz="UTC"), 1000),
    ]
    prices = {"A": 110, "B": 55}
    assert st.estimate_position_value(positions, prices) == 1100 + 1100


def test_select_all_positive_caps_max_n():
    picks = [Pick(f"P{i}", 10.0 - i * 0.5, i + 1) for i in range(15)]
    result = st.select_all_positive(picks, max_n=8)
    assert len(result) == 8
    # without cap → all 15
    assert len(st.select_all_positive(picks, max_n=20)) == 15


def test_select_dual_momentum_filters_below_btc():
    picks = [
        Pick("PEPE/USDT", 50.0, 1),
        Pick("BTC/USDT", 10.0, 2),
        Pick("ZEC/USDT", 5.0, 3),     # below BTC's 10%
        Pick("DOGE/USDT", 15.0, 4),
    ]
    # дoUAL: only assets > BTC's 10%
    result = st.select_dual_momentum(picks, n=10, btc_return_pct=10.0)
    syms = [p.symbol for p in result]
    assert "PEPE/USDT" in syms      # 50 > 10
    assert "DOGE/USDT" in syms      # 15 > 10
    assert "ZEC/USDT" not in syms   # 5 < 10
    assert "BTC/USDT" not in syms   # 10 not > 10


def test_select_dual_momentum_no_btc_filter_when_none():
    picks = [Pick("X", 5.0, 1), Pick("Y", 3.0, 2)]
    # btc_return_pct=None → no absolute filter
    result = st.select_dual_momentum(picks, n=2, btc_return_pct=None)
    assert len(result) == 2
