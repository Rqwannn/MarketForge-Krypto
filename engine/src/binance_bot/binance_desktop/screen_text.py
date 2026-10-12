"""Mengubah teks hasil OCR layar Binance menjadi data. Semua fungsi murni (tanpa layar)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from binance_bot.binance_desktop import layout
from binance_bot.exceptions import ScreenReadError
from binance_bot.macos import TextLine

# Pair Futures tampil tanpa garis miring, mis. "STRKUSDT Perpetual" atau "STRKUSDT Perp".
# Nama koin bisa satu huruf (mis. "SUSDT" untuk Sonic).
FUTURES_SYMBOL_PATTERN = re.compile(r"\b([A-Z0-9]{1,20}USD[TC])\s*Perp")
_PERCENT = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)%$")
_LEVERAGE = re.compile(r"^(\d{1,3})x$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GainerRow:
    rank: int
    symbol: str  # mis. "STRKUSDT"
    change_pct: float


@dataclass(frozen=True, slots=True)
class MarginSettings:
    isolated: bool | None  # None = tidak terbaca
    leverage: int | None

    def problems(self, leverage: int) -> list[str]:
        """Perbedaan dengan SOP V2: leverage wajib sesuai, isolated disarankan (usulan)."""
        issues = []
        if self.leverage != leverage:
            shown = "?" if self.leverage is None else self.leverage
            issues.append(f"leverage {shown}x, SOP {leverage}x")
        if self.isolated is not True:
            issues.append("bukan Isolated (usulan SOP; bila tetap Cross, stop-loss wajib)")
        return issues

    def describe(self) -> str:
        mode = {True: "Isolated", False: "Cross", None: "?"}[self.isolated]
        return f"{mode} {self.leverage if self.leverage is not None else '?'}x"


def parse_futures_symbol(texts: Sequence[str]) -> str:
    for text in texts:
        match = FUTURES_SYMBOL_PATTERN.search(text)
        if match:
            return match.group(1)
    raise ScreenReadError(f"Pair Futures tidak terbaca di halaman trade (OCR: {list(texts)[:6]})")


def parse_percent(text: str) -> float | None:
    match = _PERCENT.match(text.replace(" ", ""))
    return float(match.group(1).replace(",", ".")) if match else None


def parse_gainer_rows(lines: Sequence[TextLine], area: tuple[float, ...]) -> list[GainerRow]:
    """Pasangkan nama pair dan persentase per baris berdasarkan posisi vertikal.

    `lines` relatif terhadap gambar `area` (x0, y0, x1, y1 relatif jendela). Nomor baris
    dihitung dari posisi di layar, jadi baris yang gagal dibaca OCR tidak menggeser rank lain.
    """
    _, top, _, bottom = area

    def window_y(line: TextLine) -> float:
        return top + line.y * (bottom - top)

    percents: list[tuple[float, float]] = [
        (window_y(line), p) for line in lines if (p := parse_percent(line.text)) is not None
    ]
    rows: dict[int, GainerRow] = {}
    for line in lines:
        match = FUTURES_SYMBOL_PATTERN.search(line.text)
        if not match:
            continue
        y = window_y(line)
        nearest = min(percents, key=lambda item: abs(item[0] - y), default=None)
        if nearest is None or abs(nearest[0] - y) > layout.FUTURES_ROW_STEP / 2:
            continue
        rank = layout.rank_at(y)
        rows.setdefault(rank, GainerRow(rank, match.group(1), nearest[1]))
    return [rows[rank] for rank in sorted(rows)]


def is_sorted_by_top_gain(rows: Sequence[GainerRow]) -> bool:
    changes = [row.change_pct for row in rows]
    return bool(changes) and changes[0] > 0 and changes == sorted(changes, reverse=True)


def parse_margin(texts: Iterable[str]) -> MarginSettings:
    isolated: bool | None = None
    leverage: int | None = None
    for raw in texts:
        text = raw.strip().lower()
        if "isol" in text or "teris" in text:
            isolated = True
        elif "cross" in text or "silang" in text:
            isolated = False
        match = _LEVERAGE.match(raw.strip())
        if match:
            leverage = int(match.group(1))
    return MarginSettings(isolated, leverage)


def _readings(shown: str) -> set[float]:
    """Nilai yang mungkin dimaksud teks di kolom.

    Binance Indonesia menampilkan angka besar dengan titik ribuan ("3.367,2"), sedangkan yang
    diketik bot memakai koma desimal ("3367,2"). Titik tunggal bisa titik ribuan atau desimal,
    jadi kedua tafsiran dicoba: "." ribuan + "," desimal, dan "," ribuan + "." desimal.
    """
    text = re.sub(r"[^0-9.,]", "", shown)
    values: set[float] = set()
    for candidate in (text.replace(".", "").replace(",", "."), text.replace(",", "")):
        try:
            values.add(float(candidate))
        except ValueError:
            continue
    return values


def same_number(shown: str, typed: str) -> bool:
    """Apakah teks di kolom bernilai sama dengan angka yang diketik.

    Pemisah ribuan dan angka nol di belakang koma diabaikan ("3.367,2" = "3367,2", "41" = "41,0").
    """
    try:
        wanted = float(re.sub(r"[^0-9.,]", "", typed).replace(",", "."))
    except ValueError:
        return False
    return wanted in _readings(shown)
