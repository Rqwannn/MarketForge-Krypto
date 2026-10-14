"""Haiku membaca pola garis kuning (MA7) terhadap MA25 dari screenshot chart 15 menit (SOP V2).

AI hanya MENGAMATI: berapa kali garis kuning berada di bawah garis magenta, dan posisinya di
ujung kanan. Keputusan JANGAN/TUNGGU/OK diterapkan engine dari hitungan itu
(`MaPattern.verdict`), supaya ambang "minimal 2 kali" (usulan) bisa diubah tanpa mengubah
prompt dan keputusan AI bisa dibandingkan dengan hitungan data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from binance_bot.analysis.vision import PostJson, VisionClient, _post_json, extract_json
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError
from binance_bot.strategy.pattern import MaPattern

_MAX_COUNT = 50  # hitungan di atas ini tidak masuk akal untuk satu layar grafik

_TASK = """Tugas: ikuti garis KUNING terhadap garis MAGENTA di SELURUH grafik, dari kiri ke kanan.
Hitung berapa kali garis kuning berada DI BAWAH garis magenta sebagai periode terpisah:
- setiap kali garis kuning turun menembus ke bawah garis magenta dihitung 1;
- bila di ujung kiri grafik garis kuning sudah di bawah garis magenta, itu juga dihitung 1;
- bila garis kuning selalu di atas garis magenta, jawabannya 0.
Telusuri satu per satu dengan teliti sebelum menjawab.

Jawab HANYA dengan JSON valid, tanpa teks lain:
{
 "ma7_below_ma25_count": <bilangan bulat>,
 "ma7_below_ma25_now": true jika di ujung kanan garis kuning berada di bawah garis magenta,
 "summary": satu kalimat pendek, maksimal 20 kata, dalam Bahasa Indonesia
}"""

PROMPT = (
    """Ini screenshot grafik candlestick 15 MENIT dari Binance Futures.
Garis KUNING = MA7. Garis MAGENTA (merah muda) = MA25. Garis UNGU = MA99. Panel bawah = volume.
Abaikan kotak tombol Beli/Long dan Jual/Short yang melayang di atas grafik, dan abaikan lilin.

"""
    + _TASK
)

TEBBIT_PROMPT = """Ini screenshot grafik candlestick 15 MENIT dari Tebbit Futures (latar terang).
Di kiri atas ada legenda "MA 7", "MA 25", "MA 99"; tiap label berwarna sama dengan garisnya.
Cocokkan garis di grafik dengan warna di legenda. Panel bawah = volume.
Abaikan tombol dan tulisan yang melayang di atas grafik, dan abaikan lilin dan garis MA 99.

""" + _TASK.replace("KUNING", "MA 7").replace("kuning", "MA 7").replace("MAGENTA", "MA 25").replace(
    "magenta", "MA 25"
)


@dataclass(frozen=True, slots=True)
class PatternReading:
    pattern: MaPattern
    summary: str


class PatternAnalyzer(Protocol):
    def analyze(self, image: Path) -> PatternReading: ...


def pattern_from_dict(data: Any) -> PatternReading:
    """Validasi jawaban model. Isinya tidak dipercaya: wajib sesuai skema."""
    count = data.get("ma7_below_ma25_count") if isinstance(data, dict) else None
    summary = data.get("summary") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or not 0 <= count <= _MAX_COUNT
        or not isinstance(data.get("ma7_below_ma25_now"), bool)
        or not isinstance(summary, str)
        or not summary
    ):
        raise AnalysisError(f"Jawaban pola garis kuning tidak sesuai skema: {str(data)[:200]}")
    return PatternReading(MaPattern(count, data["ma7_below_ma25_now"]), summary)


class VikeyPatternAnalyzer:
    def __init__(
        self, settings: Settings, *, post: PostJson = _post_json, prompt: str = PROMPT
    ) -> None:
        self._client = VisionClient(settings, post=post)
        self._prompt = prompt

    def analyze(self, image: Path) -> PatternReading:
        return pattern_from_dict(extract_json(self._client.ask(image, self._prompt)))
