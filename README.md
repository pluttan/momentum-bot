<div align="center">

# momentum-bot

**Binance spot momentum trading bot with trailing stops and Telegram control**


</div>

Spot-only momentum trading bot for Binance. Each hold period it ranks a dynamically discovered universe of liquid USDT pairs by a blended momentum score (total return + EWM acceleration + volume surge), buys the top-N performers, and holds until the next rebalance or a trailing stop triggers. Includes a React web dashboard with built-in backtester, a Telegram bot for monitoring and control, and Optuna parameter optimization. Supports multiple parallel trading slots, each with its own mode, capital, and parameter overrides.

## ■ Features

- ❖ **Momentum strategy** — 8-day lookback, 9-day hold, top-2 concentrated bets, blended total-return + EWM-acceleration + volume-surge ranking
- ❖ **Trailing stop** — ~7% from high-watermark, ratchets up; ~-1% hard floor per position
- ❖ **3 modes** — SCAN_ONLY (rank only), PAPER (virtual trades in SQLite), LIVE (real Binance orders)
- ❖ **Multi-slot** — run several PAPER/LIVE instances in parallel, each with its own DB, capital, and param overrides
- ❖ **Telegram bot** — `/status`, `/positions`, `/pnl`, `/history`, `/params`, `/top`, `/pause`, `/resume`, `/stop`, `/reload`
- ❖ **Web dashboard** — React SPA (equity curve, allocation, trades log) served by FastAPI, with an in-browser backtest runner
- ❖ **Backtesting** — multi-year historical simulation with Optuna (TPE) parameter optimization
- ❖ **Dynamic universe** — auto-discovers all liquid USDT-spot pairs by 24h volume, with optional Seed/Monitoring tag filtering
- ❖ **Risk caps** — MAX_DRAWDOWN_PCT (25% default), daily-loss cap, no leverage, spot-only
- ❖ **BNB fee discount** — 0.075% effective commission rate

## ■ Stack

<div align="center">

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Exchange | Binance via ccxt |
| Data | pandas + numpy + pyarrow |
| Optimization | Optuna (TPE) |
| Backend | FastAPI + uvicorn + Jinja2 |
| Frontend | React 19 + TypeScript + Vite + Tailwind |
| Charts | lightweight-charts |
| Database | SQLite |
| Alerts | Telegram Bot API |
| Logging | structlog |

</div>

## ■ How It Works

```
1. Auto-discover all liquid USDT-spot pairs on Binance by 24h volume (≥$10M threshold).
2. Rank the universe by a blended momentum score: total return + EWM acceleration + volume surge over an 8-day lookback.
3. Buy the top-2 ranked pairs; hold for a 9-day period or until a trailing stop triggers (~7% from high-watermark, ~-1% hard floor).
4. On each rebalance cycle, repeat the scan-rank-buy loop; multi-slot mode allows parallel PAPER/LIVE instances with independent capital and params.
5. Monitor and control the bot in real time via Telegram commands or the React web dashboard (equity curve, allocation, trade log, in-browser backtest runner).
```

## ■ Usage

```bash
# Install (uv venv + editable deps)
make setup

# Rank universe (no trading)
make scan

# Paper trading with Telegram alerts
make paper

# Web dashboard on :8787
make dashboard

# Run tests
make test

# Backtest
make backtest
```

Strategy parameters live in `src/momentum/config.py` (the dashboard can rewrite them).
Secrets come from the shell environment: `BINANCE_API_KEY`, `BINANCE_API_SECRET`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_OWNER_ID`, `DASHBOARD_PASS`.

## ■ Strategy Parameters

<div align="center">

| Parameter | Value |
|-----------|-------|
| Universe | dynamic (all liquid USDT-spot, ≥$10M 24h vol) |
| Lookback | 8 days |
| Hold period | 9 days |
| Top N | 2 |
| Stop loss | ~-1% floor |
| Trailing stop | ~7% from HWM |
| Acceleration weight | 0.07 |
| Volume-surge weight | 0.30 |
| Fees | 0.075% (BNB) |

</div>

## ■ License

MIT © [pluttan](https://github.com/pluttan)
