"""Bagian Tebbit yang bisa diuji tanpa Chrome: pola teks, pengetikan, dan zona terlarang."""

from __future__ import annotations

import pytest

from binance_bot.exceptions import MarketDataError, WindowError
from binance_bot.tebbit_web import layout_tebbit as lay
from binance_bot.tebbit_web.chrome import ChromeController
from binance_bot.tebbit_web.market import ScreenMarket
from binance_bot.tebbit_web.navigator import _FIFTEEN


@pytest.mark.parametrize("text", ["Time 1m 5m 15m", "5m 15ml", "15 m", "15m 30m"])
def test_tombol_15m_terbaca_walau_ocr_menempelkan_karakter(text: str) -> None:
    assert _FIFTEEN.search(text)


@pytest.mark.parametrize("text", ["Time 1m 5m", "1.5m", "115m", "30m 1H"])
def test_tombol_lain_bukan_15m(text: str) -> None:
    assert not _FIFTEEN.search(text)


def test_hanya_angka_yang_diketik_tanpa_enter() -> None:
    calls: list[list[str]] = []
    chrome = ChromeController(runner=lambda args: calls.append(args) or "")
    chrome.type_digits("100,5")
    script = calls[0][-1]
    assert [line.strip() for line in script.splitlines()[1:-1]] == [
        f'keystroke "{c}"' for c in "100,5"
    ]
    for bad in ["7\n", "1e3", "", "12a", "1;2"]:
        with pytest.raises(ValueError):
            chrome.type_digits(bad)
    assert len(calls) == 1


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

    def read_symbol(self) -> str:
        if self.symbol is None:
            raise WindowError("Jendela Tebbit belum dibuka")
        return self.symbol

    def read_quote(self) -> tuple[float, float, float, float]:
        return 0.99, 1.01, 1.0, 30.0


def test_harga_koin_lain_atau_sebelum_chrome_dibuka_tidak_terbaca() -> None:
    # Cek slot posisi terjadi sebelum Chrome dibuka: harus MarketDataError, bukan crash.
    for nav in (_Nav(None), _Nav("OPUSDT")):
        with pytest.raises(MarketDataError):
            ScreenMarket(nav).quote("BTWUSDT")  # type: ignore[arg-type]
    quote = ScreenMarket(_Nav("BTWUSDT")).quote("BTWUSDT")  # type: ignore[arg-type]
    assert (quote.bid, quote.ask, quote.change_pct, quote.funding_rate) == (0.99, 1.01, 30.0, 0.0)
