"""Tebbit di Windows: profil layout (relatif isi halaman), zoom menurut skala layar, OCR."""

import sys
from pathlib import Path

import pytest
from PIL import Image

from binance_bot.exceptions import ScreenReadError
from binance_bot.macos.window import Rect
from binance_bot.tebbit_web import layout_tebbit as mac_layout
from binance_bot.tebbit_web.chrome import ChromeController
from binance_bot.tebbit_web.navigator import _legend_periods
from binance_bot.tebbit_web.screen_text import (
    parse_gainer_rows,
    parse_header,
    parse_margin,
    parse_order_book,
)
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


def test_header_reads_a_percent_that_ocr_turned_into_zero_slash_zero() -> None:
    assert parse_header(["SOXSUSDT", "44.45 +16.330/0", "Perpetual"]) == (44.45, 16.33)


def test_header_reads_a_decimal_point_that_ocr_turned_into_an_underscore() -> None:
    assert parse_header(["0_15320 +9.970/0"]) == (0.1532, 9.97)


def test_order_book_reads_prices_whose_decimal_point_became_an_underscore() -> None:
    area = (0.668, 0.19, 0.826, 0.91)
    lines = [
        TextLine("0_022495", 0.1, 0.2),
        TextLine("0_022494", 0.1, 0.3),
        TextLine("Mark Price: 0.022470", 0.2, 0.5),
        TextLine("0_022468", 0.1, 0.7),
        TextLine("0_022467", 0.1, 0.8),
    ]
    assert parse_order_book(lines, area) == (0.022468, 0.022494)
    with pytest.raises(ScreenReadError, match="kosong"):
        parse_order_book([TextLine("Mark Price: 0.022470", 0.2, 0.5)], area)


@pytest.mark.parametrize(
    ("legend", "periods"),
    [
        ("MA 5 close 0 2.63 MA 10 close 0 2.65 MA 30 close 0 2.49", {5, 10, 30}),
        ("MA 5 closeo 0.0215 MA 10c10seo 0.0218 'M 30 closeo 0.0206", {5, 10, 30}),
        ("MA 5 close 0 2.63 MA 10 close 0 2.65", {5, 10}),
        ("MA 5 closeo 11.923 BAIOc10seo 11.870 MA 30c10seo 11.777", {5, 10, 30}),
        ("MA 5 closeo 11.923 MAIOc10seO 11.870 MA 30c10seo 11.777", {5, 10, 30}),
        ("MA 5 close 0 17.06 mA10 close 0 17.12 BRA 30 close 0 17.11", {5, 10, 30}),
        ("MA 5 close 0 0.08588 IO close 0 0.08638 mA 30 close 0 0.08515", {5, 10, 30}),
        ("mA5closeO 17.06 MAIO closeo 17.12 mA30 closeo 17.11", {5, 10, 30}),
    ],
)
def test_legend_periods_survive_ocr_garbling(legend: str, periods: set[int]) -> None:
    assert _legend_periods(legend) >= periods


def test_header_price_without_a_decimal_point_still_gives_the_change() -> None:
    _, change = parse_header(["SOXSUSDT", "4454 +16.17%", "Perpetual"])
    assert change == 16.17


@pytest.mark.parametrize(
    ("texts", "isolated", "leverage"),
    [
        (["Cross-Merge", "sox"], False, 50),  # kasus nyata: "50X" terbaca "sox"
        (["Isolated\u00b7Merge", "2X"], True, 2),
        (["Cross\u00b7Merge  75X"], False, 75),
        (["Isolated-Merge", "ZX"], True, 2),
        (["Cross-Merge", "l50x"], False, 150),
    ],
)
def test_margin_panel_survives_ocr_turning_digits_into_letters(
    texts: list[str], isolated: bool, leverage: int
) -> None:
    settings = parse_margin(texts)
    assert (settings.isolated, settings.leverage) == (isolated, leverage)


def test_margin_panel_without_any_leverage_is_still_refused() -> None:
    with pytest.raises(ScreenReadError, match="Leverage tidak terbaca"):
        parse_margin(["Cross-Merge", "Merge"])
