"""Hapus riwayat analisis AI dari jurnal: satu entri, atau bersihkan semua yang bukan trade.

"Bersihkan" hanya membuang koin yang dilewati dan gambar contoh; posisi uji (trade) tetap ada
karena dipakai untuk fase uji 50 trade. Satu trade hanya terhapus bila dipilih satu per satu.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from binance_bot.exceptions import BotError
from binance_bot.strategy import Journal, JournalEntry

logger = logging.getLogger(__name__)

NOT_TRADES = ("skipped", "contoh")


class HistoryWorkflow:
    name = "riwayat"

    def __init__(
        self,
        journal: Journal,
        *,
        delete_id: str | None = None,
        clear: bool = False,
        output: Callable[[str], None] = print,
    ) -> None:
        if (delete_id is None) == (not clear):
            raise BotError("Pilih salah satu: --hapus ID atau --bersihkan")
        self._journal = journal
        self._delete_id = delete_id
        self._clear = clear
        self._output = output

    def run(self) -> None:
        removed = 0

        def keep(entries: list[JournalEntry]) -> list[JournalEntry]:
            nonlocal removed
            if self._clear:
                kept = [e for e in entries if e.status not in NOT_TRADES]
            else:
                kept = [e for e in entries if e.id != self._delete_id]
                if len(kept) == len(entries):
                    raise BotError(f"Riwayat {self._delete_id} tidak ditemukan")
            removed = len(entries) - len(kept)
            return kept

        self._journal.rewrite(keep)
        logger.info("Riwayat dihapus: %d entri", removed)
        self._output(json.dumps({"removed": removed}))
