"""OCR lokal lewat Windows.Media.Ocr (bawaan Windows 10/11, gratis, tanpa jaringan).

Memakai bahasa OCR dari daftar bahasa profil Windows. Teks Binance yang dibaca bot (nama pair,
angka, persen) berhuruf Latin, jadi paket OCR bahasa Inggris atau Indonesia sama-sama cukup.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from binance_bot.exceptions import ScreenReadError
from binance_bot.macos.ocr import TextLine

# Windows menggabungkan satu baris visual menjadi satu "line" walau antar-kolom berjauhan.
# Vision di macOS memisahkannya; jeda lebih lebar dari ini (kali tinggi huruf) dipotong.
_COLUMN_GAP_FACTOR = 1.5

_Word = tuple[str, float, float, float, float]  # teks, x, y, lebar, tinggi (piksel)


def _segment_line(words: list[_Word]) -> list[list[_Word]]:
    """Pecah satu baris OCR menjadi segmen terpisah di tiap jeda kolom yang lebar."""
    segments: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: w[1]):
        if segments:
            prev = segments[-1][-1]
            if word[1] - (prev[1] + prev[3]) <= _COLUMN_GAP_FACTOR * max(word[4], prev[4]):
                segments[-1].append(word)
                continue
        segments.append([word])
    return segments


def _to_text_line(segment: list[_Word], width: float, height: float) -> TextLine:
    left = min(w[1] for w in segment)
    right = max(w[1] + w[3] for w in segment)
    top = min(w[2] for w in segment)
    bottom = max(w[2] + w[4] for w in segment)
    return TextLine(
        text=" ".join(w[0] for w in segment),
        x=(left + right) / 2 / width,
        y=(top + bottom) / 2 / height,
    )


async def _recognize(image: Path) -> list[TextLine]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile

    file = await StorageFile.get_file_from_path_async(str(image.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise ScreenReadError(
            "Paket OCR Windows belum terpasang. Settings > Time & language > Language & region: "
            "tambahkan bahasa (English/Indonesia) dengan fitur OCR."
        )
    result = await engine.recognize_async(bitmap)

    lines: list[TextLine] = []
    for line in result.lines:
        words: list[_Word] = [
            (
                w.text,
                w.bounding_rect.x,
                w.bounding_rect.y,
                w.bounding_rect.width,
                w.bounding_rect.height,
            )
            for w in line.words
        ]
        for segment in _segment_line(words):
            lines.append(_to_text_line(segment, bitmap.pixel_width, bitmap.pixel_height))
    return sorted(lines, key=lambda item: (item.y, item.x))


class WinTextReader:
    def read_lines(self, image: Path) -> list[TextLine]:
        try:
            return asyncio.run(_recognize(image))
        except ScreenReadError:
            raise
        except Exception as exc:  # winrt melempar OSError/RuntimeError beragam
            raise ScreenReadError(f"OCR gagal membaca {image.name}: {exc}") from exc
