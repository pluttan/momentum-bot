"""Telegram bot — control + alerts. Long polling."""
from __future__ import annotations

import requests
import structlog

from . import config, db

log = structlog.get_logger()

API = "https://api.telegram.org/bot{token}/{method}"
_offset = 0


def _post(method: str, **kwargs) -> dict | None:
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    try:
        r = requests.post(API.format(token=config.TELEGRAM_BOT_TOKEN, method=method),
                          json=kwargs, timeout=30)
        return r.json()
    except Exception as e:
        log.warning("telegram post failed", method=method, error=str(e))
        return None


def send(text: str, chat_id: str | int | None = None):
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not chat_id:
        return
    _post("sendMessage", chat_id=chat_id, text=text, parse_mode="Markdown",
          disable_web_page_preview=True)


def alert(text: str):
    send(f"⚠ {text}")


def info(text: str):
    send(f"ℹ {text}")


def fmt_status() -> str:
    open_pos = db.get_open_positions()
    realized = db.get_realized_pnl()
    fees = db.get_total_fees()
    n_trades = db.get_trade_count()
    dd = db.get_max_drawdown_pct()
    eq_curve = db.get_equity_curve(1)
    cur_eq = eq_curve[-1] if eq_curve else None
    lines = [
        f"*momentum-bot status* ({config.MODE})",
        f"open positions: {len(open_pos)}",
        f"realized PnL: ${realized:+.2f}",
        f"total fees: ${fees:.2f}",
        f"trades: {n_trades}",
        f"max DD: {dd:.2f}%",
    ]
    if cur_eq:
        eq_total = cur_eq["capital"] + cur_eq["positions_value"]
        lines.append(f"equity: ${eq_total:.2f} (USDT ${cur_eq['capital']:.2f} + pos ${cur_eq['positions_value']:.2f})")
    return "\n".join(lines)


def fmt_positions() -> str:
    rows = db.get_open_positions()
    if not rows:
        return "no open positions"
    lines = ["*open positions*"]
    for r in rows:
        lines.append(f"`{r['symbol']}` units={r['units']:.4f} entry=${r['entry_price']:.4f} cap=${r['capital_at_entry']:.2f}")
    return "\n".join(lines)


def fmt_history(n: int = 20) -> str:
    rows = db.get_closed_positions(limit=n)
    if not rows:
        return "no closed positions"
    lines = [f"*last {len(rows)} closed*"]
    for r in rows:
        emoji = "✓" if r["pnl_pct"] > 0 else "✗"
        lines.append(f"{emoji} `{r['symbol']}` {r['pnl_pct']:+.2f}% (${r['pnl_usdt']:+.2f}) [{r['close_reason']}]")
    return "\n".join(lines)


def fmt_pnl() -> str:
    realized = db.get_realized_pnl()
    fees = db.get_total_fees()
    return f"*realized PnL*: ${realized:+.2f}\n*total fees*: ${fees:.2f}\n*net*: ${realized-fees:+.2f}"


def is_owner(user_id: int) -> bool:
    return str(user_id) == str(config.TELEGRAM_OWNER_ID)


def handle_command(text: str, user_id: int) -> str | None:
    """Process command. Returns reply text or None if not a command."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    if not is_owner(user_id):
        return "не для тебя :3"

    cmd = text.split()[0].lower()
    if cmd == "/status":
        return fmt_status()
    if cmd == "/positions":
        return fmt_positions()
    if cmd == "/pnl":
        return fmt_pnl()
    if cmd == "/history":
        return fmt_history()
    if cmd == "/pause":
        db.set_state("paused", True)
        return "paused — не будет открывать new positions"
    if cmd == "/resume":
        db.set_state("paused", False)
        return "resumed"
    if cmd == "/stop":
        db.set_state("emergency_stop", True)
        return "emergency_stop set — bot прекратит работу при next iteration"
    if cmd == "/help":
        return "/status /positions /pnl /history /pause /resume /stop"
    return f"unknown command: {cmd}"


def poll_commands(timeout: int = 25):
    """Long-poll updates. Process commands."""
    global _offset
    if not config.TELEGRAM_BOT_TOKEN:
        return
    try:
        r = requests.get(
            API.format(token=config.TELEGRAM_BOT_TOKEN, method="getUpdates"),
            params={"offset": _offset, "timeout": timeout},
            timeout=timeout + 5,
        )
        data = r.json()
        for upd in data.get("result", []):
            _offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg or "text" not in msg:
                continue
            user_id = msg["from"]["id"]
            chat_id = msg["chat"]["id"]
            reply = handle_command(msg["text"], user_id)
            if reply:
                send(reply, chat_id=chat_id)
    except requests.Timeout:
        pass
    except Exception as e:
        log.warning("poll error", error=str(e))


def is_paused() -> bool:
    return bool(db.get_state("paused", False))


def is_emergency() -> bool:
    return bool(db.get_state("emergency_stop", False))
