"""Haiku membaca pola garis kuning (MA7) terhadap MA25 dari screenshot chart 15 menit (SOP V2).

AI hanya MENGAMATI: berapa kali garis kuning berada di bawah garis magenta, dan posisinya di
ujung kanan. Keputusan JANGAN/TUNGGU/OK diterapkan engine dari hitungan itu
(`MaPattern.verdict`), supaya ambang "minimal 2 kali" (usulan) bisa diubah tanpa mengubah
prompt dan keputusan AI bisa dibandingkan dengan hitungan data.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from binance_bot.analysis.vision import PostJson, VisionClient, _post_json, extract_json
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError
from binance_bot.strategy.pattern import MaPattern

_MAX_COUNT = 50  # hitungan di atas ini tidak masuk akal untuk satu layar grafik

_TASK = """Tugas: nilai KENAIKAN TERAKHIR saja, yaitu dari titik terendah tepat sebelum harga naik
besar sampai ujung kanan grafik (bagian yang biasa dilingkari trader). Naik-turun garis SEBELUM
kenaikan itu dimulai TIDAK dihitung, karena belum termasuk kenaikan yang mau di-short.
Di bagian kenaikan itu, ikuti garis KUNING terhadap garis MAGENTA dari kiri ke kanan.
Hitung berapa kali garis kuning berada DI BAWAH garis magenta sebagai periode terpisah:
- setiap kali garis kuning turun menembus ke bawah garis magenta dihitung 1;
- bila garis kuning selalu di atas garis magenta selama kenaikan, jawabannya 0.
Penurunan SINGKAT tetap dihitung: walau hanya beberapa lilin dan garis kuning hanya sedikit
menembus ke bawah garis magenta (garis berpotongan lalu kembali ke atas), itu 1 kali.
Perhatikan khususnya bagian kanan grafik setelah harga naik: saat harga mendatar di puncak,
garis kuning sering berpotongan dengan garis magenta berkali-kali.
Telusuri satu per satu dengan teliti sebelum menjawab.

Jawab HANYA dengan JSON valid, tanpa teks lain:
{
 "ma7_below_ma25_count": <bilangan bulat>,
 "ma7_below_ma25_now": true jika di ujung kanan garis kuning berada di bawah garis magenta,
 "ma7_below_ma25_recent": true jika dalam 6 JAM TERAKHIR, yaitu sekitar 24 LILIN TERAKHIR di ujung
   kanan grafik (1 lilin = 15 menit), garis kuning pernah berada di bawah garis magenta; false bila
   di 24 lilin terakhir itu garis kuning terus di atas garis magenta. Hitung lilinnya, jangan
   menebak dari label sumbu waktu: angka tanpa titik dua di sumbu (mis. "13", "14", "10/14")
   adalah TANGGAL (pergantian hari), bukan jam,
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
Di kiri atas ada legenda garis rata-rata, mis. "MA 7", "MA 25", "MA 99" atau "MA 5", "MA 10",
"MA 30"; tiap label berwarna sama dengan garisnya. Cocokkan garis dengan warna di legenda.
- GARIS CEPAT = garis berlabel MA 7; bila tidak ada MA 7, pakai garis MA 5.
- GARIS PEMBANDING = garis berlabel MA 25; bila tidak ada MA 25, pakai garis MA 30.
Abaikan garis lain, lilin, panel volume di bawah, dan tombol atau tulisan yang melayang.

""" + _TASK.replace("KUNING", "CEPAT").replace("kuning", "cepat").replace(
    "MAGENTA", "PEMBANDING"
).replace("magenta", "pembanding")


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
        or not isinstance(data.get("ma7_below_ma25_recent"), bool)
        or not isinstance(summary, str)
        or not summary
    ):
        raise AnalysisError(f"Jawaban pola garis kuning tidak sesuai skema: {str(data)[:200]}")
    pattern = MaPattern(count, data["ma7_below_ma25_now"], data["ma7_below_ma25_recent"])
    return PatternReading(pattern, summary)


class VikeyPatternAnalyzer:
    def __init__(
        self, settings: Settings, *, post: PostJson = _post_json, prompt: str = PROMPT
    ) -> None:
        self._client = VisionClient(settings, post=post)
        self._prompt = prompt

    def analyze(self, image: Path) -> PatternReading:
        return pattern_from_dict(extract_json(self._client.ask(image, self._prompt)))


class ConsensusAnalyzer:
    """AI membaca grafik yang sama beberapa kali sekaligus; hasilnya suara terbanyak.

    Satu bacaan AI bisa berbeda dari bacaan berikutnya untuk gambar yang sama. Hitungan diambil
    nilai tengahnya, "di bawah sekarang" dan "6 jam terakhir" diambil suara terbanyak.
    """

    def __init__(self, analyzer: PatternAnalyzer, reads: int = 5) -> None:
        self._inner = analyzer
        self._reads = reads

    def analyze(self, image: Path) -> PatternReading:
        with ThreadPoolExecutor(self._reads) as pool:
            results = list(pool.map(self._try, [image] * self._reads))
        readings = [r for r in results if isinstance(r, PatternReading)]
        if len(readings) * 2 <= self._reads:
            error = next(r for r in results if isinstance(r, AnalysisError))
            raise AnalysisError(f"Mayoritas bacaan AI gagal: {error}")
        counts = sorted(r.pattern.below_count for r in readings)
        now = sum(r.pattern.below_now for r in readings) * 2 > len(readings)
        recent = sum(r.pattern.below_recent for r in readings) * 2 > len(readings)
        pattern = MaPattern(counts[len(counts) // 2], now, recent)
        same = [r for r in readings if r.pattern.below_recent == recent]
        summary = min(same, key=lambda r: abs(r.pattern.below_count - pattern.below_count)).summary
        votes = ", ".join(
            f"{r.pattern.below_count}{'+' if r.pattern.below_recent else ''}" for r in readings
        )
        return PatternReading(pattern, f"{summary} ({len(readings)} bacaan AI: {votes})")

    def _try(self, image: Path) -> PatternReading | AnalysisError:
        try:
            return self._inner.analyze(image)
        except AnalysisError as exc:
            return exc
