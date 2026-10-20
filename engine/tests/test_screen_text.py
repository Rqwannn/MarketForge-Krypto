import pytest

from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.screen_text import (
    is_sorted_by_top_gain,
    parse_available_usdt,
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


def test_margin_settings_against_sop_v2() -> None:
    cross = parse_margin(["Cross", "20x", "M"])
    assert (cross.isolated, cross.leverage, cross.describe()) == (False, 20, "Cross 20x")
    assert cross.problems(leverage=2) == ["leverage 20x, seharusnya 2x"]
    # Mode margin memakai bawaan bursa: Cross 2x dan Isolated 2x sama-sama sesuai SOP.
    assert parse_margin(["Cross", "2x"]).problems(leverage=2) == []
    assert parse_margin(["Isolated", "2x"]).problems(leverage=2) == []


def test_same_number_treats_comma_and_dot_alike() -> None:
    assert same_number("184,6", "184.6")
    assert same_number("184,6 STRK", "184,6")
    assert not same_number("1846", "184,6")
    assert not same_number("STRK", "1")


def test_single_letter_coin_is_read() -> None:
    # Uji nyata: rank 4 adalah "S" (Sonic), tampil sebagai "SUSDT Perpetual".
    texts = ["SUSDT Perpetual", "Please note that the project name of S is Sonic (formerly FTM)."]
    assert parse_futures_symbol(texts) == "SUSDT"
    rows = parse_gainer_rows(list_lines((4, "SUSDT", "+21.9%")), layout.FUTURES_LIST_AREA)
    assert [(r.rank, r.symbol) for r in rows] == [(4, "SUSDT")]


def test_same_number_ignores_thousands_separator_and_trailing_zero() -> None:
    from binance_bot.binance_desktop.screen_text import same_number

    assert same_number("3.367,2", "3367,2")  # Binance Indonesia: titik ribuan
    assert same_number("41", "41,0")  # nol di belakang koma tidak ditampilkan
    assert same_number("184,6", "184,6")
    assert same_number("184.6", "184,6")
    assert same_number("3.367", "3,367")  # titik tunggal sebagai desimal
    assert not same_number("33672", "3367,2")  # angka lain
    assert not same_number("184,4", "184,6")
    assert not same_number("", "1")
    assert not same_number("W", "1")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("58,70", 58.7),
        ("1.234,56", 1234.56),
        ("58.70", 58.7),
        ("1.234", 1234.0),
        ("0,00", 0.0),
        ("1.234.567", 1234567.0),
        ("abc", None),
        ("", None),
        ("-5", None),
    ],
)
def test_amounts_are_read_the_way_binance_prints_them(text: str, expected: float | None) -> None:
    from binance_bot.binance_desktop.screen_text import parse_amount

    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["Tersedia 21,00 USDT"], 21.0),
        (["Tersedia O,OO USDT"], 0.0),  # uji nyata 19 Okt: dompet kosong terbaca "O,OO"
        (["Tersedia o,oo USDT"], 0.0),
        (["Tersedia O.OO USDT"], 0.0),
        (["Tersedia 2O,OO USDT"], 20.0),
        (["Tersedia 21,OO USDT"], 21.0),
        (["Tersedia 1.234,5O USDT"], 1234.5),
        (["Jumlah", "Tersedia 58,70 USDT"], 58.7),  # baris lain di area diabaikan
        (["Tersedia OOO USDT"], None),  # hanya huruf, tanpa angka atau pemisah: bukan saldo
        (["Tersedia USDT"], None),
        (["Maks 0,00 USDT"], None),
        ([], None),
    ],
)
def test_available_balance_reads_the_letter_o_as_zero(
    texts: list[str], expected: float | None
) -> None:
    assert parse_available_usdt(texts) == expected


def test_margin_leverage_is_read_from_the_companion_word_line() -> None:
    """Kotak leverage dibaca bersama kata pendamping: "Leverage 2x" (uji nyata, layar 1366x768)."""
    from binance_bot.binance_desktop.screen_text import parse_margin

    assert parse_margin(["Cross", "Leverage 2x", "Leverage"]).leverage == 2
    assert parse_margin(["Cross", "Leverage 20x"]).leverage == 20
    assert parse_margin(["Cross", "25x"]).leverage == 25
    assert parse_margin(["Cross", "Leverage"]).leverage is None
