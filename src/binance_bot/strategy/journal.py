"""Jurnal SOP: setiap koin yang dinilai (dilewati atau masuk uji kertas) satu baris JSON."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

CLOSED_STATUSES = ("target", "stop", "timeout")


@dataclass(slots=True)
class JournalEntry:
    id: str
    created_at: float  # epoch detik; juga waktu masuk uji kertas
    symbol: str
    rank: int
    status: str = "skipped"  # skipped | open | target | stop | timeout
    reason: str = ""
    change_pct: float | None = None
    funding_rate: float | None = None
    spread_pct: float | None = None
    signs_ai: dict[str, bool] | None = None
    signs_data: dict[str, bool] | None = None
    ai_summary: str = ""
    margin: str = ""
    entry_price: float | None = None
    quantity: float | None = None
    notional: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    deadline: float | None = None
    exit_price: float | None = None
    closed_at: float | None = None
    funding_pct: float | None = None
    pnl_pct: float | None = None
    pnl_usdt: float | None = None
    screenshots: list[str] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return self.status in CLOSED_STATUSES

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
