"""Mencari tombol Beli/Long dan Jual/Short di form order lewat warna pekatnya.

OCR membaca teks putih di atas warna pekat dengan buruk: tombol Jual/Short hanya ketemu di 7 dari 33
foto layar Full HD. Warna tombolnya justru stabil di semua resolusi dan di halaman berbanner: dua
persegi panjang pekat (hijau dan merah) berdampingan di satu baris. Modul ini hanya mencari kedua
persegi itu; navigator lalu membaca teksnya untuk memastikan yang kanan benar-benar "Jual/Short".

Hanya memakai Pillow (tanpa numpy), dan hanya membaca gambar: tidak ada yang diklik di sini.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import product

from PIL import Image, ImageChops

# Persegi dipindai pada petak 2x2 piksel agar cepat (gambar form sekitar 400x350 piksel).
_STEP = 2
_MIN_WIDTH = 0.2  # lebar minimum tombol, pecahan lebar gambar (tombol asli sekitar 0,42)
_MIN_FILL = 0.75  # bagian persegi yang berwarna pekat (teks putih melubanginya)
_ASPECT = (2.0, 6.5)  # lebar / tinggi tombol (asli sekitar 3,4)
_SAME_ROW = 0.35  # selisih tinggi tengah dua tombol, pecahan tinggi tombol
_SAME_SIZE = 0.25  # selisih ukuran dua tombol, pecahan ukuran terbesar
_MAX_GAP = 0.5  # jarak antartombol, pecahan lebar tombol (asli sekitar 0,06)


@dataclass(frozen=True, slots=True)
class Box:
    kind: str  # "hijau" atau "merah"
    x0: int
    y0: int
    x1: int  # eksklusif
    y1: int  # eksklusif

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2


@dataclass(frozen=True, slots=True)
class ButtonPair:
    """Dua tombol sebaris: `left` = Beli/Long, `right` = Jual/Short (urutan tetap di Binance)."""

    left: Box
    right: Box


def _kind(r: int, g: int, b: int) -> str | None:
    """Merah tombol Jual/Short (sekitar 246,70,93) atau hijau Beli/Long (sekitar 46,189,133)."""
    if r >= 170 and g <= 140 and r - g >= 90 and r - b >= 60:
        return "merah"
    if g >= 120 and r <= 130 and g - r >= 50 and g - b >= 20:
        return "hijau"
    return None


def find_boxes(image: Image.Image) -> list[Box]:
    """Persegi panjang pekat hijau atau merah yang cukup besar, dalam piksel gambar."""
    rgb = image.convert("RGB")
    small = rgb.reduce(_STEP)
    width, height = small.size
    pixels = small.load()
    assert pixels is not None
    grid = [[_kind(*pixels[x, y]) for x in range(width)] for y in range(height)]  # type: ignore[misc]
    seen = [[False] * width for _ in range(height)]
    boxes: list[Box] = []
    for y, x in product(range(height), range(width)):
        kind = grid[y][x]
        if kind is None or seen[y][x]:
            continue
        queue = deque([(x, y)])
        seen[y][x] = True
        count = 0
        left, right, top, bottom = x, x, y, y
        while queue:
            cx, cy = queue.popleft()
            count += 1
            left, right = min(left, cx), max(right, cx)
            top, bottom = min(top, cy), max(bottom, cy)
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (
                    0 <= nx < width
                    and 0 <= ny < height
                    and not seen[ny][nx]
                    and grid[ny][nx] == kind
                ):
                    seen[ny][nx] = True
                    queue.append((nx, ny))
        box_w, box_h = right - left + 1, bottom - top + 1
        if (
            box_w * _STEP >= _MIN_WIDTH * rgb.width
            and count / (box_w * box_h) >= _MIN_FILL
            and _ASPECT[0] <= box_w / box_h <= _ASPECT[1]
        ):
            boxes.append(
                Box(kind, left * _STEP, top * _STEP, (right + 1) * _STEP, (bottom + 1) * _STEP)
            )
    return boxes


def find_pair(image: Image.Image) -> ButtonPair | None:
    """Pasangan tombol terbesar: dua warna berbeda, satu baris, ukuran mirip, bersebelahan."""
    best: tuple[int, ButtonPair] | None = None
    boxes = find_boxes(image)
    for a, b in product(boxes, boxes):
        if a.kind == b.kind or a.x0 >= b.x0:
            continue
        tall = max(a.height, b.height)
        wide = max(a.width, b.width)
        if abs(a.center[1] - b.center[1]) > _SAME_ROW * tall:
            continue
        if (
            abs(a.width - b.width) > _SAME_SIZE * wide
            or abs(a.height - b.height) > _SAME_SIZE * tall
        ):
            continue
        if b.x0 - a.x1 > _MAX_GAP * wide:
            continue
        area = a.width * a.height
        if best is None or area > best[0]:
            best = (area, ButtonPair(a, b))
    return best[1] if best else None


def text_image(image: Image.Image, box: Box, factor: int = 3) -> Image.Image:
    """Isi tombol sebagai gambar abu-abu untuk OCR.

    Kanal minimum (R, G, B) membuat teks putih tetap terang sedangkan warna pekat tombol jadi gelap:
    kontras tinggi di tombol merah maupun hijau, di Full HD maupun 1366x768.
    """
    crop = image.convert("RGB").crop((box.x0, box.y0, box.x1, box.y1))
    red, green, blue = crop.split()
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    return darkest.resize(
        (darkest.width * factor, darkest.height * factor), Image.Resampling.LANCZOS
    )
