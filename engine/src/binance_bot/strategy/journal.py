"""Jurnal SOP: setiap koin yang dinilai (dilewati atau masuk uji kertas) satu baris JSON.

Isi per trade mengikuti "Yang dicatat tiap trade" di SOP V2: koin, kenaikan 24 jam, jam masuk
dan keluar, harga masuk dan keluar, hasil bersih setelah fee dan funding, harga tertinggi
setelah masuk, berapa kali MA7 di bawah MA25 saat masuk, dan alasan keluar (status).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from binance_bot.filelock import exclusive

_T = TypeVar("_T")

# stop dan timeout hanya ada di catatan lama (SOP V2); V3 tanpa stop-loss dan batas waktu.
CLOSED_STATUSES = ("target", "likuidasi", "manual", "stop", "timeout")


@dataclass(slots=True)
class JournalEntry:
    id: str
    created_at: float  # epoch detik; juga waktu masuk uji kertas
    symbol: str
    rank: int
    # skipped | open | target | likuidasi | manual (Sell) | contoh (gambar contoh)
    status: str = "skipped"
    role: str = "single"  # single (Sendiri) | follower (Pengikut) | contoh (gambar contoh)
    reason: str = ""
    change_pct: float | None = None
    funding_rate: float | None = None  # catatan lama: saringan funding sudah dihapus (20 Okt 2026)
    spread_pct: float | None = None
    pattern_ai: dict[str, Any] | None = None  # {"below_count", "below_now"} dari AI
    pattern_data: dict[str, Any] | None = None  # sama, dihitung dari candle
    verdict: str = ""  # jangan | tunggu | ok (dari sumber penentu)
    ai_summary: str = ""
    margin: str = ""  # mode margin dan leverage yang terbaca di aplikasi
    capital_usdt: float | None = None
    leverage: int | None = None
    margin_usdt: float | None = None
    entry_price: float | None = None
    quantity: float | None = None
    notional: float | None = None
    target_price: float | None = None
    stop_price: float | None = None  # catatan lama (SOP V2)
    deadline: float | None = None  # catatan lama (SOP V2)
    max_price: float | None = None  # harga tertinggi setelah masuk (melawan posisi short)
    min_price: float | None = None  # harga terendah setelah masuk (seberapa jauh harga turun)
    # Harga ask terakhir yang terbaca untuk posisi ini dan kapan (detik epoch). Tebbit membaca
    # harga dari layar, jadi daftar Posisi memakai angka ini saat layar tidak dibuka.
    last_price: float | None = None
    last_price_at: float | None = None
    ma_gap_pct: float | None = None  # jarak garis cepat ke garis pembanding saat masuk (%)
    checked_ms: int | None = None  # posisi sudah dinilai dari candle sampai waktu ini
    # Real Fund Trading: posisi sungguhan di bursa. Hanya ditutup oleh proses mode real yang
    # menekan tombol tutup; penilaian uji kertas tidak pernah mengubahnya.
    real: bool = False
    exit_price: float | None = None
    closed_at: float | None = None
    funding_pct: float | None = None
    pnl_pct: float | None = None  # hasil bersih terhadap nilai posisi
    pnl_usdt: float | None = None
    screenshots: list[str] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.status in CLOSED_STATUSES

    @property
    def pnl_capital_pct(self) -> float | None:
        """Hasil bersih dalam persen modal (SOP: laporkan dalam persen modal, bukan ROI)."""
        if self.pnl_usdt is None or not self.capital_usdt:
            return None
        return 100 * self.pnl_usdt / self.capital_usdt

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalEntry:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


# Windows menolak mengganti atau membuka file yang sedang dipakai proses lain (WinError 32/5): bot
# dan perintah jurnal dari aplikasi bisa menyentuh file yang sama bersamaan. Kuncinya singkat, jadi
# cukup diulang beberapa kali (uji nyata: halaman Hasil uji crash saat bot menulis jurnal).
_LOCK_ATTEMPTS = 20
_LOCK_DELAY_S = 0.25


def _retry_locked(action: Callable[[], _T]) -> _T:
    for attempt in range(_LOCK_ATTEMPTS):
        try:
            return action()
        except PermissionError:
            if attempt + 1 == _LOCK_ATTEMPTS:
                raise
            time.sleep(_LOCK_DELAY_S)
    raise AssertionError("tidak tercapai")  # pragma: no cover


class Journal:
    """Jurnal JSONL. Beberapa bot (proses) di satu laptop bisa memakai jurnal yang sama, jadi
    setiap penulisan memegang kunci jurnal dan perubahan ditulis di atas isi file TERBARU: catatan
    yang ditambahkan bot lain di antara baca dan tulis tidak tertimpa."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _writing(self) -> Iterator[None]:
        # Ditahan sebentar (baca + tulis file), tidak pernah sambil memakai layar atau jaringan.
        with exclusive(
            self.path.with_suffix(".write.lock"),
            timeout_s=60.0,
            busy="Jurnal sedang ditulis bot lain",
        ):
            yield

    def load(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        lines = _retry_locked(lambda: self.path.read_text(encoding="utf-8")).splitlines()
        return [JournalEntry.from_dict(json.loads(line)) for line in lines if line.strip()]

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"

        def write() -> None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        with self._writing():
            _retry_locked(write)

    def rewrite(
        self, change: Callable[[list[JournalEntry]], list[JournalEntry]]
    ) -> list[JournalEntry]:
        """Ubah jurnal dari isi file terbaru: `change(entries)` -> isi baru (ditulis bila beda)."""
        with self._writing():
            entries = self.load()
            updated = change(entries)
            if updated != entries:
                self.save(updated)
            return updated

    def replace(self, changed: Sequence[JournalEntry]) -> list[JournalEntry]:
        """Ganti entri yang berubah (dicocokkan lewat id dan waktu dibuat) di isi file terbaru."""
        by_key = {(e.id, e.created_at): e for e in changed}
        if not by_key:
            return self.load()
        return self.rewrite(lambda entries: [by_key.get((e.id, e.created_at), e) for e in entries])

    def save(self, entries: list[JournalEntry]) -> None:
        """Tulis ulang seluruh jurnal secara atomik (aman bila proses terhenti di tengah)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Nama sementara per proses: dua proses menulis bersamaan tidak saling menimpa.
        tmp = self.path.with_name(f"{self.path.stem}.{os.getpid()}.tmp")
        tmp.write_text(
            "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        try:
            _retry_locked(lambda: os.replace(tmp, self.path))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
