"""Data pasar publik Binance USDⓈ-M Futures.

Endpoint publik: tanpa API key, tanpa akun, tanpa langganan. Dipakai untuk angka yang tidak
tampil lengkap di layar (aturan jumlah per koin, funding, spread) dan untuk menilai hasil
uji kertas dari candle sungguhan.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from binance_bot.exceptions import MarketDataError

BASE_URL = "https://fapi.binance.com/fapi/v1"
_SYMBOL = re.compile(r"^[A-Z0-9]{1,20}USD[TC]$")  # nama koin bisa satu huruf, mis. "SUSDT"

GetJson = Callable[[str], Any]


def _get_json(url: str) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise MarketDataError(f"Binance menjawab HTTP {exc.code} untuk {url}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise MarketDataError(f"Data pasar Binance tidak bisa diambil: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: int  # milidetik
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int

    @property
    def is_green(self) -> bool:
        return self.close >= self.open


@dataclass(frozen=True, slots=True)
class SymbolRules:
    step: float  # kelipatan jumlah koin
    min_qty: float
    min_notional: float  # nilai order minimum dalam USDT


@dataclass(frozen=True, slots=True)
class Quote:
    bid: float
    ask: float
    funding_rate: float  # per periode funding, pecahan (0.0001 = 0,01%)
    change_pct: float  # perubahan 24 jam dalam persen

    @property
    def spread_pct(self) -> float:
        mid = (self.bid + self.ask) / 2
        return 100 * (self.ask - self.bid) / mid if mid else float("inf")


class FuturesMarket:
    def __init__(self, *, base_url: str = BASE_URL, get_json: GetJson = _get_json) -> None:
        self._base = base_url
        self._get = get_json
        self._rules: dict[str, SymbolRules] | None = None

    def rules(self, symbol: str) -> SymbolRules:
        if self._rules is None:
            self._rules = {
                item["symbol"]: _rules_from(item["filters"])
                for item in self._get(f"{self._base}/exchangeInfo")["symbols"]
                if item.get("contractType") == "PERPETUAL" and item.get("status") == "TRADING"
            }
        try:
            return self._rules[_checked(symbol)]
        except KeyError as exc:
            raise MarketDataError(f"{symbol} tidak punya kontrak perpetual yang aktif") from exc

    def quote(self, symbol: str) -> Quote:
        query = self._query(symbol=_checked(symbol))
        book = self._get(f"{self._base}/ticker/bookTicker?{query}")
        premium = self._get(f"{self._base}/premiumIndex?{query}")
        ticker = self._get(f"{self._base}/ticker/24hr?{query}")
        return Quote(
            bid=float(book["bidPrice"]),
            ask=float(book["askPrice"]),
            funding_rate=float(premium["lastFundingRate"]),
            change_pct=float(ticker["priceChangePercent"]),
        )

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int = 100,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Candle]:
        query = self._query(
            symbol=_checked(symbol),
            interval=interval,
            limit=limit,
            startTime=start_ms,
            endTime=end_ms,
        )
        return [
            Candle(
                int(k[0]),
                float(k[1]),
                float(k[2]),
                float(k[3]),
                float(k[4]),
                float(k[5]),
                int(k[6]),
            )
            for k in self._get(f"{self._base}/klines?{query}")
        ]

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        """Funding yang benar-benar dibayarkan di antara dua waktu: (waktu ms, rate)."""
        query = self._query(symbol=_checked(symbol), startTime=start_ms, endTime=end_ms, limit=100)
        return [
            (int(item["fundingTime"]), float(item["fundingRate"]))
            for item in self._get(f"{self._base}/fundingRate?{query}")
        ]

    @staticmethod
    def _query(**params: object) -> str:
        return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def is_futures_symbol(symbol: str) -> bool:
    """Pair Futures yang wajar, mis. "STRKUSDT". Simbol dari OCR/hub wajib lolos cek ini."""
    return bool(_SYMBOL.fullmatch(symbol))


def _checked(symbol: str) -> str:
    if not is_futures_symbol(symbol):
        raise MarketDataError(f"Simbol tidak valid: {symbol!r}")
    return symbol


def _rules_from(filters: list[dict[str, Any]]) -> SymbolRules:
    by_type = {f["filterType"]: f for f in filters}
    lot = by_type["LOT_SIZE"]
    return SymbolRules(
        step=float(lot["stepSize"]),
        min_qty=float(lot["minQty"]),
        min_notional=float(by_type.get("MIN_NOTIONAL", {}).get("notional", 0)),
    )
