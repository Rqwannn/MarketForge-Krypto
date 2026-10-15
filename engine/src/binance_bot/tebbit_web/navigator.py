"""Navigator website Tebbit (tebbit.io) di Chrome. Alur dan antarmukanya sama dengan Binance.

Bot membuka jendela Chrome sendiri (sesi login Chrome pengguna terbawa), mengatur ukuran dan
zoom, memastikan jendelanya paling depan di layar, lalu bekerja lewat klik dan baca layar seperti
di Binance. Tombol Buy/Long, Sell/Short, dan menu akun berada di zona terlarang; hanya angka
yang diketik, tanpa Enter.
"""

from __future__ import annotations

import itertools
import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import replace

from binance_bot.binance_desktop.navigator import BinanceNavigator
from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings, same_number
from binance_bot.config import Settings
from binance_bot.exceptions import SafetyError, ScreenReadError, WindowError
from binance_bot.macos import AppController, Rect, TextReader
from binance_bot.tebbit_web import layout_tebbit as lay
from binance_bot.tebbit_web.chrome import (
    CHROME_BUNDLE_ID,
    CHROME_NAME,
    HOME_URL,
    ChromeController,
    ChromeWindowController,
)
from binance_bot.tebbit_web.pattern_rules import TEBBIT
from binance_bot.tebbit_web.screen_text import (
    contract_url,
    parse_gainer_rows,
    parse_header,
    parse_margin,
    parse_order_book,
    symbol_from_url,
)
from binance_bot.tebbit_web.visible import tab_window_is_visible

logger = logging.getLogger(__name__)

_GAINERS = re.compile(r"\bGainers\b")
_FUTURES = re.compile(r"\bFutures\b")
# OCR kadang menempelkan garis pemisah setelah tombol ("15ml"), jadi tanpa batas kata di kanan.
_FIFTEEN = re.compile(r"(?<![\d.])15\s*m", re.IGNORECASE)
_MARKET = re.compile(r"\bMarket\b")
_QUANTITY = re.compile(r"Quantity", re.IGNORECASE)
_LOGIN = re.compile(r"\b(Log\s*in|Sign\s*up|Register)\b", re.IGNORECASE)
_GUEST_PAGE = re.compile(r"Start a New Trading|Welcome to log in", re.IGNORECASE)
_MA_LABEL = re.compile(r"MA\s*\d+")
_CONTRACT_PATH = "/futures/contract/u_based/"
_PAGE_TIMEOUT_S = 25.0
_VERIFY_ATTEMPTS = 4


class TebbitNavigator(BinanceNavigator):
    def __init__(
        self,
        settings: Settings,
        apps: AppController,
        window: ChromeWindowController,
        reader: TextReader,
        chrome: ChromeController,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        screens: Callable[[], Sequence[Rect]],
    ) -> None:
        chrome_settings = replace(settings, app_name=CHROME_NAME, app_bundle_id=CHROME_BUNDLE_ID)
        super().__init__(
            chrome_settings, apps, window, reader, sleep=sleep, clock=clock, screens=screens
        )
        self._chrome = chrome
        self._chrome_window = window
        self._window_id: int | None = None
        self._rows: list[tuple[GainerRow, tuple[float, float]]] = []
        self._on_contract = False

    # ------------------------------------------------------------------ jendela
    def prepare(self) -> None:
        """Buka (atau pakai ulang) jendela Chrome Tebbit, atur ukuran dan zoom, lalu periksa."""
        if self._window_id is None or not self._chrome.window_exists(self._window_id):
            self._window_id = self._chrome.open_window(HOME_URL)
            logger.info("Jendela Chrome untuk Tebbit dibuka")
        self._chrome_window.window_id = self._window_id
        area = self._fit_area()
        self._chrome.set_bounds(self._window_id, area)
        self._chrome.raise_window(self._window_id)
        self._sleep(1.0)
        self._rect = self._chrome.bounds(self._window_id)
        self._ensure_front()
        self._chrome.set_zoom(lay.ZOOM_STEPS_DOWN)
        self._sleep(1.0)
        self._on_contract = False
        self._load(HOME_URL)
        self._check_page()

    def _fit_area(self) -> Rect:
        areas = list(self._screens())
        want_w, want_h = lay.EXPECTED_WINDOW
        for area in areas:
            if area.width >= lay.MIN_WINDOW[0] and area.height >= lay.MIN_WINDOW[1]:
                return Rect(area.x, area.y, min(area.width, want_w), min(area.height, want_h))
        raise WindowError(
            f"Layar terlalu kecil untuk Tebbit (butuh minimal {lay.MIN_WINDOW[0]}x"
            f"{lay.MIN_WINDOW[1]} pt di luar menu bar dan Dock)."
        )

    def _check_page(self) -> None:
        """Halaman Tebbit termuat, zoom 80%, dan akun sudah login (jangkar teks di menu atas)."""
        deadline = self._clock() + _PAGE_TIMEOUT_S
        scrolled_up = False
        while (found := self._find_text(lay.NAV_FUTURES_AREA, _FUTURES)) is None:
            if self._clock() >= deadline:
                self._raise_if_logged_out()  # layar login menutupi menu: jangan salah sebut
                raise ScreenReadError("Halaman Tebbit belum termuat (menu 'Futures' tidak terbaca)")
            if not scrolled_up and self._clock() >= deadline - _PAGE_TIMEOUT_S / 2:
                # Chrome bisa memulihkan posisi gulir halaman sebelumnya: menu atas tidak terlihat.
                self._ensure_front()
                for _ in range(3):
                    self._window.scroll_up(*self.rect.point_at(*lay.SCROLL_POINT))
                scrolled_up = True
            self._sleep(1.0)
        x = found[0]
        if abs(x - lay.NAV_FUTURES_X) > lay.NAV_FUTURES_TOLERANCE:
            raise ScreenReadError(
                f"Zoom Chrome tidak 80% (menu Futures di x={x:.2f}, seharusnya "
                f"{lay.NAV_FUTURES_X}). Atur zoom ke 80% lalu ulangi."
            )
        self._raise_if_logged_out()

    def _raise_if_logged_out(self) -> None:
        top = self._read_texts(self.rect.sub(0.0, 0.10, 1.0, 0.17))
        page = self._read_texts(self.rect.sub(0.0, 0.10, 1.0, 0.95))
        # Sesi kedaluwarsa: tombol Login, popup login, atau halaman tamu tanpa menu sama sekali.
        if any(_LOGIN.search(text) or _GUEST_PAGE.search(text) for text in top + page):
            raise ScreenReadError(
                "Sesi Tebbit sudah keluar (belum login). Login lagi di Chrome, lalu ulangi."
            )

    def close(self) -> None:
        """Tutup jendela Chrome milik bot."""
        if self._window_id is not None:
            self._chrome.close_window(self._window_id)
            self._window_id = None

    # ------------------------------------------------------------------ keamanan
    def _forbidden(self, target: tuple[float, float]) -> bool:
        if lay.in_zone(target, lay.ALWAYS_FORBIDDEN):
            return True
        return self._on_contract and lay.in_zone(target, lay.CONTRACT_FORBIDDEN)

    def _ensure_front(self) -> None:
        """Chrome di depan DAN jendela Tebbit benar-benar tampil di layar (bukan Desktop lain).

        Tanpa ini, tangkapan atau klik pada area jendela bisa mengenai aplikasi lain.
        """
        if self._window_id is None:
            raise WindowError("Panggil prepare() sebelum navigasi")
        super()._ensure_front()
        rect = self._chrome.bounds(self._window_id)
        if not tab_window_is_visible(rect):
            self._chrome.raise_window(self._window_id)
            self._sleep(1.0)
            if not tab_window_is_visible(rect):
                raise SafetyError(
                    "Jendela Tebbit tidak tampil di layar (tertutup atau di Desktop lain): "
                    "tangkapan dan klik dibatalkan."
                )

    def _load(self, url: str) -> None:
        assert self._window_id is not None
        self._chrome.open_url(self._window_id, url)
        self._sleep(self._settings.settle_delay_s + 1.0)

    # ------------------------------------------------------------------ daftar gainers
    def open_top_gainers(self) -> list[GainerRow]:
        """Halaman depan > gulir > tab Gainers > Futures; baca 5 baris teratas."""
        self._on_contract = False
        self._load(HOME_URL)
        gainers = self._scroll_until(_GAINERS, lay.LIST_SEARCH_AREA)
        self._click(gainers)
        futures = self._find_below(_FUTURES, gainers[1])
        if futures is None:
            raise ScreenReadError("Sub-tab 'Futures' di daftar Gainers Tebbit tidak ditemukan")
        self._click(futures)
        self._sleep(self._settings.settle_delay_s)
        rows = self._read_rows()
        if len(rows) < 2 or not _descending(rows):
            raise ScreenReadError(
                f"Daftar Futures Gainers tidak terbaca atau tidak terurut ({len(rows)} baris)"
            )
        self._rows = rows
        return [row for row, _ in rows]

    def read_top_gainers(self) -> list[GainerRow]:
        return [row for row, _ in self._read_rows()]

    def _read_rows(self) -> list[tuple[GainerRow, tuple[float, float]]]:
        area = lay.LIST_ROWS_AREA
        return parse_gainer_rows(self._read_lines(self.rect.sub(*area)), area)

    def _scroll_until(
        self, pattern: re.Pattern[str], area: tuple[float, float, float, float]
    ) -> tuple[float, float]:
        for _ in range(lay.SCROLL_STEPS):
            found = self._find_text(area, pattern)
            if found is not None:
                return found
            self._ensure_front()
            self._window.scroll_down(*self.rect.point_at(*lay.SCROLL_POINT), lay.SCROLL_NOTCHES)
            self._sleep(1.0)
        raise ScreenReadError("Tab 'Gainers' di halaman depan Tebbit tidak ditemukan")

    def _find_below(self, pattern: re.Pattern[str], below_y: float) -> tuple[float, float] | None:
        x0, y0, _x1, y1 = lay.LIST_SEARCH_AREA
        top = max(y0, below_y + 0.01)
        return self._find_text((x0, top, 0.5, min(y1, top + 0.15)), pattern)

    # ------------------------------------------------------------------ halaman koin
    def open_gainer(self, rank: int) -> str:
        """Klik baris `rank` di daftar, lalu baca nama koin dari alamat halaman."""
        row = next((click for r, click in self._rows if r.rank == rank), None)
        if row is None:
            raise ScreenReadError(f"Baris Top {rank} tidak terbaca di daftar Gainers")
        self._click(row)
        symbol = self._wait_contract()
        logger.info("Top gainer #%d: %s", rank, symbol)
        return symbol

    def open_symbol(self, symbol: str) -> str:
        """Buka koin langsung lewat alamatnya (untuk pengikut: koin yang sama dengan pemimpin)."""
        self._on_contract = False
        self._load(contract_url(symbol))
        opened = self._wait_contract()
        if opened != symbol:
            raise ScreenReadError(
                f"{symbol} tidak tersedia sebagai kontrak di Tebbit (yang terbuka: {opened})"
            )
        return opened

    def _wait_contract(self) -> str:
        assert self._window_id is not None
        deadline = self._clock() + _PAGE_TIMEOUT_S
        while True:
            url = self._chrome.current_url(self._window_id)
            if _CONTRACT_PATH in url:
                break
            if self._clock() >= deadline:
                raise ScreenReadError(f"Halaman koin Tebbit tidak terbuka (alamat: {url})")
            self._sleep(1.0)
        self._on_contract = True
        self._sleep(self._settings.settle_delay_s)
        return symbol_from_url(url)

    def read_symbol(self) -> str:
        if self._window_id is None:
            raise WindowError("Jendela Tebbit belum dibuka")
        return symbol_from_url(self._chrome.current_url(self._window_id))

    def show_15m_chart(self) -> None:
        """Klik tombol 15m di grafik, lalu tunggu legenda MA muncul."""
        deadline = self._clock() + _PAGE_TIMEOUT_S
        # Toolbar grafik baru tampil beberapa detik setelah halaman koin terbuka.
        while (found := self._find_text(lay.TIMEFRAME_AREA, _FIFTEEN)) is None:
            if self._clock() >= deadline:
                raise ScreenReadError("Tombol '15m' tidak ditemukan di halaman koin Tebbit")
            self._sleep(1.0)
        self._click(found)
        deadline = self._clock() + _PAGE_TIMEOUT_S
        while True:
            legend = " ".join(self._read_texts(self.rect.sub(*lay.LEGEND_AREA)))
            if _MA_LABEL.search(legend):
                break
            if self._clock() >= deadline:
                raise ScreenReadError("Grafik 15 menit Tebbit belum termuat (legenda MA tidak ada)")
            self._sleep(1.0)
        # Baseline Tebbit (MA 5/10/30) dipakai apa adanya; indikator grafik tidak diubah bot.
        periods = {int(n) for n in re.findall(r"MA\s*(\d+)", legend)}
        if not TEBBIT.legend_ready(periods):
            raise ScreenReadError(
                f"Indikator MA di grafik Tebbit {sorted(periods)}; aturan Tebbit memakai "
                f"{TEBBIT.baseline}. Kembalikan indikator koin ini ke bawaan Tebbit."
            )

    def _chart_area(self) -> Rect:
        return self.rect.sub(*lay.CHART_AREA)

    # ------------------------------------------------------------------ form dan data
    def read_margin_settings(self) -> MarginSettings:
        return parse_margin(self._read_texts(self.rect.sub(*lay.MARGIN_AREA)))

    def read_quote(self) -> tuple[float, float, float, float]:
        """(bid, ask, harga terakhir, perubahan 24 jam %) dari halaman koin yang terbuka."""
        price, change = parse_header(self._read_texts(self.rect.sub(*lay.HEADER_AREA)))
        area = lay.ORDERBOOK_AREA
        bid, ask = parse_order_book(self._read_lines(self.rect.sub(*area)), area)
        return bid, ask, price, change

    def fill_quantity(self, text: str) -> None:
        """Isi kolom Quantity (satuan USDT) pada tab Market, lalu cek angkanya dengan OCR.

        Hanya mengetik angka. Tidak menekan Enter dan tidak menekan tombol order.
        """
        if not self._on_contract:
            raise SafetyError("Kolom Quantity hanya diisi di halaman koin")
        market = self._find_text(lay.ORDER_TAB_AREA, _MARKET)
        if market is None:
            raise ScreenReadError("Tab 'Market' di form order Tebbit tidak ditemukan")
        self._click(market)
        quantity = self._find_text(lay.ORDER_FORM_AREA, _QUANTITY)
        if quantity is None:
            raise ScreenReadError("Kolom 'Quantity' di form order Tebbit tidak ditemukan")
        shown_before = " ".join(self._read_texts(self.rect.sub(*lay.ORDER_FORM_AREA)))
        if "USDT" not in shown_before:
            raise ScreenReadError(
                "Satuan kolom Quantity bukan USDT. Di Tebbit pilih satuan USDT pada kolom itu."
            )
        self._click((lay.QTY_CLICK_X, quantity[1]))
        self._ensure_front()
        self._window.clear_field()
        self._window.type_number(text)
        self._sleep(self._settings.settle_delay_s / 2)
        shown: list[str] = []
        for attempt in range(_VERIFY_ATTEMPTS):
            shown = self._read_texts(self.rect.sub(*lay.ORDER_FORM_AREA))
            if any(same_number(value, text) for value in shown):
                break
            if attempt + 1 < _VERIFY_ATTEMPTS:
                self._sleep(0.4)
        else:
            raise ScreenReadError(f"Kolom Quantity menampilkan {shown}, bukan {text}")
        logger.info("Kolom Quantity terisi: %s USDT", text)


def _descending(rows: Sequence[tuple[GainerRow, tuple[float, float]]]) -> bool:
    changes = [row.change_pct for row, _ in rows]
    return all(a >= b for a, b in itertools.pairwise(changes))
