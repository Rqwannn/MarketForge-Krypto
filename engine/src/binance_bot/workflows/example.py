"""AI menilai gambar grafik contoh (mis. kiriman Pak Saputra) dan mencatatnya di riwayat analisis.

Gambar disalin ke folder screenshot sebagai `*_15m.png` supaya aplikasi bisa menampilkannya.
Status "contoh" tidak dihitung sebagai trade atau koin yang dilewati.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from binance_bot.analysis import PatternAnalyzer
from binance_bot.exceptions import BotError
from binance_bot.market import is_futures_symbol
from binance_bot.strategy import Journal, JournalEntry, SopParams

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ExampleWorkflow:
    name = "contoh"

    def __init__(
        self,
        image: Path,
        symbol: str,
        note: str,
        analyzer: PatternAnalyzer,
        journal: Journal,
        screenshot_dir: Path,
        params: SopParams,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._image = image
        self._symbol = symbol.upper()
        self._note = note.strip()
        self._analyzer = analyzer
        self._journal = journal
        self._shots = screenshot_dir
        self._params = params
        self._wall_clock = wall_clock

    def run(self) -> None:
        if not is_futures_symbol(self._symbol):
            raise BotError(f"Nama pair tidak valid: {self._symbol!r} (contoh: MAGICUSDT)")
        if not self._image.is_file() or self._image.suffix.lower() != ".png":
            raise BotError(f"Gambar grafik tidak ditemukan atau bukan PNG: {self._image}")
        if self._image.stat().st_size > _MAX_IMAGE_BYTES:
            raise BotError("Gambar terlalu besar (maksimal 8 MB)")
        now = self._wall_clock()
        stamp = datetime.fromtimestamp(now).strftime("%Y%m%d_%H%M%S")
        self._shots.mkdir(parents=True, exist_ok=True)
        chart = self._shots / f"{stamp}_contoh_{self._symbol}_15m.png"
        shutil.copyfile(self._image, chart)

        reading = self._analyzer.analyze(chart)
        verdict = reading.pattern.verdict(self._params.min_crosses)
        self._journal.append(
            JournalEntry(
                id=f"{stamp}_contoh_{self._symbol}",
                created_at=now,
                symbol=self._symbol,
                rank=0,
                status="contoh",
                role="contoh",
                verdict=verdict,
                pattern_ai=reading.pattern.as_dict(),
                ai_summary=reading.summary,
                reason=f"Contoh: {self._note}" if self._note else "Contoh grafik",
                screenshots=[str(chart)],
            )
        )
        logger.info(
            "Contoh %s: AI %d kali di bawah MA25 (6 jam terakhir: %s) -> %s | %s",
            self._symbol,
            reading.pattern.below_count,
            "ya" if reading.pattern.below_recent else "tidak",
            verdict.upper(),
            reading.summary,
        )
