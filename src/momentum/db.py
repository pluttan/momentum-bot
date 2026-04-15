"""SQLite state persistence для momentum bot."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import structlog

from . import config

log = structlog.get_logger()


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_price REAL NOT NULL,
    units REAL NOT NULL,
    capital_at_entry REAL NOT NULL,
    entry_ts INTEGER NOT NULL,
    closed_ts INTEGER,
    exit_price REAL,
    pnl_usdt REAL,
    pnl_pct REAL,
    close_reason TEXT,
    UNIQUE (symbol, entry_ts)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    units REAL NOT NULL,
    price REAL NOT NULL,
    fee_usdt REAL NOT NULL,
    ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS equity (
    ts INTEGER PRIMARY KEY,
    capital REAL NOT NULL,
    positions_value REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pos_open ON positions(closed_ts) WHERE closed_ts IS NULL;
"""


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


# ===== positions =====

def add_position(symbol: str, entry_price: float, units: float,
                 capital_at_entry: float, entry_ts: int) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO positions (symbol, entry_price, units, capital_at_entry, entry_ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (symbol, entry_price, units, capital_at_entry, entry_ts),
        )
        return cur.lastrowid


def close_position(pos_id: int, exit_price: float, close_reason: str):
    with conn() as c:
        row = c.execute(
            "SELECT entry_price, units FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()
        if not row:
            return
        pnl_usdt = row["units"] * (exit_price - row["entry_price"])
        pnl_pct = (exit_price / row["entry_price"] - 1) * 100
        c.execute(
            "UPDATE positions SET closed_ts=?, exit_price=?, pnl_usdt=?, pnl_pct=?, close_reason=? "
            "WHERE id=?",
            (int(time.time()), exit_price, pnl_usdt, pnl_pct, close_reason, pos_id),
        )
        log.info("position closed", id=pos_id, reason=close_reason, pnl_pct=pnl_pct)


def get_open_positions() -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM positions WHERE closed_ts IS NULL ORDER BY entry_ts"
        ).fetchall()
        return [dict(r) for r in rows]


def get_closed_positions(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM positions WHERE closed_ts IS NOT NULL "
            "ORDER BY closed_ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_realized_pnl() -> float:
    with conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(pnl_usdt), 0) AS pnl FROM positions WHERE closed_ts IS NOT NULL"
        ).fetchone()
        return float(row["pnl"])


# ===== trades =====

def log_trade(symbol: str, side: str, units: float, price: float, fee_usdt: float, ts: int):
    with conn() as c:
        c.execute(
            "INSERT INTO trades (symbol, side, units, price, fee_usdt, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (symbol, side, units, price, fee_usdt, ts),
        )


def get_trade_count() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]


def get_total_fees() -> float:
    with conn() as c:
        row = c.execute("SELECT COALESCE(SUM(fee_usdt), 0) AS f FROM trades").fetchone()
        return float(row["f"])


# ===== equity tracking =====

def log_equity(capital: float, positions_value: float):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO equity (ts, capital, positions_value) VALUES (?, ?, ?)",
            (int(time.time()), capital, positions_value),
        )


def get_equity_curve(limit: int = 100) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM equity ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_max_drawdown_pct() -> float:
    with conn() as c:
        rows = c.execute(
            "SELECT capital + positions_value AS eq FROM equity ORDER BY ts"
        ).fetchall()
        if not rows:
            return 0.0
        peak = 0.0
        max_dd = 0.0
        for r in rows:
            eq = float(r["eq"])
            peak = max(peak, eq)
            if peak > 0:
                dd = (eq - peak) / peak
                max_dd = min(max_dd, dd)
        return max_dd * 100


# ===== state KV =====

def get_state(key: str, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]


def set_state(key: str, value):
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )


def get_last_rebalance_ts() -> int | None:
    return get_state("last_rebalance_ts")


def set_last_rebalance_ts(ts: int):
    set_state("last_rebalance_ts", ts)
