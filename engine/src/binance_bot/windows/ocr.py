"""OCR lokal lewat Windows.Media.Ocr (bawaan Windows 10/11, gratis, tanpa jaringan).

Memakai bahasa OCR dari daftar bahasa profil Windows. Teks Binance yang dibaca bot (nama pair,
angka, persen) berhuruf Latin, jadi paket OCR bahasa Inggris atau Indonesia sama-sama cukup.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from binance_bot.exceptions import ScreenReadError
from binance_bot.macos.ocr import TextLine

# Windows menggabungkan satu baris visual menjadi satu "line" walau antar-kolom berjauhan.
# Vision di macOS memisahkannya; jeda lebih lebar dari ini (kali tinggi huruf) dipotong.
_COLUMN_GAP_FACTOR = 1.5
# Kata dengan pusat vertikal berjarak kurang dari ini (kali tinggi huruf) satu baris visual.
_ROW_TOLERANCE = 0.4
# Windows OCR gagal membaca potongan kecil (mis. tombol "Cross"/"20x" setinggi 38 px). Potongan
# yang lebih pendek dari ini diperbesar dulu; koordinat hasil OCR tetap relatif (0..1).
_MIN_OCR_HEIGHT = 220
_MAX_UPSCALE = 6

_Word = tuple[str, float, float, float, float]  # teks, x, y, lebar, tinggi (piksel)


def _group_rows(words: list[_Word]) -> list[list[_Word]]:
    """Kelompokkan kata dari seluruh baris OCR menurut baris visualnya.

    Windows sering memecah teks berbeda gaya pada satu baris visual (mis. "BTCUSDT" tebal dan
    "Perpetual" tipis) menjadi dua "line"; Vision di macOS menggabungkannya. Kata yang pusat
    vertikalnya hampir sama dianggap satu baris.
    """
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: w[2] + w[4] / 2):
        center = word[2] + word[4] / 2
        if rows:
            last = rows[-1]
            row_center = sum(w[2] + w[4] / 2 for w in last) / len(last)
            row_height = max(w[4] for w in last)
            if abs(center - row_center) <= _ROW_TOLERANCE * max(row_height, word[4]):
                last.append(word)
                continue
        rows.append([word])
    return rows


def _segment_line(words: list[_Word]) -> list[list[_Word]]:
    """Pecah satu baris visual menjadi segmen terpisah di tiap jeda kolom yang lebar."""
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
        width=(right - left) / width,
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

    words: list[_Word] = [
        (
            w.text,
            w.bounding_rect.x,
            w.bounding_rect.y,
            w.bounding_rect.width,
            w.bounding_rect.height,
        )
        for line in result.lines
        for w in line.words
    ]
    lines: list[TextLine] = []
    for row in _group_rows(words):
        for segment in _segment_line(row):
            lines.append(_to_text_line(segment, bitmap.pixel_width, bitmap.pixel_height))
    return sorted(lines, key=lambda item: (item.y, item.x))


def _variants(image: Path, directory: Path) -> list[Path]:
    """Gambar untuk di-OCR. Potongan pendek diperbesar dengan beberapa cara (OCR Windows goyah
    pada teks kecil: angka yang sama bisa terbaca beda antar skala), selain itu aslinya saja."""
    from PIL import Image, ImageOps

    with Image.open(image) as source:
        factor = min(_MAX_UPSCALE, -(-_MIN_OCR_HEIGHT // source.height))
        if factor <= 1:
            return [image]
        gray = source.convert("L")
        paths: list[Path] = []
        for scale in dict.fromkeys((factor, max(2, factor // 2))):
            big = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
            for mode, candidate in (("g", big), ("i", ImageOps.invert(big))):
                target = directory / f"ocr_{mode}{scale}.png"
                candidate.save(target)
                paths.append(target)
        return paths


def _merge(results: list[list[TextLine]]) -> list[TextLine]:
    """Gabungkan hasil beberapa varian: teks yang sama hanya dihitung sekali."""
    seen: set[str] = set()
    merged: list[TextLine] = []
    for lines in results:
        for line in lines:
            if line.text not in seen:
                seen.add(line.text)
                merged.append(line)
    return sorted(merged, key=lambda item: (item.y, item.x))


class WinTextReader:
    def read_lines(self, image: Path) -> list[TextLine]:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = _variants(image, Path(tmp))
                return _merge([asyncio.run(_recognize(path)) for path in paths])
        except ScreenReadError:
            raise
        except Exception as exc:  # winrt melempar OSError/RuntimeError beragam
            raise ScreenReadError(f"OCR gagal membaca {image.name}: {exc}") from exc
