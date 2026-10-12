from __future__ import annotations

import threading

from binance_bot.analysis import AnalysisRecord


class AnalysisStore:
    """Hasil analisis terbaru per koin. Aman dipakai bersamaan oleh leader dan server hub."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._ranks: dict[int, str] = {}  # Top -> koin yang dinilai di putaran ini
        self._lock = threading.Lock()

    def begin_cycle(self) -> None:
        """Putaran baru: peta Top dikosongkan; hasil per koin tetap disimpan untuk dipakai ulang."""
        with self._lock:
            self._ranks.clear()

    def put(self, record: AnalysisRecord) -> None:
        with self._lock:
            self._records[record.symbol] = record
            self._ranks[record.rank] = record.symbol

    def by_rank(self, rank: int) -> AnalysisRecord | None:
        """Hasil untuk Top `rank` di putaran ini, atau None bila leader belum menilainya."""
        with self._lock:
            symbol = self._ranks.get(rank)
            return self._records.get(symbol) if symbol else None

    def get(self, symbol: str) -> AnalysisRecord | None:
        with self._lock:
            return self._records.get(symbol)

    def fresh(self, symbol: str, max_age_s: float, now: float) -> AnalysisRecord | None:
        """Hasil koin ini jika umurnya masih di bawah `max_age_s`, agar AI tidak dipanggil lagi."""
        record = self.get(symbol)
        return record if record is not None and record.age_s(now) <= max_age_s else None

    def all(self) -> list[AnalysisRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.rank)
