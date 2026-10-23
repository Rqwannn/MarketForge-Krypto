"""Pola garis cepat ("garis kuning") terhadap garis pembanding di chart 15 menit (SOP V2).

Hasil bacaan (hitungan turun, sekarang, baru-baru ini) berlaku untuk semua platform. Aturan
keputusannya (jangan/tunggu/ok) ada di profil tiap platform: strategy/profile.py.
Penghitungan dari data candle (data_ma_pattern) hanya untuk bursa yang punya candle (Binance).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise

from binance_bot.market import Candle

VERDICTS = ("jangan", "tunggu", "ok")
LOOKBACK_CANDLES = 96  # 24 jam lilin 15 menit, kira-kira seluas grafik yang dilihat AI
RECENT_CANDLES = 24  # 6 jam lilin 15 menit


@dataclass(frozen=True, slots=True)
class MaPattern:
    below_count: int  # berapa kali (periode terpisah) garis cepat berada di bawah pembanding
    below_now: bool  # di ujung kanan, garis cepat di bawah pembanding
    below_recent: bool  # dalam beberapa jam terakhir garis cepat pernah di bawah pembanding
    # SOP V3 (Binance): di ujung kanan garis cepat dan pembanding berdekatan. None = tidak dinilai.
    lines_close: bool | None = None

    def as_dict(self) -> dict[str, int | bool]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True, slots=True)
class LongPattern:
    """Tiga tanda masuk LONG (SOP 23 Okt) yang terlihat di grafik 15 menit."""

    reversal: bool  # tanda 1: turun tajam di bawah MA7 dan MA25 sampai dasar, lalu berbalik naik
    flat: bool  # tanda 2: harga mendatar cukup lama, MA7, MA25, dan MA99 saling berdekatan
    far_above: bool  # tanda 3: MA7 jauh di atas MA25 dan MA99

    @property
    def signs(self) -> list[int]:
        return [n for n, seen in enumerate((self.reversal, self.flat, self.far_above), 1) if seen]

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


def _sma(values: Sequence[float], period: int, end: int) -> float:
    return sum(values[end - period + 1 : end + 1]) / period


def data_ma_pattern(
    candles: Sequence[Candle],
    lookback: int = LOOKBACK_CANDLES,
    *,
    fast: int = 7,
    mid: int = 25,
    recent: int = RECENT_CANDLES,
) -> MaPattern:
    """Hitung pola dari candle yang sudah tutup (lilin terakhir dari API masih berjalan)."""
    closes = [c.close for c in candles[:-1]]
    if len(closes) < lookback + mid - 1:
        raise ValueError(f"Butuh minimal {lookback + mid - 1} lilin tertutup, ada {len(closes)}")
    window = range(len(closes) - lookback, len(closes))
    below = [_sma(closes, fast, i) < _sma(closes, mid, i) for i in window]
    count = int(below[0]) + sum(1 for prev, now in pairwise(below) if now and not prev)
    return MaPattern(below_count=count, below_now=below[-1], below_recent=any(below[-recent:]))


def ma_gap_pct(candles: Sequence[Candle], *, fast: int = 7, mid: int = 25) -> float:
    """Jarak garis cepat di bawah pembanding pada lilin tertutup terakhir, dalam persen.

    Positif = garis cepat di bawah (V3: MA7 sekitar 4,7% di bawah MA25 pada GTC dan RSR).
    """
    closes = [c.close for c in candles[:-1]]
    if len(closes) < mid:
        raise ValueError(f"Butuh minimal {mid} lilin tertutup, ada {len(closes)}")
    end = len(closes) - 1
    slow_ma = _sma(closes, mid, end)
    return 100 * (slow_ma - _sma(closes, fast, end)) / slow_ma


def long_numbers(candles: Sequence[Candle], lookback: int = LOOKBACK_CANDLES) -> dict[str, float]:
    """Angka bacaan LONG (V4) pada lilin tertutup terakhir, untuk dicatat di fase uji.

    Tidak memutuskan apa pun: ambang tiap tanda LONG belum ditetapkan, jadi angka ini menjadi
    bahan untuk menetapkannya. Persen terhadap garis/harga pembanding.
    """
    closes = [c.close for c in candles[:-1]]
    if len(closes) < 99:
        raise ValueError(f"Butuh minimal 99 lilin tertutup, ada {len(closes)}")
    end = len(closes) - 1
    ma7, ma25, ma99 = (_sma(closes, period, end) for period in (7, 25, 99))
    window = candles[:-1][-lookback:]
    high = max(c.high for c in window)
    low = min(c.low for c in window)
    last = closes[-1]
    return {
        "ma7": ma7,
        "ma25": ma25,
        "ma99": ma99,
        "ma7_above_ma25_pct": 100 * (ma7 - ma25) / ma25,  # tanda 3: MA7 jauh di atas
        "ma7_above_ma99_pct": 100 * (ma7 - ma99) / ma99,
        "ma_spread_pct": 100 * (max(ma7, ma25, ma99) - min(ma7, ma25, ma99)) / last,  # tanda 2
        "drop_from_high_pct": 100 * (high - low) / high,  # tanda 1: seberapa tajam turun
        "up_from_low_pct": 100 * (last - low) / low,  # tanda 1: sudah berbalik dari dasar
    }


def candles_needed(lookback: int = LOOKBACK_CANDLES, mid: int = 25) -> int:
    """Jumlah candle yang diminta dari API: jendela + garis pembanding + lilin yang berjalan."""
    return lookback + mid + 1
