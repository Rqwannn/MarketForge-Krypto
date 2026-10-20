"""Deteksi tombol Beli/Long (hijau) dan Jual/Short (merah) lewat warna.

Kasus nyata: lewat OCR saja, tombol Jual/Short hanya ketemu di 7 dari 33 foto layar Full HD; lewat
warna ketemu di semua foto yang tombolnya tampil (54 dari 54, termasuk halaman berbanner dan layar
1366x768). Foto tidak masuk repo, jadi tes memakai gambar buatan dengan warna yang sama.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from binance_bot.binance_desktop import BinanceNavigator, layout
from binance_bot.binance_desktop.order_buttons import find_boxes, find_pair
from binance_bot.config import Settings
from binance_bot.exceptions import SafetyError, ScreenReadError
from binance_bot.macos import Rect, TextLine
from fakes import WINDOW, Clock, FakeApps, FakeScreen

BACKGROUND = (24, 26, 32)
GREEN = (46, 189, 133)  # warna asli tombol Beli/Long di Binance Desktop
RED = (246, 70, 93)  # warna asli tombol Jual/Short
WHITE = (255, 255, 255)


def form_image(
    width: int = 384,
    height: int = 300,
    *,
    left: tuple[int, int, int] | None = GREEN,
    right: tuple[int, int, int] | None = RED,
    y: int = 120,
) -> Image.Image:
    """Form buatan: dua tombol sebaris (164x48 piksel seperti di Full HD) dengan teks putih."""
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    if left is not None:
        draw.rectangle((8, y, 171, y + 47), fill=left)
        draw.text((50, y + 18), "Beli/Long", fill=WHITE)
    if right is not None:
        draw.rectangle((181, y, 344, y + 47), fill=right)
        draw.text((220, y + 18), "Jual/Short", fill=WHITE)
    return image


def test_the_green_and_red_buttons_are_found_as_a_pair_left_to_right() -> None:
    pair = find_pair(form_image())
    assert pair is not None
    assert (pair.left.kind, pair.right.kind) == ("hijau", "merah")
    assert abs(pair.left.center[0] - 90) <= 4 and abs(pair.right.center[0] - 263) <= 4
    assert abs(pair.left.center[1] - 144) <= 4 and pair.left.center[1] == pair.right.center[1]


def test_tiny_colored_specks_are_not_buttons() -> None:
    image = form_image()
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 25, 22), fill=GREEN)  # serpihan hijau 6x3
    draw.rectangle((300, 20, 305, 22), fill=RED)  # serpihan merah di baris yang sama
    assert len(find_boxes(image)) == 2
    pair = find_pair(image)
    assert pair is not None and pair.left.width > 100


def test_a_logged_out_form_has_no_order_buttons() -> None:
    """Uji nyata: saat belum login form hanya punya tombol kuning "Daftar" dan abu-abu "Masuk"."""
    image = form_image(left=(252, 213, 53), right=(43, 49, 57))
    assert find_pair(image) is None


@pytest.mark.parametrize(
    "image",
    [
        form_image(right=None),  # hanya hijau
        form_image(left=None),  # hanya merah
        form_image(left=GREEN, right=GREEN),  # dua warna sama bukan pasangan Long/Short
    ],
)
def test_a_pair_needs_one_green_and_one_red_button(image: Image.Image) -> None:
    assert find_pair(image) is None


def test_buttons_on_different_rows_or_sizes_are_not_a_pair() -> None:
    image = form_image()
    draw = ImageDraw.Draw(image)
    draw.rectangle((181, 120, 344, 167), fill=BACKGROUND)  # hapus tombol merah
    draw.rectangle((181, 220, 344, 267), fill=RED)  # merah di baris lain
    assert find_pair(image) is None
    small = form_image()
    draw = ImageDraw.Draw(small)
    draw.rectangle((181, 120, 344, 167), fill=BACKGROUND)
    draw.rectangle((181, 130, 260, 150), fill=RED)  # merah jauh lebih kecil
    assert find_pair(small) is None


def test_swapped_colors_still_pair_but_the_text_decides() -> None:
    """Skema warna dibalik (merah di kiri): persegi tetap ditemukan, teksnya yang menentukan."""
    pair = find_pair(form_image(left=RED, right=GREEN))
    assert pair is not None and (pair.left.kind, pair.right.kind) == ("merah", "hijau")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("Beli/Long", "Jual/Short", True),
        ("", "Jual/Short", True),  # kanan terbaca Short
        ("Beli/Long", "", True),  # kiri terbaca Long: yang kanan pasti Short
        ("Beli Long", "Jual Short", True),
        ("Jual/Short", "Beli/Long", False),  # tertukar
        ("", "Beli/Long", False),  # kanan Long
        ("Jual/Short", "", False),  # kiri Short
        ("Beli/Long", "Beli/Long", False),
        ("", "", False),  # tak ada bukti teks: tidak dipakai
        ("xx", "yy", False),
    ],
)
def test_the_text_must_confirm_which_button_is_short(left: str, right: str, expected: bool) -> None:
    assert BinanceNavigator._pair_is_long_short(left, right) is expected


# ------------------------------------------------------------------ lewat navigator


class ImageScreen(FakeScreen):
    """Jendela tiruan yang memotong gambar jendela buatan (bukan hanya mencatat area)."""

    def __init__(self, window_image: Image.Image, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.window_image = window_image

    def capture(self, rect: Rect, path: Path) -> None:
        super().capture(rect, path)
        left, top = rect.x - WINDOW.x, rect.y - WINDOW.y
        self.window_image.crop((left, top, left + rect.width, top + rect.height)).save(path)


def window_with_buttons(zone: tuple[float, float, float, float]) -> tuple[Image.Image, tuple]:
    """Gambar jendela dengan dua tombol di dalam zona form; mengembalikan juga kotaknya (piksel)."""
    image = Image.new("RGB", (WINDOW.width, WINDOW.height), BACKGROUND)
    x0, y0, x1, y1 = zone
    zone_w, zone_h = (x1 - x0) * WINDOW.width, (y1 - y0) * WINDOW.height
    box_w, box_h = int(zone_w * 0.43), int(zone_h * 0.2)
    top = int(y0 * WINDOW.height + zone_h * 0.4)
    left_x = int(x0 * WINDOW.width + zone_w * 0.03)
    right_x = left_x + box_w + int(zone_w * 0.04)
    draw = ImageDraw.Draw(image)
    draw.rectangle((left_x, top, left_x + box_w, top + box_h), fill=GREEN)
    draw.rectangle((right_x, top, right_x + box_w, top + box_h), fill=RED)
    return image, (
        (left_x, top, left_x + box_w, top + box_h),
        (right_x, top, right_x + box_w, top + box_h),
    )


def order_nav(
    monkeypatch: pytest.MonkeyPatch, *, texts: tuple[str, str] = ("Beli/Long", "Jual/Short")
) -> tuple[BinanceNavigator, tuple]:
    probe = BinanceNavigator(
        Settings(settle_delay_s=0),
        FakeApps(),
        FakeScreen(),
        FakeScreen(),
        sleep=Clock().sleep,
        clock=Clock(),
        screens=lambda: [WINDOW],
    )
    zone = probe._order_form_zones()[0]
    image, boxes = window_with_buttons(zone)
    screen = ImageScreen(image)
    nav = BinanceNavigator(
        Settings(settle_delay_s=0),
        FakeApps(),
        screen,
        screen,
        sleep=Clock().sleep,
        clock=Clock(),
        screens=lambda: [WINDOW],
    )
    nav._rect, nav._on_trade_page = WINDOW, True
    monkeypatch.setattr(nav, "_ensure_front", lambda: None)
    by_side = {"kiri": texts[0], "kanan": texts[1]}
    monkeypatch.setattr(
        nav,
        "_button_text",
        lambda image, box, path: by_side["kiri" if path.name == "kiri.png" else "kanan"],
    )
    return nav, boxes


def inside(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y = WINDOW.point_at(*point)
    return box[0] <= x - WINDOW.x <= box[2] and box[1] <= y - WINDOW.y <= box[3]


def test_short_and_long_buttons_are_located_by_color_inside_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav, (long_box, short_box) = order_nav(monkeypatch)
    assert inside(nav.short_button(), short_box)
    assert inside(nav.long_button(), long_box)


def test_the_short_button_is_never_the_long_one(monkeypatch: pytest.MonkeyPatch) -> None:
    nav, (long_box, _short_box) = order_nav(monkeypatch)
    short = nav.short_button()
    assert not inside(short, long_box) and nav.long_button()[0] < short[0]


def test_swapped_texts_are_refused_and_nothing_is_clicked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kanan terbaca Long (skema tertukar atau salah pasang): tidak ada tombol yang dikembalikan."""
    nav, _ = order_nav(monkeypatch, texts=("Jual/Short", "Beli/Long"))
    with pytest.raises(ScreenReadError):
        nav.short_button()


def test_without_colored_buttons_the_text_search_is_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav, _ = order_nav(monkeypatch)
    zone = nav._order_form_zones()[0]
    nav._window.window_image = Image.new("RGB", (WINDOW.width, WINDOW.height), BACKGROUND)  # type: ignore[attr-defined]
    nav._window._texts[WINDOW.sub(*zone)] = [[TextLine("Jual/Short", 0.9, 0.5)]]  # type: ignore[attr-defined]
    x, y = nav.short_button()
    x0, y0, x1, y1 = zone
    assert x == pytest.approx(x0 + 0.9 * (x1 - x0)) and y == pytest.approx(y0 + 0.5 * (y1 - y0))


def test_tebbit_keeps_the_text_search_only() -> None:
    from binance_bot.tebbit_web.navigator import TebbitNavigator

    assert BinanceNavigator._COLOR_BUTTONS is True
    assert TebbitNavigator._COLOR_BUTTONS is False
    assert layout.ORDER_BUTTON_ZONES  # zona terlarang tetap melindungi tombol order


def test_clicks_on_visible_order_buttons_are_refused_even_outside_the_fixed_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uji nyata (20 Okt 10.14): halaman koin bergeser naik, Jual/Short tampil di y 0,32, di luar
    zona tetap dan tepat di tempat kolom Jumlah biasanya. Klik ke tombol itu tetap ditolak."""
    image, (long_box, short_box) = window_with_buttons((0.80, 0.25, 1.0, 0.40))
    screen = ImageScreen(image)
    nav = BinanceNavigator(
        Settings(settle_delay_s=0),
        FakeApps(),
        screen,
        screen,
        sleep=Clock().sleep,
        clock=Clock(),
        screens=lambda: [WINDOW],
    )
    nav._rect, nav._on_trade_page = WINDOW, True
    monkeypatch.setattr(nav, "_ensure_front", lambda: None)
    for box in (long_box, short_box):
        cx, cy = (box[0] + box[2]) / 2 / WINDOW.width, (box[1] + box[3]) / 2 / WINDOW.height
        assert not layout.in_order_button_zone((cx, cy))  # zona tetap tidak mencakupnya
        with pytest.raises(SafetyError):
            nav._click((cx, cy))
    assert not any(kind == "click" for kind, _ in screen.events)
    nav._click((0.85, 0.20))  # titik lain di kolom form (di luar tombol) tetap boleh
