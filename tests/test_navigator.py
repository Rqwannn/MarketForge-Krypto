from pathlib import Path

import pytest

from binance_bot.binance_desktop import BinanceNavigator, layout
from binance_bot.config import Settings
from binance_bot.exceptions import AppNotRunningError, SafetyError, ScreenReadError, WindowError
from binance_bot.macos import Rect
from fakes import WINDOW, FakeApps, FakeScreen, list_lines, text_lines

ASCENDING = list_lines((1, "USUSDT", "-32.21%"), (2, "JCTUSDT", "-30.04%"))
DESCENDING = list_lines(
    (1, "LUMIAUSDT", "+53.55%"), (2, "STRKUSDT", "+53.14%"), (3, "CFXUSDT", "+34.62%")
)


def make_nav(screen: FakeScreen | None = None, apps: FakeApps | None = None) -> BinanceNavigator:
    screen = screen or FakeScreen()
    return BinanceNavigator(
        Settings(settle_delay_s=0), apps or FakeApps(), screen, screen, sleep=lambda _: None
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


def test_prepare_refuses_window_size_that_differs_from_calibration() -> None:
    with pytest.raises(WindowError, match="1200x700"):
        make_nav(FakeScreen(Rect(0, 33, 1200, 700))).prepare()


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
            layout.ORDER_QTY_AREA: [text_lines("184,6", "STRK")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    nav.fill_quantity("184,6")

    assert screen.events[-4:] == [
        ("click", at(layout.ORDER_TAB_MARKET)),
        ("click", at(layout.ORDER_QTY_FIELD)),
        ("clear", None),
        ("type", "184,6"),
    ]


def test_fill_quantity_fails_when_screen_shows_another_number() -> None:
    screen = FakeScreen(
        texts={
            layout.SYMBOL_AREA: [text_lines("STRKUSDT Perp")],
            layout.ORDER_QTY_AREA: [text_lines("1846", "STRK")],
        }
    )
    nav = make_nav(screen)
    nav.prepare()
    nav.open_gainer(1)
    with pytest.raises(ScreenReadError, match="1846"):
        nav.fill_quantity("184,6")


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
