# momentum-bot

Binance spot momentum trading bot. Каждый месяц покупает 3 актива с лучшим
14-day return, держит 60 дней или закрывает по −3% стопу.

> **Backtest 4y (2022-2026)**: +60-90% annualized USD без leverage.
> Realistic после haircuts: +30-50% annualized.

## Strategy spec

- **universe**: ~18 USDT spot pairs с ≥4y history (refresh quarterly)
- **lookback**: 14 days
- **hold**: 60 days max
- **top N**: 3 (equal-weight)
- **stop loss**: −3% per position (closed early на trigger)
- **rebalance**: monthly (на open следующего месяца)
- **fees**: 0.075% (BNB discount on)

## Modes

- `SCAN_ONLY` — показать ranking, не торговать
- `PAPER` — виртуальная торговля
- `LIVE` — реальные orders на binance

## Config

`.env` (gitignored):

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_OWNER_ID=...
TOTAL_CAPITAL=1000
MODE=PAPER
```

## Quick start

```bash
make setup        # uv venv + install
make test         # pytest
make scan         # rank universe и показать picks
make paper        # PAPER trading с telegram
```

## Status

в разработке. см. STRATEGY_FINDINGS.md в `/home/pluttan/pr/pets/grid-bot/` для research basis.

## Risk

momentum strategy variance высокая:
- 70% месяцев в плюсе
- средний месяц +5-13% (median/mean)
- bad months: −30 до −40% реально
- max DD до −37%
- 3-4 месяца подряд в минус возможны (особенно crypto winter)

**не для нервных. для долгосрочной игры с pre-committed capital.**
