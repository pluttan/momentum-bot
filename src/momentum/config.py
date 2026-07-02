"""momentum-bot config — env-driven."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# === Binance API ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# === Telegram ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_OWNER_ID")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY")  # e.g. socks5h://127.0.0.1:2080 on DPI-mangled hosts

# === Mode ===
# SCAN_ONLY — показать ranking + picks, не торговать
# PAPER     — виртуальная торговля (без real orders)
# LIVE      — реальные orders на binance spot
MODE = os.getenv("MODE", "PAPER")

# === Capital ===
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "1000"))
RESERVE_PCT = float(os.getenv("RESERVE_PCT", "0.05"))  # 5% резерв на fees+slippage

# === Strategy params ===
# Defaults: balanced classic (безопаснее для first deploy).
# Real daily maxDD tracking reveals all momentum configs have ~-50% intra-period DD
# (prior rebalance-only measurement was misleading +1800% error).
# For switch в timeseries/hold=90 — raise MAX_DRAWDOWN_PCT to 0.6+.
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "14"))
HOLD_DAYS = int(os.getenv("HOLD_DAYS", "60"))
TOP_N = int(os.getenv("TOP_N", "3"))
# Audit 2026-07: tick-checked -3% stop killed 56/56 paper positions in <24h
# (median hold 0.6h vs 60d plan). Backtest sweep: no stop beats -3%; -20% is
# catastrophe insurance only. Checked on daily CLOSE (see STOP_CHECK_MODE).
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-0.20"))
# close — trigger on last CLOSED daily bar (matches backtest); tick — legacy behaviour
STOP_CHECK_MODE = os.getenv("STOP_CHECK_MODE", "close").lower()
MIN_POSITIVE_RETURN = float(os.getenv("MIN_POSITIVE_RETURN", "0.0"))

# === Sentinel (DeepSeek negative-news watchdog) ===
# LLM has veto/exit power only — never generates entries (cross-market OOS finding:
# negative news kills a coin everywhere; positive news is sell-the-news).
SENTINEL_ENABLED = os.getenv("SENTINEL_ENABLED", "true").lower() == "true"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
SENTINEL_INTERVAL_HOURS = float(os.getenv("SENTINEL_INTERVAL_HOURS", "6"))
SENTINEL_ACTION = os.getenv("SENTINEL_ACTION", "alert").lower()  # alert | sell
SENTINEL_CHANNELS = os.getenv(
    "SENTINEL_CHANNELS", "binance_announcements,cointelegraph,markettwits").split(",")
SENTINEL_PROXY = os.getenv("SENTINEL_PROXY")  # e.g. socks5h://127.0.0.1:2080 if t.me blocked

# Variant selector:
#   "classic" (default) — pick top TOP_N by past return
#   "dual" — top TOP_N AND each must beat BTC return
#   "timeseries" — buy ALL positive-momentum assets equal-weight (max N)
VARIANT = os.getenv("VARIANT", "classic").lower()
TIMESERIES_MAX_N = int(os.getenv("TIMESERIES_MAX_N", "8"))

# Sizing selector (within selected variant):
#   "equal" (default) — equal USDT per position
#   "invvol" — weights = (1/vol) / sum(1/vol), underweight volatile assets
#   "voltarget" — target daily portfolio vol (VOL_TARGET_DAILY), caps volatile assets
# Backtest 4y hold=30 N=8:
#   equal:     +150% annual, -36% maxDD
#   voltarget: +130% annual, -29% maxDD  (35% DD reduction for -20pp return)
SIZING = os.getenv("SIZING", "equal").lower()
VOL_TARGET_DAILY = float(os.getenv("VOL_TARGET_DAILY", "0.02"))  # 2% daily σ target
VOL_LOOKBACK_DAYS = int(os.getenv("VOL_LOOKBACK_DAYS", "30"))

# === Universe ===
# Top USDT-spot pairs. Refreshed via scripts/universe_refresh.py.
# Current list: 13 legacy (backtest basis) + 9 added 2026-04 (≥4y spot history).
UNIVERSE = [
    # legacy 4y backtest basis:
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "TRX/USDT", "ZEC/USDT", "PAXG/USDT",
    "DASH/USDT", "TAO/USDT", "PEPE/USDT",
    # added 2026-04 via universe_refresh (high volume + ≥4y spot listed):
    "LINK/USDT", "AAVE/USDT", "AVAX/USDT", "NEAR/USDT", "LTC/USDT",
    "CHZ/USDT", "FET/USDT", "ENJ/USDT",
    # EUR/USDT omitted — stable-ish, volatility too low для momentum picking
]
MIN_VOLUME_24H = float(os.getenv("MIN_VOLUME_24H", "10000000"))  # $10M min daily volume

# === Fees ===
FEE_RATE = float(os.getenv("FEE_RATE", "0.001"))           # 0.1% base
BNB_FEE_RATE = float(os.getenv("BNB_FEE_RATE", "0.00075"))  # 0.075% with BNB
USE_BNB_DISCOUNT = os.getenv("USE_BNB_DISCOUNT", "true").lower() == "true"

# === Risk caps ===
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "0.30"))  # halt at -30%
MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "5000"))  # safety cap
MAX_DAILY_LOSS_USD = float(os.getenv("MAX_DAILY_LOSS_USD", "300"))

# === Schedule ===
# rebalance happens на DAY_OF_MONTH каждого месяца
REBALANCE_DAY_OF_MONTH = int(os.getenv("REBALANCE_DAY_OF_MONTH", "1"))
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "300"))  # 5 min stop-loss check

# === Database ===
DB_PATH = str(PROJECT_ROOT / "momentum.db")

# === Telegram report cadence ===
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))


def validate() -> None:
    """Fail-fast: проверить обязательные env vars для текущего MODE."""
    required_telegram = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "TELEGRAM_OWNER_ID": TELEGRAM_OWNER_ID,
    }
    required_live = {
        "BINANCE_API_KEY": BINANCE_API_KEY,
        "BINANCE_API_SECRET": BINANCE_API_SECRET,
    }
    missing = []
    if MODE == "LIVE":
        missing += [k for k, v in required_live.items() if not v]
    missing += [k for k, v in required_telegram.items() if not v]
    if missing:
        raise RuntimeError(f"Missing env vars for MODE={MODE}: {', '.join(missing)}")


def effective_fee() -> float:
    """Return current fee rate based on BNB discount setting."""
    return BNB_FEE_RATE if USE_BNB_DISCOUNT else FEE_RATE
