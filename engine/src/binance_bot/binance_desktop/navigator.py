"""Navigasi Binance Desktop untuk SOP: Pasar -> Futures -> Top Gainers -> halaman trade.

Semua klik lewat `_click`, yang menolak klik ke zona tombol order di halaman trade. Bot hanya
mengklik navigasi dan mengisi kolom angka; tombol beli/short tidak pernah ditekan.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from collections.abc import Callable, Sequence
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
    AppTimeoutError,
    SafetyError,
    ScreenReadError,
    WindowError,
)
from binance_bot.logging_setup import event
from binance_bot.macos import (
    AppController,
    Rect,
    TextLine,
    TextReader,
    WindowController,
    wait_for_window,
    wait_until_frontmost,
)
from binance_bot.macos.screens import visible_areas
from binance_bot.strategy.execution import LIVE_ORDERS_ENABLED, OrderPlan
from binance_bot.tebbit_web.visible import OnScreenWindow, front_owner_at

logger = logging.getLogger(__name__)

_SORT_ATTEMPTS = 4
_OPEN_SYMBOL_ATTEMPTS = 2  # buka ulang lewat nama bila daftar bergeser saat diklik
_VERIFY_ATTEMPTS = 4
_FRONT_ATTEMPTS = 5
_FRONT_WAIT_S = 3.0
_VERIFY_RETRY_DELAY_S = 0.4
_CHART_TAB = re.compile(r"\bGrafik\b")
_FUTURES_TAB = re.compile(r"\bFutures\b")
_CHANGE_HEADER = re.compile(r"Perubahan")
_MARKET_MENU = re.compile(r"^\s*Pasar\s*$", re.IGNORECASE)
_UNIT_MENU_TITLE = re.compile(r"Preferensi\s*Unit|^\s*Unit\s*$")
_UNIT_MENU_USDT = re.compile(r"dalam\s+USDT", re.IGNORECASE)
# OCR membaca lingkaran radio sebagai huruf ("C. Ukuran Order"); huruf besar membedakannya dari
# keterangan "...ukuran order dalam USDT".
_UNIT_RADIO = re.compile(r"Ukuran\s*Order")
_ACTION_HEADER = re.compile(r"Tindakan", re.IGNORECASE)
_EXTRA_SCROLL_SHIFT = 0.05  # banner setinggi ini atau lebih: gulir satu langkah lagi
_FIFTEEN_MINUTES = re.compile(r"\b15\s*mnt\b")
_MA7_LABEL = re.compile(r"MA\s*\(\s*7\s*\)")
_USDT_UNIT = re.compile(r"\bUSDT\b")
_MARGIN_MODE = re.compile(r"Margin\s*Awal", re.IGNORECASE)
_SHORT_BUTTON = re.compile(r"(Jual|Sell)\s*/\s*Short", re.IGNORECASE)
_CHART_LOAD_TIMEOUT_S = 25.0  # aplikasi bisa lambat memuat grafik


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
        screens: Callable[[], Sequence[Rect]] = visible_areas,
        windows: Callable[[], Sequence[OnScreenWindow]] | None = None,
    ) -> None:
        self._settings = settings
        # Daftar jendela yang tampil (depan ke belakang). None = tidak diperiksa (tes).
        self._windows = windows
        self._apps = apps
        self._window = window
        self._reader = reader
        self._sleep = sleep
        self._clock = clock
        self._screens = screens
        self._rect: Rect | None = None
        self._on_trade_page = False
        self._chart_shift = 0.0  # pergeseran vertikal tata letak halaman trade (relatif jendela)
        self._list_shift = 0.0  # pergeseran daftar top gainer akibat banner di halaman Pasar
        self._header_pos: tuple[float, float] = layout.FUTURES_CHANGE_HEADER
        self._icon_x = layout.FUTURES_TRADE_ICON_X  # x ikon trade (dicari dengan OCR bila bisa)
        self._row_y: dict[int, float] = {}  # y baris top gainer yang terbaca di layar
        self._list_rows: list[GainerRow] = []  # daftar top gainers yang terakhir dibaca
        self._away = False  # layar sedang diserahkan ke aplikasi MarketForge (show_app)
        self._on_list = False  # bot sedang di daftar (belum membuka halaman koin)
        self._unit_menu_click = (
            False  # True hanya saat memilih satuan USDT (lihat _click_in_unit_menu)
        )

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
        self._rect = self._fit_window(rect)

    def _fit_window(self, rect: Rect) -> Rect:
        """Atur jendela Binance ke ukuran kalibrasi posisi klik, di dalam area layar.

        Binance mengubah susunan tampilannya mengikuti ukuran jendela, jadi posisi klik hanya
        benar pada ukuran kalibrasi. Bila layar terlalu kecil, berhenti tanpa mengklik.
        """
        areas = self._screens()
        if layout.window_ready(rect, areas):
            return rect
        target = layout.window_target(rect, areas)
        if target is None:
            raise WindowError(layout.screen_too_small(areas))
        app = self._settings.app_name
        logger.info(
            "Jendela %s diatur dari %dx%d ke %dx%d",
            app,
            rect.width,
            rect.height,
            target.width,
            target.height,
        )
        self._window.set_bounds(app, target)
        self._sleep(self._settings.settle_delay_s)
        rect = self._window.bounds(app)
        problem = layout.window_size_problem(rect.width, rect.height)
        if problem:
            raise WindowError(
                f"{problem} Pengaturan otomatis tidak berhasil; keluarkan Binance dari mode "
                "layar penuh lalu coba lagi."
            )
        return rect

    def open_top_gainers(self) -> list[GainerRow]:
        """Pasar -> tab Futures -> urutkan "Perubahan 24jam" dari kenaikan tertinggi.

        Arah urutan diperiksa dengan OCR, bukan ditebak dari jumlah klik. Banner promo di halaman
        Pasar menggeser tab dan daftar; bila layout mengaktifkannya, posisi keduanya dicari dengan
        OCR.
        """
        self._click(self._market_menu_position())
        self._on_trade_page = False
        self._row_y = {}
        self._open_futures_list()
        rows: list[GainerRow] = []
        for _ in range(_SORT_ATTEMPTS):
            self._click(self._header_pos)
            rows = self.read_top_gainers()
            if is_sorted_by_top_gain(rows):
                self._list_rows = rows
                self._on_list = True
                return rows
            if not rows:
                # Daftar Futures belum tampil (halaman lambat dimuat, klik tab hilang): ulangi.
                self._reopen_futures_tab()
        shot = self._save_debug_shot("daftar-futures")
        raise ScreenReadError(
            f"Daftar Futures tidak terurut dari kenaikan tertinggi setelah {_SORT_ATTEMPTS} "
            f"klik (terbaca: {[(r.symbol, r.change_pct) for r in rows[:3]]}). "
            f"Foto layar yang dilihat bot: {shot}"
        )

    def _save_debug_shot(self, name: str) -> Path | str:
        """Simpan foto jendela saat pembacaan gagal, agar admin tahu apa yang dilihat bot."""
        try:
            folder = self._settings.screenshot_dir
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            return self.capture_window(folder / f"gagal-{name}-{stamp}.png")
        except Exception:  # diagnosa tidak boleh menutupi galat aslinya
            logger.debug("Foto layar diagnosa gagal disimpan", exc_info=True)
            return "(tidak tersimpan)"

    def _market_menu_position(self) -> tuple[float, float]:
        """Posisi menu "Pasar" di sidebar: dicari dengan OCR, atau posisi tetap bila tak terbaca."""
        if layout.SIDEBAR_AREA is None:
            return layout.SIDEBAR_MARKET
        found = self._find_text(layout.SIDEBAR_AREA, _MARKET_MENU)
        if found is None:
            logger.warning("Menu Pasar tidak terbaca di sidebar; memakai posisi tetap")
            return layout.SIDEBAR_MARKET
        return found

    def _futures_tab_position(self) -> tuple[float, float]:
        """Posisi tab Futures: dicari dengan OCR (banner bisa menggesernya), atau posisi tetap."""
        if layout.MARKET_TABS_AREA is None:
            return layout.MARKET_FUTURES_TAB
        found = self._find_text(layout.MARKET_TABS_AREA, _FUTURES_TAB)
        if found is None:
            logger.warning("Tab Futures tidak terbaca di halaman Pasar; memakai posisi tetap")
            return layout.MARKET_FUTURES_TAB
        return found

    def _open_futures_list(self) -> None:
        """Buka tab Futures, gulir, lalu cari judul kolom untuk mengetahui pergeseran daftar."""
        tab = self._futures_tab_position()
        shift = tab[1] - layout.MARKET_FUTURES_TAB[1] if layout.MARKET_TABS_AREA else 0.0
        self._click(tab)
        notches = layout.FUTURES_LIST_SCROLL_NOTCHES
        if notches and shift > _EXTRA_SCROLL_SHIFT:
            notches += 1  # banner mendorong daftar ke bawah: gulir lebih jauh agar 5 baris terlihat
        self._scroll_futures_list(notches)
        self._locate_list()
        if layout.FUTURES_USDM_TAB:
            self._click(self._shifted(layout.FUTURES_USDM_TAB))

    def _locate_list(self) -> None:
        """Cari judul kolom "Perubahan" untuk tahu seberapa jauh daftar bergeser dari kalibrasi."""
        self._list_shift = 0.0
        self._header_pos = layout.FUTURES_CHANGE_HEADER
        self._icon_x = layout.FUTURES_TRADE_ICON_X
        if layout.FUTURES_ACTION_AREA is not None:
            action = self._find_text(layout.FUTURES_ACTION_AREA, _ACTION_HEADER)
            if action is None:
                logger.warning("Judul kolom Tindakan tidak terbaca; memakai posisi ikon tetap")
            else:
                self._icon_x = min(0.999, action[0] + layout.FUTURES_TRADE_ICON_DX)
        if layout.FUTURES_HEADER_AREA is None:
            return
        found = self._find_text(layout.FUTURES_HEADER_AREA, _CHANGE_HEADER)
        if found is None:
            logger.warning("Judul kolom Perubahan tidak terbaca; memakai posisi tetap")
            return
        self._header_pos = found
        self._list_shift = found[1] - layout.FUTURES_CHANGE_HEADER[1]
        if abs(self._list_shift) > 0.005:
            logger.info(
                "Daftar Futures bergeser %+.0f px dari kalibrasi",
                self._list_shift * self.rect.height,
            )

    def _shifted(self, target: tuple[float, float]) -> tuple[float, float]:
        return target[0], min(0.999, max(0.0, target[1] + self._list_shift))

    def _scroll_futures_list(self, notches: int) -> None:
        """Gulir halaman Pasar bila tata letak butuh (agar 5 baris pertama terlihat)."""
        if notches:
            self._window.scroll_down(
                *self.rect.point_at(*layout.FUTURES_LIST_SCROLL_POINT), notches
            )
            self._sleep(self._settings.settle_delay_s)

    def _reopen_futures_tab(self) -> None:
        if layout.FUTURES_LIST_SCROLL_NOTCHES:
            # Halaman sudah tergulir: tab Futures tidak lagi di tempat semula. Muat ulang
            # halaman Pasar agar posisi gulir kembali ke awal.
            self._click(self._market_menu_position())
        self._open_futures_list()

    def read_top_gainers(self) -> list[GainerRow]:
        x0, y0, x1, y1 = layout.FUTURES_LIST_AREA
        shift = self._list_shift
        area = (x0, max(0.0, y0 + shift), x1, min(1.0, y1 + shift))
        rows = parse_gainer_rows(self._read_lines(self.rect.sub(*area)), area, shift)
        self._row_y = {row.rank: row.y for row in rows if row.y is not None}
        return rows

    def open_gainer(self, rank: int) -> str:
        """Buka halaman trade Futures baris `rank`. Mengembalikan pair yang benar-benar terbuka.

        Peringkat bisa bergeser dalam hitungan detik, jadi pair dibaca ulang di halaman trade.
        """
        self._click(self._trade_icon(rank))
        self._on_trade_page = True
        self._on_list = False
        self._chart_shift = 0.0
        try:
            symbol = self.read_symbol()
        except ScreenReadError as exc:
            shot = self._save_debug_shot("halaman-trade")
            raise ScreenReadError(f"{exc} Foto layar yang dilihat bot: {shot}") from exc
        logger.info("Top gainer #%d: %s", rank, symbol)
        return symbol

    def open_symbol(self, symbol: str) -> str:
        """Buka koin lewat namanya dari daftar top gainers SAAT INI.

        Daftar Binance berubah urutan dalam hitungan detik: klik baris ke-N bisa membuka koin lain
        (mis. koin yang sama dua kali, dan koin ke-N hilang tak tertangani). Daftar dibaca ulang
        bila bot sedang tidak di daftar, lalu baris koin yang dimaksud dicari dengan namanya.
        """
        opened = ""
        for _attempt in range(_OPEN_SYMBOL_ATTEMPTS):
            rows = self._list_rows if self._on_list else self.open_top_gainers()
            rank = next((row.rank for row in rows if row.symbol == symbol), None)
            if rank is None:
                raise ScreenReadError(f"{symbol} sudah tidak di daftar top gainers")
            if rank > layout.MAX_RANK:
                raise ScreenReadError(f"{symbol} sudah bergeser ke peringkat {rank}, di luar Top 5")
            opened = self.open_gainer(rank)
            if opened == symbol:
                return opened
            # Daftar bergeser di antara dibaca dan diklik (hitungan detik): baca ulang, coba lagi.
            logger.info("Yang terbuka %s, bukan %s: daftar dibaca ulang", opened, symbol)
        raise ScreenReadError(f"Yang terbuka {opened}, bukan {symbol} (peringkat terus bergeser)")

    def _trade_icon(self, rank: int) -> tuple[float, float]:
        """Titik ikon trade baris `rank`.

        Baris yang terbaca OCR dipakai langsung (tinggi baris berbeda di tiap laptop); baris yang
        tidak terbaca diperkirakan dari baris lain yang terbaca, atau dari posisi kalibrasi.
        """
        fixed_x, fixed_y = layout.trade_icon(rank)
        if self._row_y:
            if rank in self._row_y:
                return self._icon_x, self._row_y[rank]
            known = sorted(self._row_y.items())
            step = layout.FUTURES_ROW_STEP
            if len(known) >= 2:
                (r0, y0), (r1, y1) = known[0], known[-1]
                step = (y1 - y0) / (r1 - r0)
            near, near_y = min(known, key=lambda item: abs(item[0] - rank))
            return self._icon_x, min(0.999, near_y + (rank - near) * step)
        x = self._icon_x if layout.FUTURES_ACTION_AREA else fixed_x
        return x, self._shifted((fixed_x, fixed_y))[1]

    def read_symbol(self) -> str:
        return parse_futures_symbol(self._read_texts(self.rect.sub(*layout.SYMBOL_AREA)))

    def show_15m_chart(self) -> None:
        """Klik tab "Grafik" lalu tombol "15 mnt", keduanya dicari dengan OCR.

        Banner di halaman koin tertentu (mis. pemberitahuan nama koin "S") menggeser tata letak
        ke bawah, sehingga posisi tetap bisa mengenai tab lain. Pergeseran yang terdeteksi juga
        dipakai untuk memotong area grafik.
        """
        chart_tab = self._find_text(layout.CHART_TOOLBAR_AREA, _CHART_TAB)
        if chart_tab is not None:
            self._click(chart_tab)
        button = self._find_text(layout.CHART_TOOLBAR_AREA, _FIFTEEN_MINUTES)
        if button is None:
            raise ScreenReadError("Tombol '15 mnt' tidak ditemukan di halaman trade")
        self._click(button)
        self._chart_shift = button[1] - layout.TIMEFRAME_15M[1]
        self._wait_for_chart()

    def _wait_for_chart(self) -> None:
        """Tunggu grafik selesai dimuat (label "MA(7)" terbaca), bukan animasi loading."""
        deadline = self._clock() + _CHART_LOAD_TIMEOUT_S
        while True:
            if any(_MA7_LABEL.search(line.text) for line in self._read_lines(self._chart_area())):
                return
            if self._clock() >= deadline:
                raise ScreenReadError(
                    f"Grafik 15 menit belum termuat setelah {_CHART_LOAD_TIMEOUT_S:g} detik"
                )
            self._sleep(1.0)

    def _chart_area(self) -> Rect:
        x0, y0, x1, y1 = layout.CHART_AREA
        shift = self._chart_shift
        return self.rect.sub(x0, y0 + shift, x1, min(1.0, y1 + shift))

    def read_margin_settings(self) -> MarginSettings:
        return parse_margin(self._read_texts(self.rect.sub(*layout.MARGIN_AREA)))

    def fill_quantity(self, text: str) -> None:
        """Isi kolom "Jumlah" (ukuran order USDT) pada form market order, lalu cek dengan OCR.

        Satuan kolom harus USDT dengan mode "Ukuran Order"; bila tidak, berhenti tanpa mengetik.
        Hanya mengetik angka. Tidak menekan Enter dan tidak menekan tombol order.
        """
        if not self._on_trade_page:
            raise SafetyError("Kolom Jumlah hanya diisi di halaman trade")
        self._click(layout.ORDER_TAB_MARKET)
        self._ensure_usdt_unit()
        self._check_order_unit()
        self._click(layout.ORDER_QTY_FIELD)
        self._ensure_front()  # ketikan angka hanya boleh masuk ke Binance
        self._window.clear_field()
        self._window.type_number(text)
        self._sleep(self._settings.settle_delay_s / 2)
        shown: list[str] = []
        for attempt in range(_VERIFY_ATTEMPTS):
            shown = self._read_texts(self.rect.sub(*layout.ORDER_QTY_AREA))
            if any(same_number(value, text) for value in shown):
                break
            if attempt + 1 < _VERIFY_ATTEMPTS:
                # Kursor berkedip di samping angka dan sesekali mengganggu OCR: baca ulang.
                self._sleep(_VERIFY_RETRY_DELAY_S)
        else:
            raise ScreenReadError(f"Kolom Jumlah menampilkan {shown}, bukan {text}")
        logger.info("Kolom Jumlah terisi: %s", text)

    def _ensure_usdt_unit(self) -> None:
        """Pastikan satuan kolom Jumlah USDT (Ukuran Order); bila bukan, pilih lewat menu satuan."""
        if layout.ORDER_UNIT_BUTTON is None or layout.ORDER_UNIT_MENU_AREA is None:
            return  # tidak diotomatiskan: _check_order_unit akan berhenti dan meminta pengguna
        joined = " ".join(self._read_texts(self.rect.sub(*layout.ORDER_QTY_AREA)))
        if _USDT_UNIT.search(joined) and not _MARGIN_MODE.search(joined):
            return
        logger.info("Satuan kolom Jumlah bukan USDT: memilih USDT lewat menu satuan")
        if not self._unit_menu_open():
            self._click(layout.ORDER_UNIT_BUTTON)
            if not self._unit_menu_open():
                shot = self._save_debug_shot("menu-satuan")
                raise ScreenReadError(f"Menu satuan Jumlah tidak terbuka. Foto layar: {shot}")
        area = layout.ORDER_UNIT_MENU_AREA
        radio = self._find_text(area, _UNIT_RADIO)
        if radio is None or radio[1] < layout.ORDER_UNIT_MIN_Y:
            shot = self._save_debug_shot("menu-satuan")
            raise ScreenReadError(
                f"Pilihan 'Ukuran Order' di menu satuan tidak ada di tempat aman. Foto: {shot}"
            )
        self._click_in_unit_menu(radio)
        shown = " ".join(self._read_texts(self.rect.sub(*layout.ORDER_QTY_AREA)))
        if not _USDT_UNIT.search(shown) or _MARGIN_MODE.search(shown):
            shot = self._save_debug_shot("menu-satuan")
            raise ScreenReadError(
                f"Satuan kolom Jumlah masih bukan USDT (terbaca: {shown}). {shot}"
            )

    def _unit_menu_open(self) -> bool:
        """Menu "Preferensi Unit" tampil: judulnya dan keterangan USDT-nya sama-sama terbaca."""
        area = layout.ORDER_UNIT_MENU_AREA
        assert area is not None
        texts = self._read_texts(self.rect.sub(*area))
        return any(_UNIT_MENU_TITLE.search(t) for t in texts) and any(
            _UNIT_MENU_USDT.search(t) for t in texts
        )

    def _click_in_unit_menu(self, target: tuple[float, float]) -> None:
        """Klik di dalam menu satuan, di zona yang biasanya terlarang (menu menutupi tombol order).

        Hanya lewat jalur ini, dan hanya bila menu terbukti masih terbuka tepat sebelum klik dan
        titiknya di bawah garis ORDER_UNIT_MIN_Y (di bawah tombol Beli/Long dan Jual/Short).
        """
        if target[1] < layout.ORDER_UNIT_MIN_Y or not self._unit_menu_open():
            raise SafetyError("Klik di menu satuan dibatalkan: menu tidak terbukti terbuka")
        self._unit_menu_click = True
        try:
            self._click(target)
        finally:
            self._unit_menu_click = False

    def _check_order_unit(self) -> None:
        """Kolom Jumlah harus bersatuan USDT (Ukuran Order), bukan koin atau Margin Awal.

        Ukuran posisi dihitung dalam USDT; angka yang sama dalam satuan koin atau sebagai margin
        akan menghasilkan posisi yang jauh berbeda.
        """
        shown = self._read_texts(self.rect.sub(*layout.ORDER_QTY_AREA))
        joined = " ".join(shown)
        fix = "Di Binance klik satuan di kolom Jumlah, lalu pilih USDT > Ukuran Order."
        if _MARGIN_MODE.search(joined):
            raise ScreenReadError(f"Kolom Jumlah memakai Margin Awal, bukan Ukuran Order. {fix}")
        if not _USDT_UNIT.search(joined):
            raise ScreenReadError(f"Satuan kolom Jumlah bukan USDT (terbaca: {shown}). {fix}")

    def capture_window(self, path: Path) -> Path:
        return self._capture(self.rect, path)

    def capture_chart(self, path: Path) -> Path:
        return self._capture(self._chart_area(), path)

    def _find_text(
        self, area: tuple[float, float, float, float], pattern: re.Pattern[str]
    ) -> tuple[float, float] | None:
        """Posisi (relatif jendela) teks yang cocok di dalam `area`, atau None."""
        x0, y0, x1, y1 = area
        for line in self._read_lines(self.rect.sub(*area)):
            match = pattern.search(line.text)
            if not match:
                continue
            x = line.x
            if line.width and len(line.text) > len(match.group()):
                # OCR menggabungkan beberapa tombol dalam satu baris: perkirakan posisi kata.
                middle = (match.start() + match.end()) / 2
                x = line.x - line.width / 2 + line.width * middle / len(line.text)
            return x0 + x * (x1 - x0), y0 + line.y * (y1 - y0)
        return None

    @property
    def rect(self) -> Rect:
        if self._rect is None:
            raise WindowError("Panggil prepare() sebelum navigasi")
        return self._rect

    def _click(self, target: tuple[float, float]) -> None:
        if self._forbidden(target):
            raise SafetyError(f"Klik ke zona terlarang ditolak: {target}")
        self._ensure_front()
        self._window.click(*self.rect.point_at(*target))
        self._sleep(self._settings.settle_delay_s)

    def _forbidden(self, target: tuple[float, float]) -> bool:
        """Titik yang tidak boleh diklik (tombol order). Platform lain menimpanya."""
        if self._unit_menu_click and target[1] >= layout.ORDER_UNIT_MIN_Y:
            return False
        return self._on_trade_page and layout.in_order_button_zone(target)

    def _ensure_front(self) -> None:
        """Pastikan Binance jendela aktif. Klik, ketikan, dan tangkapan layar hanya berarti bila
        Binance di depan; aplikasi lain bisa merebut fokus di tengah jalan."""
        bundle = self._settings.app_bundle_id
        front = (self._apps.frontmost_bundle_id() or "").casefold() == bundle.casefold()
        if front and not self._covered():
            self._away = False
            return
        if self._away:  # kembali dari aplikasi MarketForge (show_app): memang direncanakan
            logger.info(
                "Kembali ke %s",
                self._settings.app_name,
                extra=event("view", target="exchange"),
            )
            self._away = False
        else:
            logger.warning("%s tidak di depan, dibawa ke depan lagi", self._settings.app_name)
        # Aplikasi lain (atau pengguna yang sedang memakai laptop) bisa merebut fokus lagi
        # segera setelah Binance dibawa ke depan, jadi dicoba beberapa kali.
        for attempt in range(_FRONT_ATTEMPTS):
            self._apps.launch(bundle)
            try:
                wait_until_frontmost(
                    self._apps,
                    bundle,
                    timeout_s=_FRONT_WAIT_S,
                    interval_s=self._settings.poll_interval_s,
                    sleep=self._sleep,
                    clock=self._clock,
                )
                break
            except AppTimeoutError:
                if attempt + 1 == _FRONT_ATTEMPTS:
                    raise
        self._sleep(0.5)

    def _covered(self) -> bool:
        """Jendela lain menutupi jendela bursa walau aplikasinya terhitung aktif.

        Terjadi saat MarketForge memajukan jendelanya (show_app): sistem bisa tetap menganggap
        bursa aplikasi aktif, padahal klik dan tangkapan layar akan mengenai MarketForge.
        """
        if self._windows is None or self._rect is None:
            return False
        r = self._rect
        try:
            top = front_owner_at((r.x + r.width // 2, r.y + r.height // 2), self._windows)
        except Exception:  # daftar jendela tidak terbaca: andalkan pemeriksaan aplikasi aktif
            logger.debug("Daftar jendela tidak terbaca", exc_info=True)
            return False
        if top is None:
            return False
        owner = top.owner.casefold().removesuffix(".exe")  # Windows: "Binance.exe"
        return owner != self._settings.app_name.casefold()

    def show_app(self, text: str, **fields: object) -> None:
        """Serahkan layar ke aplikasi MarketForge selama bot menunggu (AI membaca grafik).

        Aplikasi memunculkan dirinya saat menerima kejadian ini (sama di macOS dan Windows).
        Bursa dibawa ke depan lagi oleh `_ensure_front` sebelum klik, ketikan, atau tangkapan
        layar berikutnya, jadi bot tidak pernah bekerja di jendela yang salah.
        """
        self._away = True
        logger.info(text, extra=event("view", target="app", **fields))

    # ------------------------------------------------------------------ tombol order (dikunci)
    def _on_coin_page(self) -> bool:
        return self._on_trade_page

    def _order_form_zones(self) -> list[tuple[float, float, float, float]]:
        """Zona tombol order di panel form (kanan), bukan widget melayang di atas grafik."""
        return [zone for zone in layout.ORDER_BUTTON_ZONES if zone[0] >= 0.5]

    def _quantity_area(self) -> tuple[float, float, float, float]:
        return layout.ORDER_QTY_AREA

    def short_button(self) -> tuple[float, float]:
        """Posisi tombol Jual/Short di form order, dicari dengan OCR. Tidak mengklik apa pun."""
        if not self._on_coin_page():
            raise SafetyError("Tombol Short hanya dicari di halaman koin")
        for zone in self._order_form_zones():
            found = self._find_text(zone, _SHORT_BUTTON)
            if found is not None:
                return found
        raise ScreenReadError("Tombol Jual/Short di form order tidak ditemukan")

    def press_short(self, plan: OrderPlan) -> None:
        """Order sungguhan: tekan Jual/Short. DIKUNCI selama LIVE_ORDERS_ENABLED False.

        Urutan: kunci, halaman koin, kolom jumlah berisi angka rencana, cari tombol, klik.
        Satu-satunya jalur yang boleh mengklik zona tombol order.
        """
        if not LIVE_ORDERS_ENABLED:
            raise SafetyError("Order sungguhan dinonaktifkan (LIVE_ORDERS_ENABLED = False)")
        if not self._on_coin_page():
            raise SafetyError("Order hanya di halaman koin")
        shown = self._read_texts(self.rect.sub(*self._quantity_area()))
        if not any(same_number(value, plan.order_text) for value in shown):
            raise SafetyError(
                f"Kolom jumlah menampilkan {shown}, bukan {plan.order_text}: order dibatalkan"
            )
        target = self.short_button()
        logger.warning("ORDER SUNGGUHAN: tekan Jual/Short %s %s USDT", plan.symbol, plan.order_text)
        self._ensure_front()
        self._window.click(*self.rect.point_at(*target))

    def _capture(self, area: Rect, path: Path) -> Path:
        self._ensure_front()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._window.capture(area, path)
        logger.info("Tangkapan layar disimpan: %s", path)
        return path

    def _read_lines(self, area: Rect) -> list[TextLine]:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "ocr.png"
            self._ensure_front()
            self._window.capture(area, image)
            return self._reader.read_lines(image)

    def _read_texts(self, area: Rect) -> list[str]:
        return [line.text for line in self._read_lines(area)]
