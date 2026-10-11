"""Empat tanda "pucuk" dari SOP, dihitung dari candle 15 menit.

Definisi angka di bawah adalah usulan (PDF hanya menyebut nama tandanya). Hasil versi data ini
dicatat di jurnal sebagai pembanding keputusan AI, atau menjadi penentu bila SINYAL=data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import mean

from binance_bot.market import Candle

MIN_CANDLES = 12
UPPER_WICK_OF_RANGE = 0.5  # sumbu atas >= 50% dari panjang lilin
HIGH_LOOKBACK = 8  # puncak dicari di 8 lilin terakhir
BIG_BODY_VS_AVERAGE = 1.5  # lilin merah >= 1,5x rata-rata badan 5 lilin sebelumnya
MIN_GREENS_BEFORE = 3  # minimal 3 hijau di 4 lilin sebelum lilin merah


@dataclass(frozen=True, slots=True)
class PeakSigns:
    upper_wick: bool  # sumbu atas panjang: harga ditolak di atas
    failed_new_high: bool  # gagal bikin high baru: puncak tak terlampaui
    volume_declining: bool  # volume menurun: tenaga beli melemah
    big_red_after_greens: bool  # lilin merah besar setelah deretan hijau

    @property
    def count(self) -> int:
        return sum(asdict(self).values())

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


def data_peak_signs(candles: Sequence[Candle]) -> PeakSigns:
    """Nilai 4 tanda pada lilin 15 menit terakhir yang SUDAH tutup.

    Lilin paling akhir dari API masih berjalan, jadi tidak dipakai.
    """
    closed = list(candles[:-1])
    if len(closed) < MIN_CANDLES:
        raise ValueError(f"Butuh minimal {MIN_CANDLES} lilin tertutup, ada {len(closed)}")
    last = closed[-1]
    body = abs(last.close - last.open)
    span = last.high - last.low

    recent = closed[-HIGH_LOOKBACK:]
    peak_index = max(range(len(recent)), key=lambda i: recent[i].high)

    v1, v2, v3 = (c.volume for c in closed[-3:])
    before = closed[-6:-1]

    return PeakSigns(
        upper_wick=span > 0
        and last.high - max(last.open, last.close) >= UPPER_WICK_OF_RANGE * span,
        # Puncak terjadi minimal 2 lilin sebelum lilin terakhir, lalu tidak terlampaui lagi.
        failed_new_high=peak_index <= len(recent) - 3,
        volume_declining=v1 > v2 > v3,
        big_red_after_greens=not last.is_green
        and body >= BIG_BODY_VS_AVERAGE * mean(abs(c.close - c.open) for c in before)
        and sum(c.is_green for c in before[-4:]) >= MIN_GREENS_BEFORE,
    )
