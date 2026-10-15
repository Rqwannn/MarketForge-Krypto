"""Jurnal SOP: setiap koin yang dinilai (dilewati atau masuk uji kertas) satu baris JSON.

Isi per trade mengikuti "Yang dicatat tiap trade" di SOP V2: koin, kenaikan 24 jam, jam masuk
dan keluar, harga masuk dan keluar, hasil bersih setelah fee dan funding, harga tertinggi
setelah masuk, berapa kali MA7 di bawah MA25 saat masuk, dan alasan keluar (status).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

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
    funding_rate: float | None = None
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
    ma_gap_pct: float | None = None  # jarak garis cepat ke garis pembanding saat masuk (%)
    checked_ms: int | None = None  # posisi sudah dinilai dari candle sampai waktu ini
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


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [JournalEntry.from_dict(json.loads(line)) for line in lines if line.strip()]

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def save(self, entries: list[JournalEntry]) -> None:
        """Tulis ulang seluruh jurnal secara atomik (aman bila proses terhenti di tengah)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
