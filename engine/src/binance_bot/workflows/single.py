from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from binance_bot.analysis import PatternAnalyzer
from binance_bot.exceptions import BotError
from binance_bot.logging_setup import event
from binance_bot.market import is_futures_symbol
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.sop import SopTrader, log_top_gainers

logger = logging.getLogger(__name__)


class SingleWorkflow:
    """Mode single: satu laptop menjalankan SOP V2 penuh dan memanggil AI sendiri.

    Langkah 1 SOP: pantau top 5, masuk hanya koin yang pola garis kuningnya OK, sampai slot
    (maksimal 2 posisi) penuh. Bila kelimanya belum OK, tidak masuk. Dengan `interval_s`,
    pemantauan diulang terus sampai dihentikan (Ctrl+C).
    """

    name = "single"

    def __init__(
        self,
        navigator: TradingNavigator,
        trader: SopTrader,
        analyzer: PatternAnalyzer | None,
        *,
        ranks: Sequence[int],
        interval_s: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._nav = navigator
        self._trader = trader
        self._analyzer = analyzer
        self._ranks = list(ranks)
        self._interval_s = interval_s
        self._sleep = sleep

    def run(self) -> None:
        while True:
            logger.info("Putaran pemantauan dimulai", extra=event("cycle", phase="start"))
            opened = self.run_cycle()
            logger.info(
                "Putaran selesai",
                extra=event("cycle", phase="done", opened=opened, next_in_s=self._interval_s),
            )
            if self._interval_s <= 0:
                return
            logger.info("Pantau ulang dalam %.0f menit", self._interval_s / 60)
            self._sleep(self._interval_s)

    def run_cycle(self) -> int:
        """Satu putaran pemantauan. Mengembalikan jumlah posisi uji baru."""
        if self._trader.halted(self._trader.refresh_journal()):
            return 0
        self._nav.prepare()
        rows = {row.rank: row for row in self._nav.open_top_gainers()}
        log_top_gainers(list(rows.values()))
        analyzer = self._analyzer
        source = (lambda _symbol, chart: analyzer.analyze(chart)) if analyzer else None
        min_gain = self._trader.params.min_gain_pct

        opened = 0
        on_list = True
        seen: set[str] = set()
        for rank in self._ranks:
            row = rows.get(rank)
            if row is not None and row.change_pct < min_gain:
                logger.info(
                    "#%d %s dilewati: naik %.1f%% < %g%%",
                    rank,
                    row.symbol,
                    row.change_pct,
                    min_gain,
                )
                continue
            try:
                # Buka lewat namanya: peringkat sering bertukar di tengah putaran, sehingga klik
                # baris ke-N membuka pair lain (atau pair yang sama lagi) dan koin ke-N terlewat.
                if row is not None and is_futures_symbol(row.symbol):
                    symbol = self._nav.open_symbol(row.symbol)
                else:
                    if not on_list:
                        self._nav.open_top_gainers()
                    symbol = self._nav.open_gainer(rank)
                on_list = False
            except BotError as exc:
                logger.error("Rank #%d dilewati: %s", rank, exc)
                continue
            if symbol in seen:
                # Peringkat bergeser sehingga pair yang sama terbuka lagi: jangan nilai dua kali.
                logger.info("#%d sekarang %s: sudah dinilai di putaran ini, dilewati", rank, symbol)
                continue
            seen.add(symbol)
            if self._trader.trade(rank, symbol, source).status == "open":
                opened += 1
        if opened == 0:
            logger.info("Tidak ada koin dengan pola OK: tidak masuk, pantau ulang nanti")
        else:
            logger.info("Selesai: %d posisi uji kertas baru", opened)
        return opened
