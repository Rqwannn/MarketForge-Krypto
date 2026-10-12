from pathlib import Path

import pytest

from binance_bot.binance_desktop import BinanceNavigator, layout
from binance_bot.config import Settings
from binance_bot.exceptions import AppNotRunningError, SafetyError, ScreenReadError, WindowError
from binance_bot.macos import Rect, TextLine
from fakes import AREA, WINDOW, Clock, FakeApps, FakeScreen, list_lines, text_lines

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


def test_chart_that_never_loads_is_an_error() -> None:
    loading = text_lines("Beli/Long", "Jual/Short")
    nav, _ = trade_page_nav(toolbar(("15 mnt", 0.1265, 0.2416)), chart=[loading])
    with pytest.raises(ScreenReadError, match="belum termuat"):
        nav.show_15m_chart()
