from __future__ import annotations

import threading
from collections.abc import Sequence

from binance_bot.analysis import AnalysisRecord


class AnalysisStore:
    """Hasil analisis terbaru per koin. Aman dipakai bersamaan oleh leader dan server hub."""

    def __init__(self) -> None:
        self._records: dict[str, AnalysisRecord] = {}
        self._ranks: dict[int, str] = {}  # Top -> koin yang dinilai di putaran ini
        self._plan: tuple[int, ...] = ()  # Top yang dimainkan leader di putaran ini
        self._plan_started = 0.0
        self._plan_done = True
        self._lock = threading.Lock()

    def begin_cycle(self, ranks: Sequence[int] = (), at: float = 0.0) -> None:
        """Putaran baru: peta Top dikosongkan; hasil per koin tetap disimpan untuk dipakai ulang.

        `ranks` = Top yang akan dimainkan leader, agar follower tahu mana yang perlu ditunggu.
        """
        with self._lock:
            self._ranks.clear()
            self._plan = tuple(ranks)
            self._plan_started = at
            self._plan_done = False

    def end_cycle(self) -> None:
        """Leader selesai menilai semua Top putaran ini (follower tak perlu menunggu lagi)."""
        with self._lock:
            self._plan_done = True

    def plan(self) -> tuple[tuple[int, ...], bool, float]:
        """(Top yang dimainkan, putaran selesai?, waktu mulai putaran dengan jam leader)."""
        with self._lock:
            return self._plan, self._plan_done, self._plan_started

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
