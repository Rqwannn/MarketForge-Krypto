from pathlib import Path
from typing import Protocol

from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings


class Workflow(Protocol):
    """Satu alur otomasi yang dijalankan dari CLI. Alur baru cukup mengimplementasikan `run`."""

    name: str

    def run(self) -> None: ...


class TradingNavigator(Protocol):
    """Yang dibutuhkan alur SOP dari satu platform: membuka top gainers, koin, grafik, dan form.

    Navigator Binance (aplikasi desktop) dan Tebbit (website di Chrome) sama-sama memenuhinya;
    alur SOP, jurnal, dan mode banyak tidak tahu platform mana yang dipakai.
    """

    def prepare(self) -> None: ...

    def open_top_gainers(self) -> list[GainerRow]: ...

    def open_gainer(self, rank: int) -> str: ...

    def open_symbol(self, symbol: str) -> str: ...

    def show_15m_chart(self) -> None: ...

    def capture_window(self, path: Path) -> Path: ...

    def capture_chart(self, path: Path) -> Path: ...

    def read_margin_settings(self) -> MarginSettings: ...

    def fill_quantity(self, text: str) -> None: ...
