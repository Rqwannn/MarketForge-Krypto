from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from binance_bot.analysis import PatternAnalyzer, PatternReading
from binance_bot.exceptions import BotError
from binance_bot.logging_setup import event
from binance_bot.market import is_futures_symbol
from binance_bot.strategy.execution import live_orders_enabled
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.sop import ReadingSource, SopTrader, log_top_gainers

logger = logging.getLogger(__name__)

_MAX_FAILED_ROUNDS = 5  # putaran gagal berturut-turut (tanpa posisi sungguhan) sebelum bot berhenti


class SingleWorkflow:
    """Mode single: satu laptop menjalankan SOP V2 penuh dan memanggil AI sendiri.

    Langkah 1 SOP: pantau top 5, masuk hanya koin yang pola garis kuningnya OK (jumlah posisi
    tidak dibatasi). Bila kelimanya belum OK, tidak masuk. Dengan `interval_s`,
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
        failed_rounds = 0
        while True:
            logger.info("Putaran pemantauan dimulai", extra=event("cycle", phase="start"))
            failure: BotError | None = None
            try:
                opened = self.run_cycle()
                failed_rounds = 0
            except BotError as exc:
                # Satu putaran yang gagal (mis. daftar Futures di layar belum siap) tidak boleh
                # mematikan bot: posisi uang sungguhan yang terbuka tetap harus diawasi sampai
                # terjual, dan putaran berikutnya mencoba lagi.
                failure, opened = exc, 0
                failed_rounds += 1
                logger.error("Putaran gagal: %s", exc)
            logger.info(
                "Putaran selesai",
                extra=event("cycle", phase="done", opened=opened, next_in_s=self._interval_s),
            )
            if self._interval_s <= 0:
                self._watch_real_positions()
                if failure is not None:
                    raise failure  # mode Sekali: kegagalan tetap dilaporkan, setelah posisi aman
                return
            if failed_rounds >= _MAX_FAILED_ROUNDS and not self._trader.real_positions_open():
                raise BotError(
                    f"{failed_rounds} putaran berturut-turut gagal, bot berhenti. "
                    f"Terakhir: {failure}"
                )
            logger.info("Pantau ulang dalam %.0f menit", self._interval_s / 60)
            self._wait_and_watch(self._interval_s)

    def _refresh_safely(self) -> None:
        """Jual otomatis; satu pengecekan yang gagal dicoba lagi menit depan, bot tetap jalan."""
        try:
            self._trader.refresh_journal()
        except BotError as exc:
            logger.error("Pengecekan jual otomatis gagal, dicoba lagi: %s", exc)

    def _watch_real_positions(self) -> None:
        """Mode Sekali dengan uang sungguhan: tetap menyala sampai semua posisi sungguhan terjual.

        Posisi sungguhan tidak boleh ditinggal tanpa pengawas, jadi bot baru berhenti setelah
        tidak ada posisi sungguhan yang terbuka. Uji kertas tetap selesai setelah satu putaran.
        """
        step = self._trader.watch_interval_s
        while (open_count := self._trader.real_positions_open()) > 0:
            logger.info("Mengawasi %d posisi uang sungguhan sampai terjual", open_count)
            self._sleep(step)
            self._refresh_safely()
        # (posisi uji kertas dinilai lagi di awal putaran berikutnya)

    def _wait_and_watch(self, seconds: float) -> None:
        """Tunggu putaran berikutnya sambil menjalankan jual otomatis posisi yang terbuka."""
        step = self._trader.watch_interval_s
        left = seconds
        while left > 0:
            wait = min(step, left)
            self._sleep(wait)
            left -= wait
            if left > 0:  # putaran berikutnya memeriksanya sendiri di awal
                self._refresh_safely()

    def run_cycle(self) -> int:
        """Satu putaran pemantauan. Mengembalikan jumlah posisi uji baru."""
        self._trader.refresh_journal()  # jual otomatis posisi yang sudah mencapai target
        self._nav.prepare()
        rows = {row.rank: row for row in self._nav.open_top_gainers()}
        log_top_gainers(list(rows.values()))
        analyzer = self._analyzer
        source: ReadingSource | None = None
        if analyzer is not None:

            def read_chart(symbol: str, chart: Path) -> PatternReading:
                # Selama AI membaca, aplikasi MarketForge tampil supaya prosesnya terlihat; bursa
                # dibawa ke depan lagi sebelum langkah berikutnya (isi jumlah, klik).
                self._nav.show_app(
                    f"AI membaca grafik {symbol}", symbol=symbol, chart=str(chart), stage="ai"
                )
                return analyzer.analyze(chart)

            source = read_chart

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
                # Tetap tampil sebagai baris di aplikasi (bukan hanya log) dengan alasannya.
                logger.warning(
                    "Rank #%d dilewati: %s",
                    rank,
                    exc,
                    extra=event(
                        "coin",
                        rank=rank,
                        symbol=row.symbol if row is not None else f"Top {rank}",
                        status="skipped",
                        verdict=None,
                        reason=str(exc),
                    ),
                )
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
            logger.info(
                "Selesai: %d posisi %s baru",
                opened,
                "uang sungguhan" if live_orders_enabled() else "uji kertas",
            )
        return opened
