import pytest

from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.screen_text import (
    is_sorted_by_top_gain,
    parse_futures_symbol,
    parse_gainer_rows,
    parse_margin,
    parse_percent,
    same_number,
)
from binance_bot.exceptions import ScreenReadError
from fakes import list_lines


def test_parse_percent_accepts_signs_and_both_decimal_marks() -> None:
    assert parse_percent("+53,55%") == 53.55
    assert parse_percent("-30.04 %") == -30.04
    assert parse_percent("Perpetual") is None


def test_futures_symbol_ignores_ocr_junk_before_the_name() -> None:
    assert parse_futures_symbol([":E STRKUSDT Perp", "0,10853"]) == "STRKUSDT"
    assert parse_futures_symbol(["* TIAUSDC Perpetual"]) == "TIAUSDC"
    with pytest.raises(ScreenReadError):
        parse_futures_symbol(["STRK/USDT", "Harga"])


def test_rows_keep_screen_rank_when_ocr_misses_a_name() -> None:
    lines = list_lines((1, "LUMIAUSDT", "+53.55%"), (3, "CFXUSDT", "+34.62%"))
    rows = parse_gainer_rows(lines, layout.FUTURES_LIST_AREA)
    assert [(r.rank, r.symbol) for r in rows] == [(1, "LUMIAUSDT"), (3, "CFXUSDT")]


def test_sorted_by_top_gain() -> None:
    rows = parse_gainer_rows(
        list_lines((1, "STRKUSDT", "+50%"), (2, "CFXUSDT", "+20%")), layout.FUTURES_LIST_AREA
    )
    assert is_sorted_by_top_gain(rows)
    assert not is_sorted_by_top_gain(list(reversed(rows)))
    assert not is_sorted_by_top_gain([])


def test_margin_settings() -> None:
    cross = parse_margin(["Cross", "20x", "M"])
    assert (cross.isolated, cross.leverage, cross.is_sop_compliant) == (False, 20, False)
    assert cross.describe() == "Cross 20x"
    assert parse_margin(["Isolated", "1x"]).is_sop_compliant


def test_same_number_treats_comma_and_dot_alike() -> None:
    assert same_number("184,6", "184.6")
    assert same_number("184,6 STRK", "184,6")
    assert not same_number("1846", "184,6")
    assert not same_number("STRK", "1")
