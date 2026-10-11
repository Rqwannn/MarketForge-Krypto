"""Navigasi Binance Desktop untuk SOP: Pasar -> Futures -> Top Gainers -> halaman trade.

Semua klik lewat `_click`, yang menolak klik ke zona tombol order di halaman trade. Bot hanya
mengklik navigasi dan mengisi kolom angka; tombol beli/short tidak pernah ditekan.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.screen_text import (
    GainerRow,
    MarginSettings,
    is_sorted_by_top_gain,
    parse_futures_symbol,
    parse_gainer_rows,
    parse_margin,
    same_number,
)
from binance_bot.config import Settings
from binance_bot.exceptions import (
    AppNotRunningError,
    SafetyError,
    ScreenReadError,
    WindowError,
)
from binance_bot.macos import (
    AppController,
    Rect,
    TextLine,
    TextReader,
    WindowController,
    wait_for_window,
    wait_until_frontmost,
)

logger = logging.getLogger(__name__)

_SORT_ATTEMPTS = 3


class BinanceNavigator:
    def __init__(
        self,
        settings: Settings,
        apps: AppController,
        window: WindowController,
        reader: TextReader,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._apps = apps
        self._window = window
        self._reader = reader
        self._sleep = sleep
        self._clock = clock
        self._rect: Rect | None = None
        self._on_trade_page = False

    def prepare(self) -> None:
        """Bawa Binance ke depan dan pastikan ukuran jendela sesuai kalibrasi posisi klik."""
        settings = self._settings
        if not self._apps.is_running(settings.app_bundle_id):
            raise AppNotRunningError(
                f"{settings.app_name} belum berjalan. Jalankan `binance-bot open`, "
                "login manual, lalu ulangi."
            )
        # `open -b` pada aplikasi yang sudah berjalan hanya membawanya ke depan.
        self._apps.launch(settings.app_bundle_id)
        wait_until_frontmost(
            self._apps,
            settings.app_bundle_id,
            timeout_s=settings.launch_timeout_s,
            interval_s=settings.poll_interval_s,
            sleep=self._sleep,
            clock=self._clock,
        )
        rect = wait_for_window(
            self._window,
            settings.app_name,
            timeout_s=settings.launch_timeout_s,
            interval_s=settings.poll_interval_s,
            sleep=self._sleep,
            clock=self._clock,
        )
        want_w, want_h = layout.EXPECTED_WINDOW
        tol = layout.WINDOW_TOLERANCE
        if abs(rect.width - want_w) > want_w * tol or abs(rect.height - want_h) > want_h * tol:
            raise WindowError(
                f"Ukuran jendela {rect.width}x{rect.height} berbeda dari {want_w}x{want_h} "
                "yang dipakai untuk mengukur posisi klik. Atur ulang ukuran jendela Binance "
                "atau ukur ulang posisi di binance_desktop/layout.py."
            )
        self._rect = rect

    def open_top_gainers(self) -> list[GainerRow]:
        """Pasar -> tab Futures -> urutkan "Perubahan 24jam" dari kenaikan tertinggi.

        Arah urutan diperiksa dengan OCR, bukan ditebak dari jumlah klik.
        """
        self._click(layout.SIDEBAR_MARKET)
        self._on_trade_page = False
        self._click(layout.MARKET_FUTURES_TAB)
        rows: list[GainerRow] = []
        for _ in range(_SORT_ATTEMPTS):
            self._click(layout.FUTURES_CHANGE_HEADER)
            rows = self.read_top_gainers()
            if is_sorted_by_top_gain(rows):
                return rows
        raise ScreenReadError(
            f"Daftar Futures tidak terurut dari kenaikan tertinggi setelah {_SORT_ATTEMPTS} "
            f"klik (terbaca: {[(r.symbol, r.change_pct) for r in rows[:3]]})"
        )

    def read_top_gainers(self) -> list[GainerRow]:
        area = layout.FUTURES_LIST_AREA
        return parse_gainer_rows(self._read_lines(self.rect.sub(*area)), area)

    def open_gainer(self, rank: int) -> str:
        """Buka halaman trade Futures baris `rank`. Mengembalikan pair yang benar-benar terbuka.

        Peringkat bisa bergeser dalam hitungan detik, jadi pair dibaca ulang di halaman trade.
        """
        self._click(layout.trade_icon(rank))
        self._on_trade_page = True
        symbol = self.read_symbol()
        logger.info("Top gainer #%d: %s", rank, symbol)
        return symbol

    def read_symbol(self) -> str:
        return parse_futures_symbol(self._read_texts(self.rect.sub(*layout.SYMBOL_AREA)))

    def show_15m_chart(self) -> None:
        self._click(layout.TIMEFRAME_15M)

    def read_margin_settings(self) -> MarginSettings:
        return parse_margin(self._read_texts(self.rect.sub(*layout.MARGIN_AREA)))

    def fill_quantity(self, text: str) -> None:
        """Isi kolom "Jumlah" pada form market order, lalu pastikan angkanya tampil dengan OCR.

        Hanya mengetik angka. Tidak menekan Enter dan tidak menekan tombol order.
        """
        if not self._on_trade_page:
            raise SafetyError("Kolom Jumlah hanya diisi di halaman trade")
        self._click(layout.ORDER_TAB_MARKET)
        self._click(layout.ORDER_QTY_FIELD)
        self._window.clear_field()
        self._window.type_number(text)
        self._sleep(self._settings.settle_delay_s / 2)
        shown = self._read_texts(self.rect.sub(*layout.ORDER_QTY_AREA))
        if not any(same_number(value, text) for value in shown):
            raise ScreenReadError(f"Kolom Jumlah menampilkan {shown}, bukan {text}")
        logger.info("Kolom Jumlah terisi: %s", text)

    def capture_window(self, path: Path) -> Path:
        return self._capture(self.rect, path)

    def capture_chart(self, path: Path) -> Path:
        return self._capture(self.rect.sub(*layout.CHART_AREA), path)

    @property
    def rect(self) -> Rect:
        if self._rect is None:
            raise WindowError("Panggil prepare() sebelum navigasi")
        return self._rect

    def _click(self, target: tuple[float, float]) -> None:
        if self._on_trade_page and layout.in_order_button_zone(target):
            raise SafetyError(f"Klik ke zona tombol order ditolak: {target}")
        self._window.click(*self.rect.point_at(*target))
        self._sleep(self._settings.settle_delay_s)

    def _capture(self, area: Rect, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._window.capture(area, path)
        logger.info("Tangkapan layar disimpan: %s", path)
        return path

    def _read_lines(self, area: Rect) -> list[TextLine]:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "ocr.png"
            self._window.capture(area, image)
            return self._reader.read_lines(image)

    def _read_texts(self, area: Rect) -> list[str]:
        return [line.text for line in self._read_lines(area)]
