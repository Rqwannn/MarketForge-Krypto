"""Tebbit di Windows: profil layout (relatif isi halaman), zoom menurut skala layar, OCR."""

import sys
from pathlib import Path

import pytest
from PIL import Image

from binance_bot.macos.window import Rect
from binance_bot.tebbit_web import layout_tebbit as mac_layout
from binance_bot.tebbit_web.chrome import ChromeController
from binance_bot.tebbit_web.screen_text import parse_gainer_rows
from fakes import TextLine

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="khusus Windows")


@windows_only
def test_windows_profile_keeps_order_buttons_forbidden_and_quantity_reachable() -> None:
    from binance_bot.tebbit_web import layout_tebbit_windows as win

    def forbidden(point: tuple[float, float]) -> bool:
        return mac_layout.in_zone(point, win.ALWAYS_FORBIDDEN + win.CONTRACT_FORBIDDEN)

    # Diukur dari halaman koin: slider 0,36, Buy/Long 0,50, Sell/Short 0,63, Transfer 0,83.
    for point in [(0.85, 0.36), (0.89, 0.50), (0.915, 0.63), (0.90, 0.83), (0.5, 0.95)]:
        assert forbidden(point), point
    assert forbidden((0.5, 0.04))  # menu atas situs (akun)
    # Tab Market (y 0,177) dan kolom Quantity (y 0,305) harus bisa diklik.
    assert not forbidden((0.886, 0.177))
    assert not forbidden((win.QTY_CLICK_X, 0.305))
    assert not forbidden((0.5, 0.5))  # grafik


@windows_only
def test_windows_profile_areas_are_inside_the_page() -> None:
    from binance_bot.tebbit_web import layout_tebbit_windows as win

    areas = [
        win.NAV_FUTURES_AREA, win.LOGIN_AREA, win.LIST_SEARCH_AREA, win.LIST_ROWS_AREA,
        win.HEADER_AREA, win.TIMEFRAME_AREA, win.LEGEND_AREA, win.CHART_AREA,
        win.ORDERBOOK_AREA, win.MARGIN_AREA, win.ORDER_TAB_AREA, win.ORDER_FORM_AREA,
    ]  # fmt: skip
    for x0, y0, x1, y1 in areas:
        assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0


@windows_only
@pytest.mark.parametrize(("scale", "steps"), [(1.0, 0), (1.25, 2), (1.5, 4), (2.0, 5)])
def test_zoom_follows_the_display_scale(scale: float, steps: int) -> None:
    from binance_bot.tebbit_web import layout_tebbit_windows as win

    assert win.zoom_steps_down(scale) == steps  # zoom x skala tampilan mendekati 1,0


@windows_only
def test_a_short_wide_crop_is_not_upscaled_past_the_ocr_limit(tmp_path: Path) -> None:
    from binance_bot.windows import ocr

    Image.new("RGB", (3800, 70)).save(tmp_path / "wide.png")
    for path in ocr._variants(tmp_path / "wide.png", tmp_path):
        with Image.open(path) as image:
            assert max(image.size) <= 10000


def test_percent_read_as_zero_slash_zero_is_still_a_percent() -> None:
    area = (0.05, 0.45, 0.90, 0.99)
    name_x = (0.25 - area[0]) / (area[2] - area[0])
    pct_x = (0.70 - area[0]) / (area[2] - area[0])
    lines = [
        TextLine("TRUTHUSDT", name_x, 0.2),
        TextLine("+9.560/0", pct_x, 0.2),
        TextLine("BTWUSDT", name_x, 0.4),
        TextLine("+8.99%", pct_x, 0.4),
    ]
    rows = parse_gainer_rows(lines, area)
    assert [(r.symbol, r.change_pct) for r, _ in rows] == [("TRUTHUSDT", 9.56), ("BTWUSDT", 8.99)]


def test_mac_chrome_content_is_the_whole_window() -> None:
    chrome = ChromeController(runner=lambda command: "10, 20, 1480, 883")
    assert chrome.content_bounds(1) == chrome.bounds(1) == Rect(10, 20, 1470, 863)
