from pathlib import Path

import pytest

from binance_bot.binance_desktop import BinanceNavigator, layout
from binance_bot.config import Settings
from binance_bot.exceptions import (
    AppNotRunningError,
    AppTimeoutError,
    SafetyError,
    ScreenReadError,
    WindowError,
)
from binance_bot.macos import Rect, TextLine
from fakes import AREA, BUNDLE, WINDOW, Clock, FakeApps, FakeScreen, list_lines, text_lines

ASCENDING = list_lines((1, "USUSDT", "-32.21%"), (2, "JCTUSDT", "-30.04%"))
DESCENDING = list_lines(
    (1, "LUMIAUSDT", "+53.55%"), (2, "STRKUSDT", "+53.14%"), (3, "CFXUSDT", "+34.62%")
)


def make_nav(
    screen: FakeScreen | None = None,
    apps: FakeApps | None = None,
    areas: list[Rect] | None = None,
) -> BinanceNavigator:
    screen = screen or FakeScreen()
    clock = Clock()  # jam tiruan: menunggu berjalan instan
    return BinanceNavigator(
        Settings(settle_delay_s=0),
        apps or FakeApps(),
        screen,
        screen,
        sleep=clock.sleep,
        clock=clock,
        screens=lambda: areas or [AREA],
    )


def at(target: tuple[float, float]) -> tuple[int, int]:
    return WINDOW.point_at(*target)


def clicks(screen: FakeScreen) -> list[object]:
    return [where for kind, where in screen.events if kind == "click"]


class FocusStuckApps(FakeApps):
    """Aplikasi lain (jendela notifikasi Windows) memegang fokus sampai ada klik di jendela."""

    def __init__(self, screen: FakeScreen) -> None:
        super().__init__()
        self._screen = screen

    def frontmost_bundle_id(self) -> str | None:
        clicked = any(kind == "click" for kind, _ in self._screen.events)
        return BUNDLE if clicked else "ShellExperienceHost.exe"


def test_prepare_clicks_the_empty_title_bar_when_focus_will_not_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Uji nyata (04.45): jendela notifikasi Windows memegang fokus, putaran gagal di awal.
    monkeypatch.setattr(layout, "FOCUS_POINT", (0.25, 0.0216))
    screen = FakeScreen()
    nav = make_nav(screen, FocusStuckApps(screen))
    nav.prepare()
    assert clicks(screen) == [WINDOW.point_at(0.25, 0.0216)]


def test_ensure_front_clicks_the_empty_title_bar_after_two_failed_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(layout, "FOCUS_POINT", (0.25, 0.0216))
    screen = FakeScreen()
    apps = FocusStuckApps(screen)
    nav = make_nav(screen, apps)
    nav._rect = WINDOW
    nav._ensure_front()
    assert clicks(screen) == [WINDOW.point_at(0.25, 0.0216)]
    assert len(apps.launched) == 3  # dua usaha biasa gagal, klik, usaha ketiga berhasil


def test_focus_that_never_returns_is_still_an_error_after_one_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NeverFront(FakeApps):
        def frontmost_bundle_id(self) -> str | None:
            return "ShellExperienceHost.exe"

    monkeypatch.setattr(layout, "FOCUS_POINT", (0.25, 0.0216))
    screen = FakeScreen()
    nav = make_nav(screen, NeverFront())
    nav._rect = WINDOW
    with pytest.raises(AppTimeoutError):
        nav._ensure_front()
    assert len(clicks(screen)) == 1  # satu klik saja, bukan klik berulang


def test_no_title_bar_click_without_a_focus_point(monkeypatch: pytest.MonkeyPatch) -> None:
    class NeverFront(FakeApps):
        def frontmost_bundle_id(self) -> str | None:
            return "ShellExperienceHost.exe"

    monkeypatch.setattr(layout, "FOCUS_POINT", None)  # profil macOS
    screen = FakeScreen()
    nav = make_nav(screen, NeverFront())
    nav._rect = WINDOW
    with pytest.raises(AppTimeoutError):
        nav._ensure_front()
    assert clicks(screen) == []


def test_focus_point_is_an_empty_title_bar_spot_far_from_the_order_zones() -> None:
    from binance_bot.binance_desktop import layout_windows, layout_windows_1366

    for profile in (layout_windows, layout_windows_1366):
        x, y = profile.FOCUS_POINT
        _, height = profile.EXPECTED_WINDOW
        assert y * height < 45  # di dalam bilah judul (45 px)
        assert 0.2 < x < 0.34  # di antara tombol muat ulang dan kotak pencarian
        assert not any(
            x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in profile.ORDER_BUTTON_ZONES
        )


def test_prepare_refuses_when_binance_not_running() -> None:
    apps, screen = FakeApps(running=False), FakeScreen()
    with pytest.raises(AppNotRunningError):
        make_nav(screen, apps).prepare()
    assert apps.launched == []
    assert screen.events == []


def resizes(screen: FakeScreen) -> list[object]:
    return [where for kind, where in screen.events if kind == "set_bounds"]


def test_prepare_keeps_a_window_that_already_fits() -> None:
    screen = FakeScreen()
    make_nav(screen).prepare()
    assert resizes(screen) == []


def test_prepare_resizes_window_to_calibration_size_on_a_bigger_screen() -> None:
    # MacBook Pro 16": area 1728x1084; jendela Binance sedang 1200x700 di tengah layar.
    screen = FakeScreen(Rect(260, 200, 1200, 700))
    nav = make_nav(screen, areas=[Rect(0, 33, 1728, 1084)])
    nav.prepare()
    assert resizes(screen) == [Rect(0, 33, 1470, 859)]
    assert nav.rect == Rect(0, 33, 1470, 859)
    assert clicks(screen) == []


def test_prepare_moves_a_window_hanging_off_the_screen() -> None:
    screen = FakeScreen(Rect(400, 33, 1470, 859))  # ukuran benar, tapi sebagian di luar layar
    make_nav(screen).prepare()
    assert resizes(screen) == [Rect(0, 33, 1470, 859)]


def test_prepare_keeps_binance_on_the_screen_it_is_on() -> None:
    external = Rect(1470, 0, 1920, 1055)
    screen = FakeScreen(Rect(1600, 100, 1000, 600))
    make_nav(screen, areas=[AREA, external]).prepare()
    assert resizes(screen) == [Rect(1470, 0, 1470, 859)]


def test_prepare_stops_without_clicking_when_the_screen_is_too_small() -> None:
    # MacBook Air 13" M1 (1440x900): jendela 1470 point tidak muat.
    screen = FakeScreen(Rect(0, 25, 1440, 790))
    with pytest.raises(WindowError, match=r"terlalu kecil.*1440x790"):
        make_nav(screen, areas=[Rect(0, 25, 1440, 790)]).prepare()
    assert screen.events == []


def test_prepare_stops_when_the_window_cannot_be_resized() -> None:
    screen = FakeScreen(Rect(0, 0, 1470, 956), resizable=False)  # mis. mode layar penuh
    with pytest.raises(WindowError, match="layar penuh"):
        make_nav(screen).prepare()
    assert clicks(screen) == []


def test_navigation_before_prepare_is_an_error() -> None:
    with pytest.raises(WindowError, match="prepare"):
        make_nav().open_top_gainers()


def test_top_gainers_reclicks_header_until_sorted_by_highest_gain() -> None:
    screen = FakeScreen(texts={layout.FUTURES_LIST_AREA: [ASCENDING, DESCENDING]})
    nav = make_nav(screen)
    nav.prepare()

    rows = nav.open_top_gainers()

    assert [(r.rank, r.symbol, r.change_pct) for r in rows] == [
        (1, "LUMIAUSDT", 53.55),
        (2, "STRKUSDT", 53.14),
        (3, "CFXUSDT", 34.62),
    ]
    header = at(layout.FUTURES_CHANGE_HEADER)
    assert clicks(screen) == [
        at(layout.SIDEBAR_MARKET),
        at(layout.MARKET_FUTURES_TAB),
        header,
        header,
    ]


def test_top_gainers_gives_up_when_never_sorted() -> None:
    nav = make_nav(FakeScreen(texts={layout.FUTURES_LIST_AREA: [ASCENDING]}))
    nav.prepare()
    with pytest.raises(ScreenReadError, match="tidak terurut"):
        nav.open_top_gainers()


def test_open_gainer_clicks_row_icon_and_reads_pair_on_trade_page() -> None:
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [text_lines("≡ MBLUSDT Perpetual", "0,0181")]})
    nav = make_nav(screen)
    nav.prepare()
    assert nav.open_gainer(3) == "MBLUSDT"
    assert clicks(screen) == [at(layout.trade_icon(3))]


ACTION_AREA = (0.60, 0.20, 1.0, 0.80)  # judul kolom "Tindakan" di daftar Futures


def test_open_gainer_waits_for_a_trade_page_that_is_slow_to_load() -> None:
    # Uji nyata (BRUSDT): halaman koin baru separuh tampil saat pair pertama dibaca.
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [[], [], text_lines("BRUSDT Perpetual")]})
    nav = make_nav(screen)
    nav.prepare()
    assert nav.open_gainer(1) == "BRUSDT"
    assert clicks(screen) == [at(layout.trade_icon(1))]  # tanpa klik tambahan


def test_open_gainer_clicks_the_icon_again_when_the_click_was_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Uji nyata (NILUSDT): klik ikon "Perdagangkan" hilang, daftar Pasar tetap di layar.
    monkeypatch.setattr(layout, "FUTURES_ACTION_AREA", ACTION_AREA)
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [[], [], [], text_lines("NILUSDT Perpetual")],
            ACTION_AREA: [text_lines("Tindakan")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    assert nav.open_gainer(5) == "NILUSDT"
    icon = clicks(screen)[0]
    assert clicks(screen) == [icon, icon]


def test_open_gainer_does_not_click_again_when_the_list_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daftar tak terbukti tampil: klik ulang bisa mendarat di halaman koin, jadi tidak ada."""
    monkeypatch.setattr(layout, "FUTURES_ACTION_AREA", ACTION_AREA)
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [[]], ACTION_AREA: [[]]})
    nav = make_nav(screen)
    nav.prepare()
    with pytest.raises(ScreenReadError, match="Pair Futures tidak terbaca"):
        nav.open_gainer(2)
    assert len(clicks(screen)) == 1


def test_open_gainer_repeats_the_click_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "FUTURES_ACTION_AREA", ACTION_AREA)
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [[]], ACTION_AREA: [text_lines("Tindakan")]})
    nav = make_nav(screen)
    nav.prepare()
    with pytest.raises(ScreenReadError, match="Pair Futures tidak terbaca"):
        nav.open_gainer(1)
    assert len(clicks(screen)) == 2


def test_available_usdt_reads_an_empty_wallet_that_ocr_shows_with_letter_o() -> None:
    # Uji nyata (19 Okt 23.50): dompet Futures kosong, "0,00" terbaca "O,OO" lalu "tidak terbaca".
    screen = FakeScreen(texts={layout.ORDER_AVAILABLE_AREA: [text_lines("Tersedia O,OO USDT")]})
    nav = make_nav(screen)
    nav.prepare()
    assert nav.available_usdt() == 0.0


def test_rank_is_bounded() -> None:
    for bad in (0, layout.MAX_RANK + 1):
        with pytest.raises(ValueError):
            layout.trade_icon(bad)


def test_fill_quantity_types_number_and_verifies_it_on_screen() -> None:
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")],
            # sebelum mengetik: satuan USDT; sesudah mengetik: angkanya tampil
            layout.ORDER_QTY_AREA: [text_lines("USDT"), text_lines("100", "USDT")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    nav.fill_quantity("100")

    assert screen.events[-4:] == [
        ("click", at(layout.ORDER_TAB_MARKET)),
        ("click", at(layout.ORDER_QTY_FIELD)),
        ("clear", None),
        ("type", "100"),
    ]


@pytest.mark.parametrize(
    ("unit", "message"),
    [
        (text_lines("STRK"), "bukan USDT"),  # masih satuan koin
        (text_lines("Margin Awal", "USDT"), "Margin Awal"),  # USDT tapi mode margin
    ],
)
def test_fill_quantity_refuses_to_type_unless_unit_is_usdt_order_size(
    unit: list[TextLine], message: str
) -> None:
    screen = FakeScreen(
        texts={layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")], layout.ORDER_QTY_AREA: [unit]}
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    with pytest.raises(ScreenReadError, match=message):
        nav.fill_quantity("100")
    assert not any(kind in ("type", "clear") for kind, _ in screen.events)  # tidak mengetik apa pun


def test_fill_quantity_fails_when_screen_shows_another_number() -> None:
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")],
            layout.ORDER_QTY_AREA: [text_lines("USDT"), text_lines("1000", "USDT")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    with pytest.raises(ScreenReadError, match="1000"):
        nav.fill_quantity("100")


def test_fill_quantity_only_on_trade_page() -> None:
    nav = make_nav()
    nav.prepare()
    with pytest.raises(SafetyError):
        nav.fill_quantity("1")


def test_clicks_into_order_buttons_are_refused_on_trade_page() -> None:
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")]})
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    sell_short_market_tab = (1893 / 2000, 596 / 1167)
    before = list(screen.events)
    with pytest.raises(SafetyError):
        nav._click(sell_short_market_tab)
    assert screen.events == before


def test_order_buttons_are_inside_zones_and_navigation_targets_are_not() -> None:
    buttons = [
        (1893 / 2000, 596 / 1167),
        (1713 / 2000, 596 / 1167),
        (1887 / 2000, 735 / 1167),
        (498 / 2000, 485 / 1167),
        (200 / 2000, 485 / 1167),
    ]
    assert all(layout.in_order_button_zone(b) for b in buttons)
    trade_page_targets = [layout.TIMEFRAME_15M, layout.ORDER_TAB_MARKET, layout.ORDER_QTY_FIELD]
    assert not any(layout.in_order_button_zone(t) for t in trade_page_targets)


def test_capture_chart_uses_chart_area(tmp_path: Path) -> None:
    screen = FakeScreen()
    nav = make_nav(screen)
    nav.prepare()
    nav.capture_chart(tmp_path / "c.png")
    assert screen._last == WINDOW.sub(*layout.CHART_AREA)


def toolbar(*items: tuple[str, float, float], width: float = 0.0) -> list[TextLine]:
    """Teks pada CHART_TOOLBAR_AREA di posisi relatif jendela (x, y)."""
    x0, y0, x1, y1 = layout.CHART_TOOLBAR_AREA
    return [TextLine(t, (x - x0) / (x1 - x0), (y - y0) / (y1 - y0), width) for t, x, y in items]


def chart_area(shift: float = 0.0) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = layout.CHART_AREA
    return x0, y0 + shift, x1, y1 + shift


def trade_page_nav(
    lines: list[TextLine], shift: float = 0.0, chart: list[list[TextLine]] | None = None
) -> tuple[BinanceNavigator, FakeScreen]:
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("SUSDT Perpetual")],
            layout.CHART_TOOLBAR_AREA: [lines],
            chart_area(shift): chart or [text_lines("MA(7) 0,0610")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    return nav, screen


def test_15m_button_is_found_by_ocr_even_when_a_banner_shifts_the_page(tmp_path: Path) -> None:
    # Uji nyata: banner "project name of S is Sonic" menggeser halaman sekitar 0,04 ke bawah.
    shift = 0.04
    nav, screen = trade_page_nav(
        toolbar(("Grafik", 0.0715, 0.196 + shift), ("15 mnt", 0.1265, 0.2416 + shift)), shift
    )
    nav.show_15m_chart()
    assert clicks(screen)[-2:] == [WINDOW.point_at(0.0715, 0.236), WINDOW.point_at(0.1265, 0.2816)]

    nav.capture_chart(tmp_path / "c.png")
    x0, y0, x1, y1 = layout.CHART_AREA
    assert screen._last == WINDOW.sub(x0, y0 + shift, x1, y1 + shift)


def test_15m_button_inside_a_merged_ocr_line() -> None:
    text = "Waktu 1 dtk 15 mnt 1 Jam"
    nav, screen = trade_page_nav(toolbar((text, 0.15, 0.2416), width=0.3))
    nav.show_15m_chart()
    x, _ = clicks(screen)[-1]  # type: ignore[misc]
    expected_x, _ = WINDOW.point_at(*toolbar_x(text, "15 mnt", 0.15, 0.3), 0.2416)
    assert abs(x - expected_x) <= 1


def toolbar_x(text: str, word: str, center: float, width: float) -> tuple[float]:
    x0, _, x1, _ = layout.CHART_TOOLBAR_AREA
    start = text.index(word)
    rel_center, rel_width = (center - x0) / (x1 - x0), width
    rel = rel_center - rel_width / 2 + rel_width * (start + len(word) / 2) / len(text)
    return (x0 + rel * (x1 - x0),)


def test_missing_15m_button_is_an_error_not_a_blind_click() -> None:
    nav, screen = trade_page_nav(toolbar(("Minat Terbuka", 0.2, 0.25)))
    before = len(clicks(screen))
    with pytest.raises(ScreenReadError, match="15 mnt"):
        nav.show_15m_chart()
    assert len(clicks(screen)) == before


def test_15m_button_is_waited_for_while_the_trade_page_is_still_loading() -> None:
    # Uji nyata (BRUSDT): toolbar grafik belum tampil saat dicari, halaman baru separuh dimuat.
    ready = toolbar(("Grafik", 0.0715, 0.196), ("15 mnt", 0.1265, 0.2416))
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("BRUSDT Perpetual")],
            layout.CHART_TOOLBAR_AREA: [[], [], [], [], ready],
            chart_area(): [text_lines("MA(7) 0,0610")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    nav.show_15m_chart()
    assert clicks(screen)[-2:] == [at((0.0715, 0.196)), at((0.1265, 0.2416))]


def test_futures_tab_is_clicked_again_when_the_list_has_not_loaded() -> None:
    screen = FakeScreen(texts={layout.FUTURES_LIST_AREA: [[], DESCENDING]})
    nav = make_nav(screen)
    nav.prepare()
    assert nav.open_top_gainers()[0].symbol == "LUMIAUSDT"
    tab = at(layout.MARKET_FUTURES_TAB)
    assert clicks(screen).count(tab) == 2


def test_chart_capture_waits_until_the_chart_has_loaded() -> None:
    # Uji nyata: aplikasi lambat, screenshot pertama hanya berisi animasi loading.
    loading, ready = text_lines("Beli/Long", "Jual/Short"), text_lines("v MA(7) 0,0287")
    nav, _ = trade_page_nav(toolbar(("15 mnt", 0.1265, 0.2416)), chart=[loading, loading, ready])
    nav.show_15m_chart()  # tidak error: menunggu sampai MA(7) terbaca


def test_chart_click_is_repeated_once_when_the_chart_does_not_load() -> None:
    # Uji nyata (ZEREBROUSDT, Windows): MA(7) tak pernah muncul sesudah klik "15 mnt" pertama.
    loading, ready = text_lines("Beli/Long", "Jual/Short"), text_lines("v MA(7) 0,0287")
    nav, screen = trade_page_nav(
        toolbar(("15 mnt", 0.1265, 0.2416)), chart=[loading] * 40 + [ready]
    )
    before = len(clicks(screen))
    nav.show_15m_chart()
    assert clicks(screen)[before:].count(at((0.1265, 0.2416))) == 2


def test_windows_toolbar_area_reaches_a_banner_shifted_15m_button() -> None:
    """Uji nyata (QUSDT, BRUSDT): banner menggeser toolbar ~0,06; area sempit melewatkannya."""
    from binance_bot.binance_desktop import layout_windows as lw

    for shift in (0.04, 0.06, 0.065):
        y = lw.TIMEFRAME_15M[1] + shift
        assert lw.CHART_TOOLBAR_AREA[1] < y < lw.CHART_TOOLBAR_AREA[3] - 0.02


def test_chart_that_never_loads_is_an_error() -> None:
    loading = text_lines("Beli/Long", "Jual/Short")
    nav, _ = trade_page_nav(toolbar(("15 mnt", 0.1265, 0.2416)), chart=[loading])
    with pytest.raises(ScreenReadError, match="belum termuat"):
        nav.show_15m_chart()


def test_futures_list_follows_a_banner_shift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Banner promo menggeser halaman Pasar: tab, judul kolom, dan baris dicari dengan OCR."""
    tabs_area = (0.10, 0.30, 0.60, 0.66)
    header_area = (0.30, 0.20, 0.75, 0.80)
    monkeypatch.setattr(layout, "MARKET_TABS_AREA", tabs_area)
    monkeypatch.setattr(layout, "FUTURES_HEADER_AREA", header_area)
    monkeypatch.setattr(layout, "FUTURES_LIST_SCROLL_NOTCHES", 1)

    tab_y = tabs_area[1] + 0.8 * (tabs_area[3] - tabs_area[1])  # jauh di bawah posisi kalibrasi
    header_y = layout.FUTURES_CHANGE_HEADER[1] + 0.03
    shift = 0.03
    x0, y0, x1, y1 = layout.FUTURES_LIST_AREA
    shifted_area = (x0, y0 + shift, x1, min(1.0, y1 + shift))
    header_rel = (header_y - header_area[1]) / (header_area[3] - header_area[1])
    screen = FakeScreen(
        texts={
            tabs_area: [[TextLine("Futures", 0.5, 0.8)]],
            header_area: [[TextLine("Perubahan 24jam", 0.5, header_rel)]],
            shifted_area: [list_lines((1, "WUSDT", "+60.00%"), (2, "RSRUSDT", "+51.00%"))],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    rows = nav.open_top_gainers()

    assert [(r.rank, r.symbol) for r in rows] == [(1, "WUSDT"), (2, "RSRUSDT")]
    tab_pos = (tabs_area[0] + 0.5 * (tabs_area[2] - tabs_area[0]), tab_y)
    header_pos = (header_area[0] + 0.5 * (header_area[2] - header_area[0]), header_y)
    assert clicks(screen) == [at(layout.SIDEBAR_MARKET), at(tab_pos), at(header_pos)]
    # banner lebih dari 5% tinggi jendela: digulir dua langkah, bukan satu
    scroll = next(e for k, e in screen.events if k == "scroll_down")
    assert scroll[2] == 2
    # ikon trade ikut bergeser
    assert nav._shifted(layout.trade_icon(1)) == pytest.approx(
        (layout.trade_icon(1)[0], layout.trade_icon(1)[1] + shift)
    )


def test_screen_slightly_smaller_than_calibration_still_fits() -> None:
    from binance_bot.binance_desktop.layout import EXPECTED_WINDOW, area_fits, window_target
    from binance_bot.macos import Rect

    width, height = EXPECTED_WINDOW
    dock = Rect(0, 33, width, height - 1)  # Dock tampil: 1 pt lebih pendek
    assert area_fits(dock)
    assert window_target(Rect(0, 33, 800, 600), [dock]) == Rect(0, 33, width, height - 1)
    assert not area_fits(Rect(0, 33, width, int(height * 0.9)))


# --------------------------------------------------------------------------- tampilan berbeda


def tight_list(step: float, *rows: tuple[int, str, str]) -> list[TextLine]:
    """Baris daftar dengan jarak antarbaris `step` (relatif jendela), bukan nilai kalibrasi."""
    _, top, _, bottom = layout.FUTURES_LIST_AREA
    lines = []
    for rank, name, percent in rows:
        window_y = layout.FUTURES_FIRST_ROW_Y + (rank - 1) * step
        y = (window_y - top) / (bottom - top)
        lines += [TextLine(f"{name} Perpetual", 0.2, y), TextLine(percent, 0.8, y + 0.002)]
    return lines


def test_rows_closer_together_than_calibration_keep_their_ranks() -> None:
    from binance_bot.binance_desktop.screen_text import parse_gainer_rows

    step = layout.FUTURES_ROW_STEP * 0.8
    lines = tight_list(
        step, (1, "AUSDT", "+60%"), (2, "BUSDT", "+50%"), (3, "CUSDT", "+40%"),
        (4, "DUSDT", "+30%"), (5, "EUSDT", "+20%"),
    )  # fmt: skip
    rows = parse_gainer_rows(lines, layout.FUTURES_LIST_AREA)
    assert [(r.rank, r.symbol) for r in rows] == [
        (1, "AUSDT"), (2, "BUSDT"), (3, "CUSDT"), (4, "DUSDT"), (5, "EUSDT"),
    ]  # fmt: skip


def test_a_row_ocr_missed_does_not_shift_the_other_ranks() -> None:
    from binance_bot.binance_desktop.screen_text import parse_gainer_rows

    step = layout.FUTURES_ROW_STEP * 0.8
    lines = tight_list(step, (1, "AUSDT", "+60%"), (2, "BUSDT", "+50%"), (4, "DUSDT", "+30%"))
    rows = parse_gainer_rows(lines, layout.FUTURES_LIST_AREA)
    assert [(r.rank, r.symbol) for r in rows] == [(1, "AUSDT"), (2, "BUSDT"), (4, "DUSDT")]


def test_market_menu_is_found_by_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    area = (0.0, 0.05, 0.14, 0.60)
    monkeypatch.setattr(layout, "SIDEBAR_AREA", area)
    screen = FakeScreen(texts={area: [[TextLine("Dasbor", 0.5, 0.1), TextLine("Pasar", 0.4, 0.3)]]})
    nav = make_nav(screen)
    nav.prepare()
    found = (area[0] + 0.4 * (area[2] - area[0]), area[1] + 0.3 * (area[3] - area[1]))
    assert nav._market_menu_position() == pytest.approx(found)


def test_market_menu_falls_back_to_fixed_position(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "SIDEBAR_AREA", (0.0, 0.05, 0.14, 0.60))
    nav = make_nav(FakeScreen())
    nav.prepare()
    assert nav._market_menu_position() == layout.SIDEBAR_MARKET


def test_trade_icon_follows_the_action_header_and_the_rows_read_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_area = (0.60, 0.20, 1.0, 0.80)
    monkeypatch.setattr(layout, "FUTURES_ACTION_AREA", action_area)
    monkeypatch.setattr(layout, "FUTURES_TRADE_ICON_DX", 0.01)
    header = (0.80, 0.47)  # judul "Tindakan" jauh dari posisi kalibrasi
    header_rel = (
        (header[0] - action_area[0]) / (action_area[2] - action_area[0]),
        (header[1] - action_area[1]) / (action_area[3] - action_area[1]),
    )
    step = layout.FUTURES_ROW_STEP * 0.8
    screen = FakeScreen(
        texts={
            action_area: [[TextLine("Tindakan", *header_rel)]],
            layout.FUTURES_LIST_AREA: [
                tight_list(step, (1, "AUSDT", "+60%"), (2, "BUSDT", "+50%"), (4, "DUSDT", "+30%"))
            ],
            layout.SYMBOL_AREA: [text_lines("BUSDT Perpetual")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav._locate_list()
    nav.read_top_gainers()
    icon_x = header[0] + 0.01
    assert nav._trade_icon(2) == pytest.approx((icon_x, layout.FUTURES_FIRST_ROW_Y + step))
    # baris 3 tidak terbaca: diperkirakan dari jarak antarbaris yang terukur
    assert nav._trade_icon(3) == pytest.approx((icon_x, layout.FUTURES_FIRST_ROW_Y + 2 * step))
    assert nav.open_gainer(2) == "BUSDT"
    assert clicks(screen)[-1] == at((icon_x, layout.FUTURES_FIRST_ROW_Y + step))


def test_open_symbol_follows_the_coin_when_the_list_reorders() -> None:
    from binance_bot.binance_desktop.screen_text import GainerRow

    nav = make_nav()
    lists = [
        [GainerRow(1, "AAAUSDT", 50), GainerRow(2, "BBBUSDT", 40), GainerRow(3, "CCCUSDT", 30)],
        # beberapa detik kemudian: BBB dan CCC bertukar tempat
        [GainerRow(1, "AAAUSDT", 51), GainerRow(2, "CCCUSDT", 41), GainerRow(3, "BBBUSDT", 39)],
        [GainerRow(1, "AAAUSDT", 52)],  # CCC sudah keluar dari daftar
    ]
    opened: list[int] = []
    on_trade_page = {1: "AAAUSDT", 2: "CCCUSDT", 3: "BBBUSDT"}

    def top() -> list[GainerRow]:
        rows = lists.pop(0)
        nav._list_rows, nav._on_list = rows, True
        return rows

    def gainer(rank: int) -> str:
        opened.append(rank)
        nav._on_list = False
        return on_trade_page[rank]

    nav.open_top_gainers = top  # type: ignore[method-assign]
    nav.open_gainer = gainer  # type: ignore[method-assign]
    top()  # putaran dimulai: daftar sudah terbuka
    assert nav.open_symbol("AAAUSDT") == "AAAUSDT"  # memakai daftar yang sedang terbuka
    assert nav.open_symbol("BBBUSDT") == "BBBUSDT"  # daftar dibaca ulang: BBB sekarang baris 3
    assert opened == [1, 3]  # klik baris 2 akan membuka CCC, bukan BBB
    nav._on_list = False
    with pytest.raises(ScreenReadError, match="sudah tidak di daftar"):
        nav.open_symbol("CCCUSDT")


# --------------------------------------------------------------------------- satuan USDT otomatis

UNIT_MENU_AREA = (0.60, 0.30, 1.0, 0.70)
UNIT_BUTTON = (0.97, 0.31)
RADIO = (0.82, 0.63)  # "Ukuran Order": di zona tombol order, tetapi di bawah tombolnya


def unit_menu(radio: tuple[float, float] | None = RADIO) -> list[TextLine]:
    x0, y0, x1, y1 = UNIT_MENU_AREA
    lines = [
        TextLine("Preferensi Unit", 0.3, 0.1),
        TextLine("Masukkan dan menampilkan ukuran order dalam USDT.", 0.5, 0.6),
    ]
    if radio:
        lines.append(
            TextLine("C. Ukuran Order", (radio[0] - x0) / (x1 - x0), (radio[1] - y0) / (y1 - y0))
        )
    return lines


def unit_nav(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    qty: list[list[TextLine]],
    menu: list[list[TextLine]],
) -> tuple[BinanceNavigator, FakeScreen]:
    monkeypatch.chdir(tmp_path)  # foto diagnosa ditulis relatif ke folder kerja
    monkeypatch.setattr(layout, "ORDER_UNIT_BUTTON", UNIT_BUTTON)
    monkeypatch.setattr(layout, "ORDER_UNIT_MENU_AREA", UNIT_MENU_AREA)
    monkeypatch.setattr(layout, "ORDER_UNIT_MIN_Y", 0.62)
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")],
            layout.ORDER_QTY_AREA: qty,
            UNIT_MENU_AREA: menu,
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    return nav, screen


def test_usdt_unit_is_chosen_from_the_menu_below_the_order_buttons(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nav, screen = unit_nav(
        monkeypatch,
        tmp_path,
        qty=[text_lines("STRK"), text_lines("USDT"), text_lines("USDT"), text_lines("100", "USDT")],
        menu=[[], unit_menu(), unit_menu(), unit_menu()],  # tertutup, lalu terbuka setelah diklik
    )
    assert layout.in_order_button_zone(RADIO)  # titik ini biasanya terlarang
    nav.fill_quantity("100")
    done = clicks(screen)
    assert at(UNIT_BUTTON) in done and at(RADIO) in done
    assert done.index(at(UNIT_BUTTON)) < done.index(at(RADIO))
    assert ("type", "100") in screen.events
    assert nav._forbidden(RADIO)  # pengecualian tidak bocor ke klik berikutnya


def test_usdt_unit_already_selected_needs_no_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nav, screen = unit_nav(
        monkeypatch, tmp_path, qty=[text_lines("USDT"), text_lines("100", "USDT")], menu=[[]]
    )
    nav.fill_quantity("100")
    assert at(UNIT_BUTTON) not in clicks(screen)


def test_nothing_is_clicked_in_the_button_zone_when_the_menu_does_not_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nav, screen = unit_nav(monkeypatch, tmp_path, qty=[text_lines("STRK")], menu=[[]])
    with pytest.raises(ScreenReadError, match="Menu satuan"):
        nav.fill_quantity("100")
    assert at(RADIO) not in clicks(screen)
    assert not any(kind in ("type", "clear") for kind, _ in screen.events)


def test_the_menu_choice_next_to_the_order_buttons_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    near_buttons = (0.82, 0.55)  # di atas garis aman: bisa saja tombol Beli/Long
    nav, screen = unit_nav(
        monkeypatch,
        tmp_path,
        qty=[text_lines("STRK")],
        menu=[[], unit_menu(near_buttons), unit_menu(near_buttons)],
    )
    with pytest.raises(ScreenReadError, match="tempat aman"):
        nav.fill_quantity("100")
    assert at(near_buttons) not in clicks(screen)


def test_the_click_is_cancelled_if_the_menu_vanished_before_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nav, screen = unit_nav(
        monkeypatch,
        tmp_path,
        qty=[text_lines("STRK")],
        menu=[[], unit_menu(), unit_menu(), []],  # menu hilang tepat sebelum klik
    )
    with pytest.raises(SafetyError, match="menu tidak terbukti terbuka"):
        nav.fill_quantity("100")
    assert at(RADIO) not in clicks(screen)


def test_typing_is_refused_if_the_unit_is_still_not_usdt_after_the_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nav, screen = unit_nav(
        monkeypatch,
        tmp_path,
        qty=[text_lines("STRK")],  # tetap koin
        menu=[[], unit_menu(), unit_menu(), unit_menu()],
    )
    with pytest.raises(ScreenReadError, match="masih bukan USDT"):
        nav.fill_quantity("100")
    assert not any(kind in ("type", "clear") for kind, _ in screen.events)


def test_open_symbol_skips_a_coin_that_slid_out_of_the_top_five() -> None:
    from binance_bot.binance_desktop.screen_text import GainerRow

    nav = make_nav()
    rows = [GainerRow(r, f"C{r}USDT", 50 - r) for r in range(1, 6)] + [GainerRow(6, "AKEUSDT", 8)]
    nav._list_rows, nav._on_list = rows, True
    with pytest.raises(ScreenReadError, match="di luar Top 5"):
        nav.open_symbol("AKEUSDT")  # klik baris 6 tidak didukung layout: dilewati, bukan crash


def _locked_order_nav(
    monkeypatch: pytest.MonkeyPatch, shown: list[str]
) -> tuple[BinanceNavigator, list[tuple[int, int]]]:
    nav = make_nav()
    nav._rect, nav._on_trade_page = WINDOW, True
    pressed: list[tuple[int, int]] = []
    monkeypatch.setattr(nav._window, "click", lambda x, y: pressed.append((x, y)))
    monkeypatch.setattr(nav, "_read_texts", lambda area: shown)
    monkeypatch.setattr(nav, "_ensure_front", lambda: None)
    monkeypatch.setattr(nav, "short_button", lambda: (0.95, 0.51))
    return nav, pressed


def test_press_short_is_locked_even_when_called_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    from binance_bot.strategy.execution import OrderPlan

    nav, pressed = _locked_order_nav(monkeypatch, ["100", "USDT"])
    plan = OrderPlan("CFXUSDT", "100", "100", 100.0, 50.0, 1.0, 0.98, 2)
    with pytest.raises(SafetyError, match="terkunci"):
        nav.press_short(plan)
    assert pressed == []


def test_press_short_logic_when_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hanya di tes: kunci dibuka (seperti --uang-sungguhan) untuk membuktikan logikanya.
    from binance_bot.strategy import execution
    from binance_bot.strategy.execution import OrderPlan

    monkeypatch.setattr(execution, "_live_orders", True)
    plan = OrderPlan("CFXUSDT", "100", "100", 100.0, 50.0, 1.0, 0.98, 2)

    nav, pressed = _locked_order_nav(monkeypatch, ["50", "USDT"])  # kolom jumlah tidak cocok
    with pytest.raises(SafetyError, match="order dibatalkan"):
        nav.press_short(plan)
    assert pressed == []

    nav, pressed = _locked_order_nav(monkeypatch, ["100", "USDT"])
    nav.press_short(plan)
    assert pressed == [nav.rect.point_at(0.95, 0.51)]  # hanya tombol Short yang ditemukan

    nav._on_trade_page = False
    with pytest.raises(SafetyError, match="halaman koin"):
        nav.press_short(plan)


def test_press_short_reads_the_quantity_again_when_ocr_stumbles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Uji nyata (AGTUSDT): bacaan "24" padahal kolom berisi 20, 0,17 detik setelah bacaan "20".
    from binance_bot.strategy import execution
    from binance_bot.strategy.execution import OrderPlan

    monkeypatch.setattr(execution, "_live_orders", True)
    plan = OrderPlan("CFXUSDT", "100", "100", 100.0, 50.0, 1.0, 0.98, 2)

    nav, pressed = _locked_order_nav(monkeypatch, [])
    answers = iter([["10", "USDT"], ["100", "USDT"]])
    monkeypatch.setattr(nav, "_read_texts", lambda area: next(answers))
    nav.press_short(plan)
    assert pressed == [nav.rect.point_at(0.95, 0.51)]

    nav, pressed = _locked_order_nav(monkeypatch, [])
    reads: list[int] = []
    monkeypatch.setattr(nav, "_read_texts", lambda area: reads.append(1) or ["50", "USDT"])
    with pytest.raises(SafetyError, match="order dibatalkan"):
        nav.press_short(plan)  # semua bacaan salah: tetap batal, tidak ada yang diklik
    assert pressed == [] and len(reads) == 4


def test_short_button_is_searched_only_in_the_order_form_not_the_chart_widget() -> None:
    nav = make_nav()
    zones = nav._order_form_zones()
    assert zones and all(
        x0 >= 0.5 for x0, _, _, _ in zones
    )  # widget melayang di grafik dikecualikan


def test_exchange_window_covered_by_marketforge_is_detected_on_mac_and_windows() -> None:
    from binance_bot.tebbit_web.visible import OnScreenWindow

    nav = make_nav()
    nav._rect = WINDOW
    full = Rect(WINDOW.x, WINDOW.y, WINDOW.width, WINDOW.height)
    for owner, covered in [
        ("Electron", True),  # MarketForge memajukan jendelanya (show_app)
        ("MarketForge.exe", True),
        ("Binance", False),  # macOS
        ("Binance.exe", False),  # Windows
    ]:
        nav._windows = lambda owner=owner: [OnScreenWindow(owner, full)]
        assert nav._covered() is covered, owner
    nav._windows = None  # tanpa daftar jendela (tes lain): tidak diperiksa
    assert nav._covered() is False


def test_open_symbol_retries_once_when_the_list_moves_between_read_and_click() -> None:
    from binance_bot.binance_desktop.screen_text import GainerRow

    nav = make_nav()
    first = [GainerRow(1, "AAAUSDT", 50), GainerRow(2, "BBBUSDT", 40)]
    again = [GainerRow(1, "BBBUSDT", 51), GainerRow(2, "AAAUSDT", 49)]
    reads = [again]
    # Klik baris 2 (BBB menurut daftar) ternyata membuka AAA: daftar bergeser tepat saat diklik.
    trade_pages = ["AAAUSDT", "BBBUSDT"]
    clicked: list[int] = []

    def top() -> list[GainerRow]:
        rows = reads.pop(0)
        nav._list_rows, nav._on_list = rows, True
        return rows

    def gainer(rank: int) -> str:
        clicked.append(rank)
        nav._on_list = False
        return trade_pages.pop(0)

    nav.open_top_gainers = top  # type: ignore[method-assign]
    nav.open_gainer = gainer  # type: ignore[method-assign]
    nav._list_rows, nav._on_list = first, True
    assert nav.open_symbol("BBBUSDT") == "BBBUSDT"
    assert clicked == [2, 1]  # klik pertama meleset, daftar dibaca ulang, BBB kini baris 1


def test_market_menu_is_retried_when_ocr_misses_it_once(monkeypatch: pytest.MonkeyPatch) -> None:
    area = (0.0, 0.05, 0.14, 0.60)
    monkeypatch.setattr(layout, "SIDEBAR_AREA", area)
    screen = FakeScreen(texts={area: [[], [TextLine("Pasar", 0.4, 0.3)]]})  # percobaan 1 kosong
    nav = make_nav(screen)
    nav.prepare()
    found = (area[0] + 0.4 * (area[2] - area[0]), area[1] + 0.3 * (area[3] - area[1]))
    assert nav._market_menu_position() == pytest.approx(found)


@pytest.mark.parametrize(
    "label",
    [
        "MA(7) 0,46097",
        "v MAC7) 0,46097 MA(25) 0,45520",
        "MA[7) 0,1",
        "MA 7 0,1",
        "7) 0,026157 MA(25) 0,024945 MA(99) 0,023298",  # MA99 melintasi awal label
        "MA(25) 0,455",
    ],
)
def test_chart_legend_is_recognised_even_when_ocr_garbles_the_start(label: str) -> None:
    """Uji nyata (BRUSDT, ZEREBROUSDT, Windows): "MA(7)" terbaca "MAC7)" atau "7) 0,02..."."""
    from binance_bot.binance_desktop.navigator import _CHART_LEGEND

    assert _CHART_LEGEND.search(label)


@pytest.mark.parametrize(
    "label", ["MA(77) 1", "MA(70) 1", "Beli/Long", "Jumlah (USDT)", "0,026157"]
)
def test_chart_legend_does_not_match_other_lines(label: str) -> None:
    from binance_bot.binance_desktop.navigator import _CHART_LEGEND

    assert not _CHART_LEGEND.search(label)


def test_a_banner_shifts_the_order_form_and_every_click_follows_it() -> None:
    """Uji nyata (BRUSDT): banner menggeser form ~0,065; klik di posisi lama mengenai "Cross"."""
    shift = 0.065
    qty = layout.ORDER_QTY_AREA
    shifted_qty = (qty[0], qty[1] + shift, qty[2], qty[3] + shift)
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("BRUSDT Perp")],
            shifted_qty: [text_lines("USDT"), text_lines("100", "USDT")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    nav._chart_shift = shift
    nav.fill_quantity("100")

    tab = (layout.ORDER_TAB_MARKET[0], layout.ORDER_TAB_MARKET[1] + shift)
    field = (layout.ORDER_QTY_FIELD[0], layout.ORDER_QTY_FIELD[1] + shift)
    assert screen.events[-4:] == [
        ("click", at(tab)),
        ("click", at(field)),
        ("clear", None),
        ("type", "100"),
    ]
    # Zona tombol order ikut bergeser: titik di zona lama maupun zona baru tetap terlarang.
    x0, y0, _x1, y1 = layout.ORDER_BUTTON_ZONES[0]
    assert nav._forbidden((x0 + 0.01, y0 + 0.01))
    assert nav._forbidden((x0 + 0.01, y1 + shift - 0.01))
    assert not nav._forbidden(tab) and not nav._forbidden(field)


def test_a_tiny_measurement_error_does_not_shift_the_form() -> None:
    screen = FakeScreen(texts={layout.SYMBOL_AREA: [text_lines("BRUSDT Perp")]})
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    nav._chart_shift = 0.006  # kesalahan ukur OCR, bukan banner
    assert nav._form_shift == 0.0
    assert nav._form_point(layout.ORDER_QTY_FIELD) == layout.ORDER_QTY_FIELD


def leverage_nav(
    monkeypatch: pytest.MonkeyPatch, plain: list[TextLine], companion: list[str]
) -> tuple[BinanceNavigator, FakeScreen]:
    monkeypatch.setattr(layout, "LEVERAGE_BOX_X", (0.37, 0.47), raising=False)
    screen = FakeScreen(
        texts={layout.SYMBOL_AREA: [text_lines("BRUSDT Perp")], layout.MARGIN_AREA: [plain]}
    )
    nav = make_nav(screen)
    monkeypatch.setattr(nav, "_leverage_with_companion", lambda: companion)
    nav.prepare()
    nav.open_gainer(1)
    return nav, screen


def test_leverage_dropped_by_ocr_is_read_with_the_companion_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uji nyata (BRUSDT, Windows): "2x" hilang dari bacaan biasa, lalu terbaca dengan kata."""
    nav, _ = leverage_nav(monkeypatch, text_lines("Cross"), ["Leverage", "2x"])
    assert nav.read_margin_settings().leverage == 2


def test_companion_is_not_used_when_the_plain_read_already_has_the_leverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav, _ = leverage_nav(monkeypatch, text_lines("Cross", "20x"), ["Leverage", "2x"])
    assert nav.read_margin_settings().leverage == 20


def test_leverage_button_is_clicked_by_layout_when_ocr_cannot_place_its_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav, screen = leverage_nav(monkeypatch, text_lines("Cross"), ["Leverage", "20x"])
    x0, y0, x1, y1 = layout.MARGIN_AREA
    button = (x0 + 0.42 * (x1 - x0), (y0 + y1) / 2)
    with pytest.raises(ScreenReadError, match="Dialog leverage tidak terbuka"):
        nav.ensure_leverage(2)
    assert clicks(screen)[-1] == at(button)  # klik hanya setelah angkanya terbukti terbaca


def test_leverage_is_not_clicked_blindly_when_nothing_could_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav, screen = leverage_nav(monkeypatch, text_lines("Cross"), [])
    before = len(clicks(screen))
    with pytest.raises(ScreenReadError, match="Tombol leverage"):
        nav.ensure_leverage(2)
    assert len(clicks(screen)) == before


def test_positions_panel_follows_a_banner_shift(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uji nyata (BRUSDT): banner menggeser panel Posisi ~0,065 sampai barisnya keluar jendela."""
    monkeypatch.setattr(layout, "POSITIONS_TAB_Y", 0.857, raising=False)
    nav = make_nav()
    nav.prepare()
    assert nav._measure_positions_shift((0.1, 0.857 + 0.003)) == 0.0  # galat ukur
    shift = nav._measure_positions_shift((0.1, 0.920))
    assert shift == pytest.approx(0.063)
    nav._positions_shift = shift
    x0, y0, x1, _y1 = layout.POSITIONS_TABLE_AREA
    assert nav._positions_table() == (x0, pytest.approx(min(1.0, y0 + shift)), x1, 1.0)
    monkeypatch.setattr(layout, "POSITIONS_TAB_Y", None)
    assert nav._measure_positions_shift((0.1, 0.9)) == 0.0  # profil tanpa kalibrasi: tidak digeser


def _positions_nav(
    monkeypatch: pytest.MonkeyPatch, pages: list[list[TextLine]]
) -> tuple[BinanceNavigator, FakeScreen]:
    """Navigator di mode uang sungguhan; `pages` = bacaan tabel Posisi berurutan."""
    from binance_bot.strategy import execution

    monkeypatch.setattr(execution, "_live_orders", True)
    screen = FakeScreen(
        texts={
            layout.POSITIONS_TAB_AREA: [[TextLine("Posisi(4)", 0.1, 0.5)]],
            layout.POSITIONS_TABLE_AREA: pages,
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    return nav, screen


def _table_point(x: float, y: float) -> tuple[int, int]:
    x0, y0, x1, y1 = layout.POSITIONS_TABLE_AREA
    return at((x0 + x * (x1 - x0), y0 + y * (y1 - y0)))


def test_the_position_row_is_found_by_name_further_down_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3-5 posisi: baris koin yang dijual di bawah, belum terlihat. Tabel digulir, lalu yang diklik
    tombol Market di baris koin itu, bukan baris pertama atau baris koin bernama mirip."""
    top = [TextLine("BTWUSDT Perp", 0.1, 0.3), TextLine("ICNTUSDT Perp", 0.1, 0.7)]
    lower = [
        TextLine("ICNTUSDT Perp", 0.1, 0.3),
        TextLine("1000PEPEUSDT Perp", 0.1, 0.5),
        TextLine("PEPEUSDT Perp", 0.1, 0.7),
    ]
    buttons = [
        TextLine("Market", 0.8, 0.3),
        TextLine("Market", 0.8, 0.5),
        TextLine("Market", 0.8, 0.7),
    ]
    closed = [TextLine("ICNTUSDT Perp", 0.1, 0.3), TextLine("1000PEPEUSDT Perp", 0.1, 0.5)]
    nav, screen = _positions_nav(monkeypatch, [top, top, lower, buttons, closed])

    nav.close_position("PEPEUSDT")

    kinds = [kind for kind, _ in screen.events if kind in ("scroll_up", "scroll_down", "click")]
    assert kinds.index("scroll_down") < len(kinds) - 1 - kinds[::-1].index("click")
    assert clicks(screen)[-1] == _table_point(0.8, 0.7)  # baris PEPEUSDT, bukan 1000PEPEUSDT
    assert kinds[-1] == "scroll_up"  # tabel dikembalikan ke baris teratas


def test_a_similar_name_is_not_closed_and_the_table_is_scrolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_similar = [TextLine("1000PEPEUSDT Perp", 0.1, 0.3), TextLine("Market", 0.8, 0.3)]
    nav, screen = _positions_nav(monkeypatch, [only_similar])

    with pytest.raises(ScreenReadError, match="tidak ada di tab Posisi"):
        nav.close_position("PEPEUSDT")

    assert len(clicks(screen)) == 1  # hanya tab Posisi; tombol Market tidak disentuh
    vertical = [kind for kind, _ in screen.events if kind in ("scroll_up", "scroll_down")]
    assert vertical[-1] == "scroll_up"


def test_a_visible_row_is_clicked_without_scrolling_the_table_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = [TextLine("BTWUSDT Perp", 0.1, 0.3)]
    nav, screen = _positions_nav(
        monkeypatch, [row, [TextLine("Market", 0.8, 0.3)], [TextLine("ICNTUSDT Perp", 0.1, 0.3)]]
    )
    nav.close_position("BTWUSDT")
    market = screen.events.index(("click", _table_point(0.8, 0.3)))
    assert not any(kind == "scroll_down" for kind, _ in screen.events[:market])
    # Sesudah klik, seluruh tabel diperiksa: baris BTWUSDT harus hilang di mana pun.
    assert any(kind == "scroll_down" for kind, _ in screen.events[market:])


@pytest.mark.parametrize(
    "label", ["Posisi(0)", "Posisi(O) Transaksi terbuka(O) Riwayat Order", "Positions(2)"]
)
def test_positions_tab_is_found_even_when_ocr_reads_zero_as_the_letter_o(label: str) -> None:
    from binance_bot.binance_desktop.navigator import _POSITIONS_TAB

    assert _POSITIONS_TAB.search(label)


# ----------------------------------------------------------------- profil layar 1366x768


def test_the_layout_profile_follows_the_screen_width_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Laptop 1366x768 memakai profil 1366; layar 1920x1080 memakai profil 1920."""
    monkeypatch.delenv("BOT_LAYOUT", raising=False)
    monkeypatch.setattr(layout.sys, "platform", "win32")
    for width, expected in ((1366, "windows-1366"), (1536, "windows-1366"), (1920, "windows")):
        monkeypatch.setattr(layout, "_work_area_width", lambda w=width: w)
        assert layout._profile() == expected
    monkeypatch.setattr(layout, "_work_area_width", lambda: None)  # tak terbaca: profil 1920
    assert layout._profile() == "windows"
    monkeypatch.setattr(layout.sys, "platform", "darwin")
    assert layout._profile() == "mac"
    monkeypatch.setenv("BOT_LAYOUT", "windows-1366")  # dipaksa lewat variabel lingkungan
    assert layout._profile() == "windows-1366"


def test_the_1366_profile_is_internally_consistent() -> None:
    """Pemeriksaan murah pada hasil ukur: area valid, ikon lima baris muat, menu satuan aman."""
    from binance_bot.binance_desktop import layout_windows_1366 as small

    areas = [
        small.SIDEBAR_AREA, small.MARKET_TABS_AREA, small.FUTURES_HEADER_AREA,
        small.FUTURES_LIST_AREA, small.FUTURES_ACTION_AREA, small.SYMBOL_AREA,
        small.CHART_TOOLBAR_AREA, small.CHART_AREA, small.MARGIN_AREA, small.ORDER_QTY_AREA,
        small.ORDER_AVAILABLE_AREA, small.ORDER_UNIT_MENU_AREA, *small.ORDER_BUTTON_ZONES,
    ]  # fmt: skip
    for x0, y0, x1, y1 in areas:
        assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0
    last_row = small.FUTURES_FIRST_ROW_Y + (small.MAX_RANK - 1) * small.FUTURES_ROW_STEP
    assert last_row < small.FUTURES_LIST_AREA[3]  # baris ke-5 ada di dalam area baca
    assert small.EXPECTED_WINDOW == (1366, 720) and small.WINDOW_MAXIMIZED
    # Titik yang diklik di form tidak boleh jatuh di zona tombol order.
    for point in (small.ORDER_TAB_MARKET, small.ORDER_QTY_FIELD, small.ORDER_UNIT_BUTTON):
        assert not any(
            x0 <= point[0] <= x1 and y0 <= point[1] <= y1
            for x0, y0, x1, y1 in small.ORDER_BUTTON_ZONES
        )
    assert small.ORDER_UNIT_MIN_Y >= 0.6 and small.OCR_UPSCALE == 2


def test_closing_from_another_page_first_opens_a_coin_page_for_the_positions_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bot lain meninggalkan layar di daftar top gainers (tanpa tab Posisi): jual otomatis membuka
    halaman koin teratas dulu, bukan gagal dengan "tab Posisi tidak ditemukan"."""
    from binance_bot.binance_desktop.screen_text import GainerRow

    nav, screen = _positions_nav(
        monkeypatch,
        [
            [TextLine("BTWUSDT Perp", 0.1, 0.3)],
            [TextLine("Market", 0.8, 0.3)],
            [TextLine("ICNTUSDT Perp", 0.1, 0.3)],
        ],
    )
    tab_area = screen.rect.sub(*layout.POSITIONS_TAB_AREA)
    screen._texts[tab_area] = [[], [TextLine("Posisi(1)", 0.1, 0.5)]]
    opened: list[str] = []
    monkeypatch.setattr(
        nav, "open_top_gainers", lambda: opened.append("list") or [GainerRow(1, "AUSDT", 9.0)]
    )
    monkeypatch.setattr(nav, "open_gainer", lambda rank: opened.append(f"top{rank}") or "AUSDT")

    nav.close_position("BTWUSDT")

    assert opened == ["list", "top1"]
    assert ("click", _table_point(0.8, 0.3)) in screen.events
