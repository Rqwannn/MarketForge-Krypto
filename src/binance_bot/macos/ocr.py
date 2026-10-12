"""OCR lokal lewat Vision framework macOS: gratis, tanpa jaringan, sekitar 0,5 detik."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binance_bot.exceptions import ScreenReadError


@dataclass(frozen=True, slots=True)
class TextLine:
    """Satu baris teks hasil OCR. `x`, `y` = titik tengah, relatif 0..1 dari kiri-atas gambar."""

    text: str
    x: float
    y: float
    width: float = 0.0  # lebar relatif; dipakai bila OCR menggabungkan beberapa kata


class TextReader(Protocol):
    def read_lines(self, image: Path) -> list[TextLine]: ...


class MacTextReader:
    def read_lines(self, image: Path) -> list[TextLine]:
        import Vision
        from Foundation import NSURL

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        # Nama koin bukan kata kamus; koreksi bahasa justru bisa mengubahnya.
        request.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(str(image)), {}
        )
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise ScreenReadError(f"OCR gagal membaca {image.name}: {error}")

        lines = []
        for obs in request.results() or []:
            box = obs.boundingBox()  # relatif 0..1, titik asal di kiri-bawah
            lines.append(
                TextLine(
                    text=obs.topCandidates_(1)[0].string(),
                    x=box.origin.x + box.size.width / 2,
                    y=1.0 - (box.origin.y + box.size.height / 2),
                    width=box.size.width,
                )
            )
        return sorted(lines, key=lambda line: (line.y, line.x))
