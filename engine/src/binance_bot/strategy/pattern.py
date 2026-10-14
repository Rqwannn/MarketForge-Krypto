"""Pola garis kuning (MA7) terhadap MA25 di chart 15 menit, filter masuk SOP V2.

Aturan beliau: selalu di atas = JANGAN short; baru sekali di bawah = TUNGGU; berkali-kali di
bawah = OK. "Berkali-kali" = minimal `min_crosses` (usulan 2). Hitungan = jumlah periode
terpisah saat MA7 berada di bawah MA25 dalam grafik yang dinilai.

OK juga menuntut kenaikan "mulai habis": MA7 pernah di bawah MA25 dalam 6 jam terakhir.
Turun berkali-kali SEBELUM lonjakan, lalu naik terus sampai ujung kanan, tetap TUNGGU.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise

from binance_bot.market import Candle

VERDICTS = ("jangan", "tunggu", "ok")
LOOKBACK_CANDLES = 96  # 24 jam lilin 15 menit, kira-kira seluas grafik yang dilihat AI
RECENT_CANDLES = 24  # 6 jam terakhir: MA7 harus pernah di bawah MA25 di sini untuk OK
_SLOW, _FAST = 25, 7


@dataclass(frozen=True, slots=True)
class MaPattern:
    below_count: int  # berapa kali (periode terpisah) MA7 berada di bawah MA25
    below_now: bool  # di ujung kanan, MA7 di bawah MA25
    below_recent: bool  # dalam 6 jam terakhir MA7 pernah di bawah MA25

    def verdict(self, min_crosses: int) -> str:
        if self.below_count == 0:
            return "jangan"  # selalu di atas: harga naik terus
        if self.below_count < min_crosses:
            return "tunggu"  # baru sekali di bawah: masih bisa naik besar
        if not self.below_recent:
            return "tunggu"  # turunnya sebelum lonjakan; sekarang masih naik terus
        return "ok"  # berkali-kali di bawah dan baru saja turun lagi: cenderung turun

    def as_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _sma(values: Sequence[float], period: int, end: int) -> float:
    return sum(values[end - period + 1 : end + 1]) / period


def data_ma_pattern(candles: Sequence[Candle], lookback: int = LOOKBACK_CANDLES) -> MaPattern:
    """Hitung pola dari candle yang sudah tutup (lilin terakhir dari API masih berjalan)."""
    closes = [c.close for c in candles[:-1]]
    if len(closes) < lookback + _SLOW - 1:
        raise ValueError(f"Butuh minimal {lookback + _SLOW - 1} lilin tertutup, ada {len(closes)}")
    window = range(len(closes) - lookback, len(closes))
    below = [_sma(closes, _FAST, i) < _sma(closes, _SLOW, i) for i in window]
    count = int(below[0]) + sum(1 for prev, now in pairwise(below) if now and not prev)
    return MaPattern(
        below_count=count, below_now=below[-1], below_recent=any(below[-RECENT_CANDLES:])
    )


def candles_needed(lookback: int = LOOKBACK_CANDLES) -> int:
    """Jumlah candle yang diminta dari API: jendela + MA25 + lilin yang masih berjalan."""
    return lookback + _SLOW + 1
