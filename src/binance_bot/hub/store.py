from __future__ import annotations

import threading

from binance_bot.analysis import AnalysisRecord


class AnalysisStore:
    """Hasil analisis terbaru per koin. Aman dipakai bersamaan oleh leader dan server hub."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._lock = threading.Lock()

    def put(self, record: AnalysisRecord) -> None:
        with self._lock:
            self._records[record.symbol] = record

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
