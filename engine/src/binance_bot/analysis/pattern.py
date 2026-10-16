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
    close = data.get("ma7_ma25_close")  # hanya prompt Binance (V3) yang menanyakannya
    if close is not None and not isinstance(close, bool):
        raise AnalysisError(f"Jawaban 'garis berdekatan' bukan true/false: {str(data)[:200]}")
    pattern = MaPattern(count, data["ma7_below_ma25_now"], data["ma7_below_ma25_recent"], close)
    return PatternReading(pattern, summary)


class VikeyPatternAnalyzer:
    def __init__(self, settings: Settings, prompt: str, *, post: PostJson = _post_json) -> None:
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
        judged = [r.pattern.lines_close for r in readings if r.pattern.lines_close is not None]
        close = sum(judged) * 2 > len(judged) if judged else None
        pattern = MaPattern(counts[len(counts) // 2], now, recent, close)
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
