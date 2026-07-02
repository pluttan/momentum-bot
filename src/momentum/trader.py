"""Binance spot trader wrapper. Supports PAPER and LIVE modes."""
from __future__ import annotations

import time

import ccxt
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import config

log = structlog.get_logger()


class TraderError(Exception):
    pass


class Trader:
    """ccxt-based binance spot trader. PAPER mode skips real orders."""

    def __init__(self):
        self.mode = config.MODE
        self.fee = config.effective_fee()
        if self.mode == "LIVE":
            if not config.BINANCE_API_KEY:
                raise TraderError("LIVE mode requires BINANCE_API_KEY")
            self.ex = ccxt.binance({
                "apiKey": config.BINANCE_API_KEY,
                "secret": config.BINANCE_API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
        else:
            # PAPER / SCAN_ONLY: используем public ccxt без auth для prices/markets
            self.ex = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
        self.ex.load_markets()
        # paper-mode virtual balance, reconstructed from DB so restarts don't
        # mint fresh capital on top of already-open positions (audit 2026-07:
        # equity doubled to $2000 after a service restart)
        self._paper_balance = {"USDT": config.TOTAL_CAPITAL}
        if self.mode != "LIVE":
            from . import db
            invested = 0.0
            for row in db.get_open_positions():
                invested += row["capital_at_entry"]
                base = row["symbol"].split("/")[0]
                self._paper_balance[base] = self._paper_balance.get(base, 0) + row["units"]
            realized = db.get_realized_pnl() - db.get_total_fees()
            self._paper_balance["USDT"] = max(0.0, config.TOTAL_CAPITAL + realized - invested)

    @retry(retry=retry_if_exception_type(ccxt.NetworkError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_ticker(self, symbol: str) -> dict:
        return self.ex.fetch_ticker(symbol)

    def get_price(self, symbol: str) -> float | None:
        try:
            t = self.fetch_ticker(symbol)
            return float(t["last"])
        except Exception as e:
            log.warning("fetch_ticker failed", symbol=symbol, error=str(e))
            return None

    @retry(retry=retry_if_exception_type(ccxt.NetworkError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 30) -> list:
        return self.ex.fetch_ohlcv(symbol, timeframe, limit=limit)

    def market_buy(self, symbol: str, usdt_amount: float) -> dict:
        """Market buy worth `usdt_amount` USDT. Returns order dict (real or simulated).

        Returns:
            {"symbol", "side", "filled_units", "filled_price", "fee_usdt", "ts"}
        """
        price = self.get_price(symbol)
        if price is None or price <= 0:
            raise TraderError(f"no price для {symbol}")
        units = self._round_amount(symbol, usdt_amount * (1 - self.fee) / price)
        if units <= 0:
            raise TraderError(f"computed units <= 0 для {symbol}")
        if self.mode == "LIVE":
            order = self.ex.create_market_buy_order(symbol, units)
            filled_price = float(order.get("average") or price)
            filled_units = float(order.get("filled") or units)
            fee_usdt = filled_units * filled_price * self.fee
            log.info("[LIVE BUY]", symbol=symbol, units=filled_units, price=filled_price)
        else:
            filled_price = price
            filled_units = units
            fee_usdt = usdt_amount * self.fee
            self._paper_balance["USDT"] -= usdt_amount
            self._paper_balance.setdefault(symbol.split("/")[0], 0)
            self._paper_balance[symbol.split("/")[0]] += filled_units
            log.info("[PAPER BUY]", symbol=symbol, units=filled_units, price=filled_price,
                     usdt=usdt_amount)
        return {
            "symbol": symbol, "side": "buy",
            "filled_units": filled_units, "filled_price": filled_price,
            "fee_usdt": fee_usdt, "ts": int(time.time()),
        }

    def market_sell(self, symbol: str, units: float) -> dict:
        """Market sell `units` of base asset. Returns order dict."""
        price = self.get_price(symbol)
        if price is None or price <= 0:
            raise TraderError(f"no price для {symbol}")
        units = self._round_amount(symbol, units)
        if units <= 0:
            raise TraderError(f"computed units <= 0 для {symbol}")
        if self.mode == "LIVE":
            order = self.ex.create_market_sell_order(symbol, units)
            filled_price = float(order.get("average") or price)
            filled_units = float(order.get("filled") or units)
            fee_usdt = filled_units * filled_price * self.fee
            log.info("[LIVE SELL]", symbol=symbol, units=filled_units, price=filled_price)
        else:
            filled_price = price
            filled_units = units
            usdt_received = units * price * (1 - self.fee)
            fee_usdt = units * price * self.fee
            base = symbol.split("/")[0]
            self._paper_balance[base] = max(0, self._paper_balance.get(base, 0) - units)
            self._paper_balance["USDT"] = self._paper_balance.get("USDT", 0) + usdt_received
            log.info("[PAPER SELL]", symbol=symbol, units=units, price=price,
                     usdt_received=usdt_received)
        return {
            "symbol": symbol, "side": "sell",
            "filled_units": filled_units, "filled_price": filled_price,
            "fee_usdt": fee_usdt, "ts": int(time.time()),
        }

    @retry(retry=retry_if_exception_type(ccxt.NetworkError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_balance(self):
        return self.ex.fetch_balance()

    def get_balance_usdt(self) -> float:
        if self.mode == "LIVE":
            try:
                bal = self._fetch_balance()
                return float(bal.get("USDT", {}).get("free", 0))
            except Exception as e:
                log.warning("fetch_balance failed", error=str(e))
                return 0.0
        return self._paper_balance.get("USDT", 0)

    def get_balance(self, asset: str) -> float:
        if self.mode == "LIVE":
            try:
                bal = self._fetch_balance()
                return float(bal.get(asset, {}).get("free", 0))
            except Exception as e:
                log.warning("fetch_balance failed", error=str(e))
                return 0.0
        return self._paper_balance.get(asset, 0)

    def _round_amount(self, symbol: str, amount: float) -> float:
        try:
            return float(self.ex.amount_to_precision(symbol, amount))
        except Exception:
            return round(amount, 8)

    def market_info(self, symbol: str) -> dict:
        return self.ex.markets.get(symbol, {})
