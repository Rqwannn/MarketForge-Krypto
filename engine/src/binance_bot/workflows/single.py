from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from binance_bot.analysis import PatternAnalyzer, PatternReading
from binance_bot.binance_desktop.screen_text import GainerRow
from binance_bot.exceptions import BotError, ScreenReadError
from binance_bot.logging_setup import event
from binance_bot.market import is_futures_symbol
from binance_bot.strategy.execution import live_orders_enabled
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.sop import ReadingSource, SopTrader, log_top_gainers

logger = logging.getLogger(__name__)

_MAX_FAILED_ROUNDS = 5  # putaran gagal berturut-turut (tanpa posisi sungguhan) sebelum bot berhenti

# Momentum (keputusan 21 Okt): koin yang terjual di target dicek ulang tiap candle 15 menit baru
# selama 2 jam. Grafik 15 menit hanya berubah tiap candle, jadi cek ulang di candle yang sama
# hanya mengulang bacaan AI yang sama.
_MOMENTUM_WINDOW_S = 2 * 3600.0
_CANDLE_S = 15 * 60.0
_CANDLE_SETTLE_S = 60.0  # candle sebelumnya sudah tutup dan tampil di grafik


def _candle(now: float) -> int:
    return int(now // _CANDLE_S)


class SingleWorkflow:
    """Mode single: satu laptop menjalankan SOP V2 penuh dan memanggil AI sendiri.

    Langkah 1 SOP: pantau top 5, masuk hanya koin yang pola garis kuningnya OK (jumlah posisi
    tidak dibatasi). Bila kelimanya belum OK, tidak masuk. Dengan `interval_s`,
    pemantauan diulang terus sampai dihentikan (Ctrl+C).

    Momentum: koin yang terjual di target dicek ulang lebih dulu, langsung setelah terjual lalu
    tiap candle 15 menit baru selama 2 jam, lewat pencarian bila sudah keluar Top 5 (koin itu
    pernah lolos Top 5). Aturan masuk tetap sama, termasuk batas masuk ulang per hari.
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._nav = navigator
        self._trader = trader
        self._analyzer = analyzer
        self._ranks = list(ranks)
        self._interval_s = interval_s
        self._sleep = sleep
        self._clock = clock
        self._watch: dict[str, float] = {}  # pair yang baru terjual di target -> akhir pantauan
        self._checked: dict[str, int] = {}  # pair -> candle 15 menit terakhir yang sudah dicek

    def run(self) -> None:
        self._resume_watch()
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

    def _refresh_safely(self) -> list[str]:
        """Jual otomatis; satu pengecekan yang gagal dicoba lagi menit depan, bot tetap jalan.

        Mengembalikan pair yang baru terjual di target."""
        try:
            return self._trader.sell_due()
        except BotError as exc:
            logger.error("Pengecekan jual otomatis gagal, dicoba lagi: %s", exc)
            return []

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
        """Tunggu putaran berikutnya sambil menjalankan jual otomatis posisi yang terbuka.

        Momentum: begitu ada posisi yang terjual di target, putaran berikutnya dimulai saat itu
        juga (tanpa menunggu sisa jeda). Koin yang baru terjual juga dicek ulang tiap candle
        15 menit baru di sela jeda putaran.
        """
        step = self._trader.watch_interval_s
        left = seconds
        while left > 0:
            wait = min(step, left)
            self._sleep(wait)
            left -= wait
            if left > 0:  # putaran berikutnya memeriksanya sendiri di awal
                sold = self._refresh_safely()
                if sold:
                    self._remember(sold)
                    logger.info(
                        "%s terjual di target: putaran baru dimulai sekarang", ", ".join(sold)
                    )
                    return
                self._recheck_between_rounds()

    # ------------------------------------------------------------------ momentum (masuk ulang)

    def _resume_watch(self) -> None:
        """Bot dijalankan ulang: koin yang terjual di target < 2 jam lalu tetap dipantau ulang."""
        for symbol, sold_at in self._trader.recent_target_sales(_MOMENTUM_WINDOW_S).items():
            self._watch[symbol] = sold_at + _MOMENTUM_WINDOW_S
            minutes = (self._watch[symbol] - self._clock()) / 60
            logger.info("%s terjual di target tadi: dicek ulang %.0f menit lagi", symbol, minutes)

    def _remember(self, sold: Sequence[str]) -> None:
        """Koin yang terjual di target: dicek ulang sekarang, lalu tiap candle baru selama 2 jam."""
        until = self._clock() + _MOMENTUM_WINDOW_S
        for symbol in sold:
            self._watch[symbol] = until
            self._checked.pop(symbol, None)
            logger.info(
                "%s terjual di target: dicek ulang tiap candle 15 menit selama %d jam",
                symbol,
                _MOMENTUM_WINDOW_S // 3600,
            )

    def _due(self, *, settled: bool) -> list[str]:
        """Pair pantauan momentum yang belum dicek di candle 15 menit ini.

        `settled`: hanya bila candle sebelumnya sudah tutup (cek di sela jeda putaran); di awal
        putaran pair yang baru terjual langsung dicek."""
        now = self._clock()
        for symbol, until in list(self._watch.items()):
            if now >= until:
                del self._watch[symbol]
                self._checked.pop(symbol, None)
                logger.info("%s: pantauan ulang 2 jam selesai", symbol)
        if settled and now % _CANDLE_S < _CANDLE_SETTLE_S:
            return []
        candle = _candle(now)
        return [s for s in self._watch if self._checked.get(s) != candle]

    def _recheck_between_rounds(self) -> None:
        """Candle 15 menit baru: cek ulang koin yang baru terjual tanpa menunggu putaran."""
        due = self._due(settled=True)
        if not due:
            return
        logger.info("Candle 15 menit baru: cek ulang %s", ", ".join(due))
        candle = _candle(self._clock())
        for (
            symbol
        ) in due:  # gagal pun tetap terhitung: dicoba lagi candle berikutnya, bukan tiap menit
            self._checked[symbol] = candle
        try:
            with self._nav.screen_turn():
                self._nav.prepare()
                listed = self._nav.open_top_gainers()
            rows = {row.rank: row for row in listed}
            source = self._reading_source()
            seen: set[str] = set()
            for symbol in due:
                with self._nav.screen_turn():
                    self._recheck(symbol, rows, source, seen)
        except BotError as exc:
            logger.error(
                "Cek ulang koin yang baru terjual gagal, dicoba candle berikutnya: %s", exc
            )

    def _recheck(
        self,
        symbol: str,
        rows: dict[int, GainerRow],
        source: ReadingSource | None,
        seen: set[str],
    ) -> bool:
        """Nilai ulang satu koin yang baru terjual (di dalam giliran layar). True bila masuk."""
        self._checked[symbol] = _candle(self._clock())
        blocker = self._trader.reentry_blocker(symbol)
        if blocker is None and self._trader.has_open(symbol):
            blocker = "posisinya masih terbuka"
        if blocker:
            logger.info("%s tidak dicek ulang lagi: %s", symbol, blocker)
            self._watch.pop(symbol, None)
            return False
        rank = next((row.rank for row in rows.values() if row.symbol == symbol), 0)
        where = f"Top {rank}" if rank else "lewat pencarian"
        logger.info("%s baru terjual di target: dicek ulang (%s)", symbol, where)
        try:
            try:
                opened = self._nav.open_symbol(symbol)  # masih di daftar Top 5
            except ScreenReadError:
                opened = self._nav.search_symbol(symbol)  # sudah keluar Top 5
        except BotError as exc:
            logger.warning(
                "%s tidak bisa dibuka untuk dicek ulang: %s",
                symbol,
                exc,
                extra=event(
                    "coin",
                    rank=rank,
                    symbol=symbol,
                    status="skipped",
                    verdict=None,
                    reason=str(exc),
                ),
            )
            return False
        if opened in seen:
            return False
        seen.add(opened)
        if self._trader.trade(rank, opened, source).status == "open":
            self._watch.pop(symbol, None)  # dipantau lagi setelah terjual berikutnya
            return True
        return False

    # ------------------------------------------------------------------ putaran

    def _reading_source(self) -> ReadingSource | None:
        analyzer = self._analyzer
        if analyzer is None:
            return None

        def read_chart(symbol: str, chart: Path) -> PatternReading:
            # Selama AI membaca, aplikasi MarketForge tampil supaya prosesnya terlihat; bursa
            # dibawa ke depan lagi sebelum langkah berikutnya (isi jumlah, klik).
            self._nav.show_app(
                f"AI membaca grafik {symbol}", symbol=symbol, chart=str(chart), stage="ai"
            )
            return analyzer.analyze(chart)

        return read_chart

    def run_cycle(self) -> int:
        """Satu putaran pemantauan. Mengembalikan jumlah posisi uji baru."""
        # Jual otomatis posisi yang sudah mencapai target; yang baru terjual dicek ulang lebih dulu.
        self._remember(self._trader.sell_due())
        with self._nav.screen_turn():
            self._nav.prepare()
            listed = self._nav.open_top_gainers()
        rows = {row.rank: row for row in listed}
        log_top_gainers(listed)
        source = self._reading_source()

        opened = 0
        seen: set[str] = set()
        for symbol in self._due(settled=False):
            with self._nav.screen_turn():
                if self._recheck(symbol, rows, source, seen):
                    opened += 1
        for rank in self._ranks:
            row = rows.get(rank)
            if row is not None and row.symbol in seen:
                continue  # sudah dicek ulang di atas
            # Satu koin = satu giliran layar: buka, baca grafik, AI, isi form, dan order tidak
            # boleh diselingi bot lain yang membuka koin lain di layar yang sama.
            with self._nav.screen_turn():
                if self._play(rank, row, source, seen):
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

    def _play(
        self, rank: int, row: GainerRow | None, source: ReadingSource | None, seen: set[str]
    ) -> bool:
        """Nilai satu Top (di dalam giliran layar). True bila posisi uji baru dibuka."""
        min_gain = self._trader.params.min_gain_pct
        if row is not None and row.change_pct < min_gain:
            logger.info(
                "#%d %s dilewati: naik %.1f%% < %g%%", rank, row.symbol, row.change_pct, min_gain
            )
            return False
        try:
            # Buka lewat namanya: peringkat sering bertukar di tengah putaran, sehingga klik
            # baris ke-N membuka pair lain (atau pair yang sama lagi) dan koin ke-N terlewat.
            if row is not None and is_futures_symbol(row.symbol):
                symbol = self._nav.open_symbol(row.symbol)
            else:
                # Daftar dibuka ulang: di antara giliran, bot lain bisa membuka halaman lain.
                self._nav.open_top_gainers()
                symbol = self._nav.open_gainer(rank)
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
            return False
        if symbol in seen:
            # Peringkat bergeser sehingga pair yang sama terbuka lagi: jangan nilai dua kali.
            logger.info("#%d sekarang %s: sudah dinilai di putaran ini, dilewati", rank, symbol)
            return False
        seen.add(symbol)
        return self._trader.trade(rank, symbol, source).status == "open"
