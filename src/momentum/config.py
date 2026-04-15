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

# === Mode ===
# SCAN_ONLY — показать ranking + picks, не торговать
# PAPER     — виртуальная торговля (без real orders)
# LIVE      — реальные orders на binance spot
MODE = os.getenv("MODE", "PAPER")

# === Capital ===
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "1000"))
RESERVE_PCT = float(os.getenv("RESERVE_PCT", "0.05"))  # 5% резерв на fees+slippage

# === Strategy params (best from grid-bot research) ===
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "14"))
HOLD_DAYS = int(os.getenv("HOLD_DAYS", "60"))
TOP_N = int(os.getenv("TOP_N", "3"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-0.03"))
MIN_POSITIVE_RETURN = float(os.getenv("MIN_POSITIVE_RETURN", "0.0"))  # only buy assets with > X% lookback

# === Universe ===
# Top USDT-spot pairs с ≥4y history. Refresh quarterly via scripts/universe_refresh.py.
UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "TRX/USDT", "ZEC/USDT", "DASH/USDT",
    "TAO/USDT", "PAXG/USDT", "PEPE/USDT",
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
