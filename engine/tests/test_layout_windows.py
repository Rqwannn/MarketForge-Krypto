"""Pemeriksaan konsistensi profil layout Windows (tanpa layar)."""

from binance_bot.binance_desktop import layout_windows as win


def _inside(point: tuple[float, float]) -> bool:
    return 0.0 < point[0] < 1.0 and 0.0 < point[1] < 1.0


def test_all_click_targets_are_inside_the_window() -> None:
    targets = [
        win.SIDEBAR_MARKET,
        win.MARKET_FUTURES_TAB,
        win.FUTURES_CHANGE_HEADER,
        win.FUTURES_LIST_SCROLL_POINT,
        win.TIMEFRAME_15M,
        win.ORDER_TAB_MARKET,
        win.ORDER_QTY_FIELD,
    ]
    assert all(_inside(t) for t in targets)


def test_five_gainer_rows_fit_above_the_bottom_ticker() -> None:
    last_row_y = win.FUTURES_FIRST_ROW_Y + (win.MAX_RANK - 1) * win.FUTURES_ROW_STEP
    assert last_row_y < 0.93  # ticker Binance mulai sekitar y=0.965


def test_list_area_covers_every_row_and_the_change_column() -> None:
    _, top, right, bottom = win.FUTURES_LIST_AREA
    first = win.FUTURES_FIRST_ROW_Y
    last = first + (win.MAX_RANK - 1) * win.FUTURES_ROW_STEP
    assert top < first and last < bottom
    assert right > win.FUTURES_CHANGE_HEADER[0]  # kolom perubahan ikut terbaca OCR


def test_order_zones_never_contain_the_fields_the_bot_clicks() -> None:
    def in_zone(point: tuple[float, float]) -> bool:
        x, y = point
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in win.ORDER_BUTTON_ZONES)

    for target in (win.TIMEFRAME_15M, win.ORDER_TAB_MARKET, win.ORDER_QTY_FIELD):
        assert not in_zone(target)
    # tombol Beli/Long dan Jual/Short (y 0.55..0.80 di form kanan) harus terlindungi
    assert in_zone((0.87, 0.60)) and in_zone((0.95, 0.75))


def test_windows_profile_is_the_maximized_screen() -> None:
    assert win.WINDOW_MAXIMIZED is True
    assert win.EXPECTED_WINDOW == (1920, 1020)
