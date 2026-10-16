"""Data pasar Tebbit dari layar (tanpa API): harga, spread, dan perubahan 24 jam.

Tebbit tidak punya sumber candle atau funding yang kita pakai, jadi `klines` dan `funding_history`
melempar NoHistoryError (SOP menanganinya sebagai "tanpa pembanding"; hanya AI yang menilai pola).
Funding tidak tampil di halaman: dianggap 0, sehingga saringan funding tidak menolak koin.

Harga koin lain (mis. posisi uji yang masih terbuka) hanya dibaca bila `browse` aktif: bot
membuka halaman koin itu sebentar lalu kembali. Saat aplikasi sekadar menampilkan daftar posisi,
`browse` mati agar Chrome tidak dibuka. Harga yang dibaca dengan cara itu dipakai ulang selama
`_BROWSE_TTL_S`, agar halaman koin lain tidak dibuka berulang kali dalam satu putaran.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from binance_bot.exceptions import BotError, MarketDataError, NoHistoryError
from binance_bot.market.binance_futures import Candle, Quote, SymbolRules
from binance_bot.tebbit_web.navigator import TebbitNavigator

# Perkiraan hati-hati bila aturan pair tidak terbaca: langkah 0,01 USDT, minimum 5 USDT.
_RULES = SymbolRules(step=0.01, min_qty=0.01, min_notional=5.0)
_BROWSE_TTL_S = 120.0


class ScreenMarket:
    def __init__(
        self,
        navigator: TebbitNavigator,
        *,
        browse: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._nav = navigator
        self._browse = browse
        self._clock = clock
        self._browsed: dict[str, tuple[float, Quote]] = {}

    def rules(self, symbol: str) -> SymbolRules:
        return _RULES

    def quote(self, symbol: str) -> Quote:
        try:
            opened: str | None = self._nav.read_symbol()
        except BotError:
            opened = None  # jendela belum dibuka atau bukan halaman koin
        if opened == symbol:
            return self._read()
        if not self._browse:
            raise MarketDataError(f"{symbol} tidak sedang terbuka di Tebbit, harga tidak terbaca")
        cached = self._browsed.get(symbol)
        if cached is not None and self._clock() - cached[0] < _BROWSE_TTL_S:
            return cached[1]
        if opened is None:
            self._nav.prepare()
        self._nav.open_symbol(symbol)
        try:
            quote = self._read()
            self._browsed[symbol] = (self._clock(), quote)
            return quote
        finally:
            if opened is not None:
                self._nav.open_symbol(opened)  # kembali ke koin yang sedang dinilai

    def _read(self) -> Quote:
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
        raise NoHistoryError("Tebbit tidak punya sumber candle")

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        raise NoHistoryError("Tebbit tidak punya sumber funding")
