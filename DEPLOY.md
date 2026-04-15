# DEPLOY — momentum-bot live deployment guide

3-stage rollout: PAPER week → micro-LIVE 2 weeks → scale.

## Pre-deploy checklist

- [ ] Binance spot account с активным USDT баланс
- [ ] API key created (Trading + Read, **NO withdrawal**)
- [ ] BNB ≥ $20 в аккаунте для fee discount (0.075% vs 0.1%)
- [ ] Telegram bot создан через @BotFather, токен получен
- [ ] `cp .env.example .env` + заполнить actual values
- [ ] `make test` зелёные (26 tests)
- [ ] `make scan` показывает разумный ranking universe
- [ ] system clock synced (NTP) — для stop-loss timestamps

## ⚠️ HONEST maxDD expectations

Research настоящий intra-period drawdown (daily equity tracking):

| variant | annual (4y bt) | REAL maxDD |
|---------|----------------|------------|
| classic top-3 (DEFAULT) | +158% | **−61.8%** |
| dual top-3 | +164% | −61.8% |
| timeseries max_n=13 | +177% | **−44.8%** (best) |

**НЕ −3% как казалось при rebalance-only tracking!**

`MAX_DRAWDOWN_PCT=0.30` default **срабатывает** на обычных bear moves.
Если deploy timeseries — raise `MAX_DRAWDOWN_PCT=0.60` чтобы не halt'нуть
в normal volatility.

## .env example

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_OWNER_ID=...

MODE=PAPER
TOTAL_CAPITAL=1000

# strategy (defaults match research)
LOOKBACK_DAYS=14
HOLD_DAYS=60
TOP_N=3
STOP_LOSS_PCT=-0.03

# risk
MAX_DRAWDOWN_PCT=0.30
MAX_DAILY_LOSS_USD=300
USE_BNB_DISCOUNT=true
```

## Stage 1: PAPER mode (неделя)

```bash
cd ~/pr/pets/momentum-bot
make paper   # MODE=PAPER make run
```

или systemd unit:

```ini
# ~/.config/systemd/user/momentum-bot.service
[Unit]
Description=momentum-bot PAPER
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pluttan/pr/pets/momentum-bot
EnvironmentFile=/home/pluttan/pr/pets/momentum-bot/.env
ExecStart=/home/pluttan/pr/pets/momentum-bot/.venv/bin/python -m momentum.main
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

Pass criteria после 1 недели:
- Telegram alerts работают (rebalance, stops, status)
- Хотя бы 1 rebalance прошёл (если внутри месяца попал)
- Stop-loss срабатывал на хотя бы 1 position (в bear/sideways период)
- Никаких unhandled exceptions (`journalctl --user -u momentum-bot.service | grep ERROR`)
- Equity tracking логируется

## Stage 2: micro-LIVE ($100-200, 2 недели)

```
# .env:
MODE=LIVE
TOTAL_CAPITAL=200
```

Watch:
- Realized PnL matches paper sim within 30%
- Slippage не превышает 0.5% per trade на тонких альтах
- Никаких stuck positions (одна нога открыта, другая нет)
- Daily loss cap не trigger ложно

Pass criteria после 2 недель:
- Net PnL > 0 OR breakeven (один rebalance может дать +5/-5%)
- Все positions properly closed
- Fee ratio < 30% от gross gains

## Stage 3: scale up ($500-5000)

После micro-LIVE success:
1. Update `TOTAL_CAPITAL=5000` в `.env`
2. `systemctl --user restart momentum-bot.service`
3. Daily check `/status` через telegram
4. Weekly review:
   - cumulative PnL
   - winrate (target ~40-50%)
   - max DD (cap 30%)
   - fee ratio

## Monitoring

- **Telegram**: `/status` daily, `/positions` after rebalance, `/pnl` weekly, `/history` monthly
- **journalctl**: `journalctl --user -u momentum-bot.service -f`
- **DB**: `sqlite3 momentum.db "SELECT * FROM equity ORDER BY ts DESC LIMIT 10"`

## Emergency procedures

- **Pause new opens**: `/pause` в Telegram (existing positions держатся, новые нет)
- **Resume**: `/resume`
- **Hard emergency stop**: `/stop` — флаг в DB, bot exit'нет на next iteration
- **Force kill**: `systemctl --user stop momentum-bot.service`
- **Manual position close**: через binance UI — bot обнаружит нулевой balance на next check

## Red flags — investigate

- Drawdown > 20% (close to 30% cap) → проверь если bear regime → consider pause
- Fees > 30% gross profit → возможно stops срабатывают слишком часто, проверь STOP_LOSS_PCT
- 3+ месяца подряд negative → strategy may be in adverse regime, consider pause
- Telegram heartbeat tihо > 24h → bot стопнул, проверь journal

## Что НЕ делать

- ❌ Деплоить в активный bear (BTC down >20% за месяц) — strategy underperforms
- ❌ Менять STOP_LOSS_PCT > -0.05 — широкий стоп ломает risk profile
- ❌ TOP_N > 5 — больше positions = bigger fee drag без proportional return
- ❌ Без BNB discount — съест 25% extra fees
- ❌ Без MIN_POSITIVE_RETURN filter — будет покупать "лучших из плохих"
- ❌ Использовать withdrawal API key — security risk

## Realistic expectations

Backtest (4y, 2022-2026):
- median annual: +60-90% USD (broader universe haircut)
- maxDD median: ~−30% (worst 10% scenario −60%)
- monthly: 70% positive, σ 32%
- bad year (2022 winter): ~−10 до −20%
- good year (2024): +500-900%

Live будет hairier на ~20-40pp due to slippage, basis effects, missing trades.
**Net realistic: +30-50% annualized USD long-term**.

## Risk acknowledgment

Я понимаю что:
- 30% месяцев в минусе normal
- 3-4 месяца подряд negative возможны (особенно crypto winter)
- Bot может потерять до −30% капитала до emergency halt
- В случае catastrophic exchange event могу потерять весь baans на binance

Подпись: ___________  Дата: __________
