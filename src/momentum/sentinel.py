"""Negative-news sentinel: DeepSeek watches held positions for critical news.

Cross-market OOS finding (MOEX + Binance, 2026): LLM news-reading is only
reliable as a NEGATIVE filter — hack/lawsuit/delisting/unlock kills a coin
on every market (-18% vs BTC over 40d, hit rate 17%). Positive news adds
nothing (sell-the-news). So the sentinel has veto/exit power only, never buys.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request

import structlog

from . import config, db

log = structlog.get_logger()

TAG_RE = re.compile(r"<[^>]+>")
MSG_RE = re.compile(
    r'tgme_widget_message_text[^>]*>(.*?)</div>.*?<time datetime="([^"]+)"', re.S)

SYSTEM_PROMPT = """Ты — риск-монитор крипто-портфеля. По приложенным новостным постам определи,
есть ли КРИТИЧЕСКИЙ НЕГАТИВ по каждой из монет: взлом/эксплойт протокола, иск/уголовное дело
против команды, делистинг со спотового рынка крупной биржи, крупный разлок токенов (>3% supply),
депег, банкротство/остановка выводов связанной платформы. Общий падающий рынок, волатильность,
чужие монеты — НЕ критический негатив. Отвечай СТРОГО JSON-массивом:
[{"symbol": "...", "critical": true/false, "reason": "кратко или null"}] по всем монетам из запроса."""


def _http(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    if config.SENTINEL_PROXY:
        import subprocess
        r = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "--proxy", config.SENTINEL_PROXY,
             "-A", "Mozilla/5.0", url], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_recent_posts(channels: list[str]) -> list[str]:
    """Last page of each t.me/s/ channel (~20 posts, covers recent hours)."""
    posts = []
    for ch in channels:
        try:
            page = _http(f"https://t.me/s/{ch}")
        except Exception as e:
            log.warning("sentinel channel fetch failed", channel=ch, error=str(e))
            continue
        for m in MSG_RE.finditer(page):
            text = html.unescape(TAG_RE.sub("", m.group(1))).strip()
            if text:
                posts.append(f"[{ch}] {text[:400]}")
    return posts


def _match_posts(posts: list[str], bases: list[str]) -> list[str]:
    out = []
    for p in posts:
        up = p.upper()
        if any(re.search(r"(?<![A-Z0-9])" + re.escape(b) + r"(?![A-Z0-9])", up) for b in bases):
            out.append(p)
    return out[:20]


def ask_deepseek(bases: list[str], posts: list[str]) -> list[dict]:
    body = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                f"Монеты в портфеле: {', '.join(bases)}\n\nПосты:\n" + "\n---\n".join(posts)},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    content = d["choices"][0]["message"]["content"]
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        log.warning("sentinel: unparseable llm reply", reply=content[:200])
        return []
    return json.loads(m.group(0))


def run_sentinel(trader) -> list[dict]:
    """Check held positions against recent news. Returns list of critical verdicts."""
    open_pos = db.get_open_positions()
    if not open_pos or not config.DEEPSEEK_API_KEY:
        return []
    bases = sorted({row["symbol"].split("/")[0] for row in open_pos})
    posts = fetch_recent_posts(config.SENTINEL_CHANNELS)
    relevant = _match_posts(posts, bases)
    if not relevant:
        log.info("sentinel: no relevant posts", coins=bases)
        return []
    try:
        verdicts = ask_deepseek(bases, relevant)
    except Exception as e:
        log.error("sentinel llm error", error=str(e))
        return []
    critical = [v for v in verdicts if v.get("critical")]
    if not critical:
        return []

    from . import telegram_bot
    for v in critical:
        sym = v["symbol"].upper().replace("USDT", "").strip("/")
        rows = [r for r in open_pos if r["symbol"].split("/")[0] == sym]
        msg = f"🦊 SENTINEL: критический негатив по {sym}: {v.get('reason')}"
        if config.SENTINEL_ACTION == "sell" and rows:
            for row in rows:
                try:
                    order = trader.market_sell(row["symbol"], row["units"])
                    db.log_trade(order["symbol"], order["side"], order["filled_units"],
                                 order["filled_price"], order["fee_usdt"], order["ts"])
                    db.close_position(row["id"], order["filled_price"], "sentinel")
                    msg += f"\nпозиция {row['symbol']} закрыта по {order['filled_price']}"
                except Exception as e:
                    msg += f"\nЗАКРЫТЬ {row['symbol']} НЕ ВЫШЛО: {e}"
                    log.error("sentinel sell failed", symbol=row["symbol"], error=str(e))
        else:
            msg += "\n(SENTINEL_ACTION=alert — закрой руками, если согласен)"
        telegram_bot.send(msg)
        log.warning("sentinel critical", **v)
    return critical
