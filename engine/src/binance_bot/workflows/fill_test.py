from __future__ import annotations

import logging

from binance_bot.binance_desktop import BinanceNavigator

logger = logging.getLogger(__name__)


class FillTestWorkflow:
    """Uji kalibrasi: buka top gainer #rank lalu isi kolom Jumlah. Tanpa saringan SOP.

    Dipakai untuk memastikan posisi kolom dan tanda desimal benar di laptop ini. Tombol order
    tidak ditekan; kolom dibiarkan terisi agar bisa dilihat, kosongkan sendiri bila perlu.
    """

    name = "uji-isi"

    def __init__(self, navigator: BinanceNavigator, *, rank: int, quantity_text: str) -> None:
        self._nav = navigator
        self._rank = rank
        self._text = quantity_text

    def run(self) -> None:
        self._nav.prepare()
        self._nav.open_top_gainers()
        symbol = self._nav.open_gainer(self._rank)
        self._nav.fill_quantity(self._text)
        logger.info(
            "BERHASIL: kolom Jumlah %s berisi %s dan terbaca di layar. Tombol order tidak ditekan.",
            symbol,
            self._text,
        )
