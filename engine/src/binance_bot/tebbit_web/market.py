"""Data pasar Tebbit dari layar (tanpa API): harga, spread, dan perubahan 24 jam.

Tebbit tidak punya sumber candle atau funding yang kita pakai, jadi `klines` dan `funding_history`
melempar MarketDataError (SOP menanganinya sebagai "tanpa pembanding"; hanya AI yang menilai pola).
Funding tidak tampil di halaman: dianggap 0, sehingga saringan funding tidak menolak koin.
"""

from __future__ import annotations

from binance_bot.exceptions import BotError, MarketDataError
from binance_bot.market.binance_futures import Candle, Quote, SymbolRules
from binance_bot.tebbit_web.navigator import TebbitNavigator

# Perkiraan hati-hati bila aturan pair tidak terbaca: langkah 0,01 USDT, minimum 5 USDT.
_RULES = SymbolRules(step=0.01, min_qty=0.01, min_notional=5.0)


class ScreenMarket:
    def __init__(self, navigator: TebbitNavigator) -> None:
        self._nav = navigator

    def rules(self, symbol: str) -> SymbolRules:
        return _RULES

    def quote(self, symbol: str) -> Quote:
        """Hanya untuk koin yang halamannya sedang terbuka di Chrome."""
        try:
            opened = self._nav.read_symbol()
        except BotError:
            opened = None  # jendela belum dibuka atau bukan halaman koin
        if opened != symbol:
            raise MarketDataError(f"{symbol} tidak sedang terbuka di Tebbit, harga tidak terbaca")
        bid, ask, _price, change = self._nav.read_quote()
        return Quote(bid=bid, ask=ask, funding_rate=0.0, change_pct=change)

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int = 100,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Candle]:
        raise MarketDataError("Tebbit tidak punya sumber candle")

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        raise MarketDataError("Tebbit tidak punya sumber funding")
