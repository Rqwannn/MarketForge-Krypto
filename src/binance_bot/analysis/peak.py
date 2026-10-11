"""AI visual menilai 4 tanda "pucuk" SOP dari screenshot grafik 15 menit Binance Futures."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from binance_bot.analysis.vision import PostJson, VisionClient, _post_json, extract_json
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError
from binance_bot.strategy.signals import PeakSigns

_SIGN_FIELDS = ("upper_wick", "failed_new_high", "volume_declining", "big_red_after_greens")

PROMPT = """Ini screenshot grafik candlestick 15 MENIT dari Binance Futures, untuk memutuskan
apakah kenaikan koin ini sudah "kehabisan tenaga" (pucuk) sebelum posisi short.
Hijau = naik, merah = turun. Panel bawah = volume. Abaikan kotak tombol Beli/Long dan
Jual/Short yang melayang di atas grafik. Nilai hanya beberapa lilin PALING KANAN.
Jawab HANYA dengan JSON valid, tanpa teks lain:
{
 "upper_wick": true jika lilin terakhir punya sumbu atas panjang (harga naik lalu ditolak),
 "failed_new_high": true jika puncak tertinggi terjadi beberapa lilin sebelumnya dan lilin
                    sesudahnya gagal melampauinya,
 "volume_declining": true jika volume beberapa lilin terakhir makin menurun,
 "big_red_after_greens": true jika lilin terakhir merah besar setelah deretan lilin hijau,
 "summary": satu kalimat pendek, maksimal 15 kata, dalam Bahasa Indonesia
}"""


@dataclass(frozen=True, slots=True)
class PeakReading:
    signs: PeakSigns
    summary: str


class PeakAnalyzer(Protocol):
    def analyze(self, image: Path) -> PeakReading: ...


def peak_from_dict(data: Any) -> PeakReading:
    """Validasi jawaban model. Isinya tidak dipercaya: wajib sesuai skema."""
    summary = data.get("summary") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or any(not isinstance(data.get(key), bool) for key in _SIGN_FIELDS)
        or not isinstance(summary, str)
        or not summary
    ):
        raise AnalysisError(f"Jawaban tanda pucuk tidak sesuai skema: {str(data)[:200]}")
    return PeakReading(PeakSigns(**{key: data[key] for key in _SIGN_FIELDS}), summary)


class VikeyPeakAnalyzer:
    def __init__(self, settings: Settings, *, post: PostJson = _post_json) -> None:
        self._client = VisionClient(settings, post=post)

    def analyze(self, image: Path) -> PeakReading:
        return peak_from_dict(extract_json(self._client.ask(image, PROMPT)))
