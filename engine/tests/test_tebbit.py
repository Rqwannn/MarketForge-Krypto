"""Bagian Tebbit yang bisa diuji tanpa Chrome: pola teks, pengetikan, dan zona terlarang."""

from __future__ import annotations

import pytest

from binance_bot.exceptions import MarketDataError, NoHistoryError, WindowError
from binance_bot.tebbit_web import layout_tebbit as lay
from binance_bot.tebbit_web.market import ScreenMarket
from binance_bot.tebbit_web.navigator import _FIFTEEN


@pytest.mark.parametrize("text", ["Time 1m 5m 15m", "5m 15ml", "15 m", "15m 30m"])
def test_tombol_15m_terbaca_walau_ocr_menempelkan_karakter(text: str) -> None:
    assert _FIFTEEN.search(text)


@pytest.mark.parametrize("text", ["Time 1m 5m", "1.5m", "115m", "30m 1H"])
def test_tombol_lain_bukan_15m(text: str) -> None:
    assert not _FIFTEEN.search(text)


def test_hanya_angka_yang_diketik_tanpa_enter() -> None:
    from binance_bot.macos.keyboard import clear_field, type_number

    calls: list[list[str]] = []
    type_number("100,5", run=lambda args: calls.append(args) or "")
    lines = [line.strip() for line in calls[0][-1].splitlines()[1:-1]]
    assert lines == [f'keystroke "{c}"' for c in "100,5"]
    for bad in ["7\n", "1e3", "", "12a", "1;2", '1"']:
        with pytest.raises(ValueError):
            type_number(bad, run=lambda args: calls.append(args) or "")
    assert len(calls) == 1
    clear_field(run=lambda args: calls.append(args) or "")
    assert "return" not in calls[-1][-1].lower() and "key code 36" not in calls[-1][-1]


@pytest.mark.parametrize(
    "point",
    [
        (0.5, 0.05),  # bilah alamat dan ekstensi Chrome
        (0.92, 0.50),  # Buy/Long
        (0.92, 0.61),  # Sell/Short
    ],
)
def test_tombol_order_dan_browser_di_zona_terlarang(point: tuple[float, float]) -> None:
    forbidden = lay.ALWAYS_FORBIDDEN + lay.CONTRACT_FORBIDDEN
    assert lay.in_zone(point, forbidden)


def test_kolom_quantity_dan_grafik_tidak_terlarang() -> None:
    forbidden = lay.ALWAYS_FORBIDDEN + lay.CONTRACT_FORBIDDEN
    assert not lay.in_zone((lay.QTY_CLICK_X, 0.345), forbidden)
    assert not lay.in_zone((0.068, 0.286), forbidden)  # tombol 15m


class _Nav:
    def __init__(self, symbol: str | None) -> None:
        self.symbol = symbol
        self.visits: list[str] = []
        self.prices = {"BTWUSDT": (2.50, 2.51), "TRUTHUSDT": (0.021, 0.0211)}

    def read_symbol(self) -> str:
        if self.symbol is None:
            raise WindowError("Jendela Tebbit belum dibuka")
        return self.symbol

    def prepare(self) -> None:
        self.visits.append("beranda")

    def open_symbol(self, symbol: str) -> str:
        self.visits.append(symbol)
        self.symbol = symbol
        return symbol

    def read_quote(self) -> tuple[float, float, float, float]:
        assert self.symbol is not None
        bid, ask = self.prices[self.symbol]
        return bid, ask, bid, 30.0


def test_harga_koin_lain_hanya_dibaca_saat_bot_bekerja_lalu_kembali() -> None:
    # Daftar posisi di aplikasi (browse mati): Chrome tidak dibuka, harga tidak terbaca.
    for nav in (_Nav(None), _Nav("OPUSDT")):
        with pytest.raises(MarketDataError):
            ScreenMarket(nav).quote("BTWUSDT")  # type: ignore[arg-type]
        assert nav.visits == []
    # Saat bot menilai OPUSDT: buka TRUTHUSDT sebentar untuk cek slot, lalu kembali ke OPUSDT.
    nav = _Nav("BTWUSDT")
    quote = ScreenMarket(nav, browse=True).quote("TRUTHUSDT")  # type: ignore[arg-type]
    assert (quote.bid, quote.ask, quote.funding_rate) == (0.021, 0.0211, 0.0)
    assert nav.visits == ["TRUTHUSDT", "BTWUSDT"]
    # Belum ada jendela (cek slot di awal putaran): siapkan Chrome dulu.
    nav = _Nav(None)
    ScreenMarket(nav, browse=True).quote("BTWUSDT")  # type: ignore[arg-type]
    assert nav.visits == ["beranda", "BTWUSDT"]
    with pytest.raises(NoHistoryError):
        ScreenMarket(nav).klines("BTWUSDT", "1m")  # type: ignore[arg-type]


def test_header_harga_dan_perubahan_walau_ocr_menyisipkan_spasi() -> None:
    from binance_bot.tebbit_web.screen_text import parse_header

    texts = ["24H Low", "24H High", "0.15384 + 11.35%", "OPUSDT Perpetual", "0.13448", "0.16230"]
    assert parse_header(texts) == (0.15384, 11.35)
    assert parse_header(["BTWUSDT Perpetual", "2.5528 +44.60%", "2.6047"]) == (2.5528, 44.6)
    assert parse_header(["1,234.5 -2.5%"]) == (1234.5, -2.5)


def test_header_without_a_readable_price_still_gives_the_change() -> None:
    import math

    from binance_bot.tebbit_web.screen_text import parse_header

    texts = ["24H Low", "16.98", "24H Volume(USDT)", "24H High", "+7.46%", "UVXYUSDT Perpetual"]
    price, change = parse_header(texts)
    assert change == 7.46 and math.isnan(price)  # harga header tidak dipakai SOP
    with pytest.raises(Exception, match="tidak terbaca"):
        parse_header(["24H Low", "16.98"])


def test_a_gainer_whose_name_is_unreadable_is_clicked_inside_its_row() -> None:
    """Bacaan nyata: nama Top 1 gagal terbaca. Klik harus di kolom nama, bukan margin kosong."""
    from binance_bot.macos import TextLine
    from binance_bot.tebbit_web.screen_text import parse_gainer_rows

    area = lay.LIST_ROWS_AREA
    lines = [
        TextLine("+21.58%", 0.775, 0.331),
        TextLine("S SKDDUSDT", 0.216, 0.393),
        TextLine("+20.06%", 0.775, 0.395),
        TextLine("S SQQQUSDT", 0.216, 0.456),
        TextLine("+10.39%", 0.774, 0.458),
    ]
    rows = parse_gainer_rows(lines, area)
    assert [row.symbol for row, _ in rows] == ["#1", "SKDDUSDT", "SQQQUSDT"]
    (_, first), (_, second) = rows[0], rows[1]
    assert first[0] == pytest.approx(second[0])  # kolom nama yang sama dengan baris lain
    assert first[0] > lay.FUTURES_NAME_X[0] + 0.1


def test_without_any_readable_name_the_row_is_clicked_on_its_change() -> None:
    from binance_bot.macos import TextLine
    from binance_bot.tebbit_web.screen_text import parse_gainer_rows

    area = lay.LIST_ROWS_AREA
    rows = parse_gainer_rows([TextLine("+21.58%", 0.775, 0.331)], area)
    x0, _, x1, _ = area
    assert rows[0][1][0] == pytest.approx(x0 + 0.775 * (x1 - x0))


def test_typed_leverage_is_read_with_or_without_the_x() -> None:
    from binance_bot.binance_desktop.navigator import _leverage_of

    assert _leverage_of("2") == 2  # Tebbit: angka dan "X" bisa terbaca terpisah
    assert _leverage_of("2X") == 2
    assert _leverage_of("— 2x +") == 2
    assert _leverage_of("11.500") is None  # harga order book bukan leverage
