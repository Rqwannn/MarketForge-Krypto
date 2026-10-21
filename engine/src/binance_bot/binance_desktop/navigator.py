"""Navigasi Binance Desktop untuk SOP: Pasar -> Futures -> Top Gainers -> halaman trade.

Semua klik lewat `_click`, yang menolak klik ke zona tombol order di halaman trade. Bot hanya
mengklik navigasi dan mengisi kolom angka; tombol beli/short tidak pernah ditekan.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

from binance_bot.binance_desktop import layout
from binance_bot.binance_desktop.order_buttons import find_pair, text_image
from binance_bot.binance_desktop.screen_text import (
    GainerRow,
    MarginSettings,
    is_sorted_by_top_gain,
    parse_available_usdt,
    parse_futures_symbol,
    parse_gainer_rows,
    parse_margin,
    same_number,
)
from binance_bot.config import Settings
from binance_bot.exceptions import (
    AppNotRunningError,
    AppTimeoutError,
    PositionNotFoundError,
    SafetyError,
    ScreenReadError,
    WindowError,
)
from binance_bot.filelock import ScreenTurn
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
from binance_bot.strategy.execution import OrderPlan, live_orders_enabled
from binance_bot.tebbit_web.visible import OnScreenWindow, front_owner_at

logger = logging.getLogger(__name__)

_SORT_ATTEMPTS = 4
_OPEN_SYMBOL_ATTEMPTS = 2  # buka ulang lewat nama bila daftar bergeser saat diklik
_VERIFY_ATTEMPTS = 4
_FRONT_ATTEMPTS = 5
_FRONT_WAIT_S = 3.0
_FOCUS_CLICK_AFTER = 2  # usaha biasa yang gagal sebelum klik titik kosong bilah judul
_VERIFY_RETRY_DELAY_S = 0.4
_SEARCH_READ_ATTEMPTS = 5  # baca hasil pencarian daftar Futures (sekitar 5 detik)
_LEVERAGE_SETTLE_ATTEMPTS = 12  # sekitar 5 detik untuk dialog menutup dan label berubah
_POSITION_PAGES = 8  # langkah gulir maksimal mencari baris posisi di tabel Posisi (3-5 posisi)
_PAGE_READ_ATTEMPTS = 3  # baca pair di halaman koin: halaman baru bisa lambat tampil
_PAGE_READ_DELAY_S = 1.0
_OPEN_PAGE_ATTEMPTS = 2  # klik ikon trade diulang sekali bila hilang (daftar masih tampil)
_TOOLBAR_WAIT_S = 15.0  # toolbar grafik belum tampil saat halaman koin masih memuat
_CHART_TAB = re.compile(r"\bGrafik\b")
_FUTURES_TAB = re.compile(r"\bFutures\b")
_CHANGE_HEADER = re.compile(r"Perubahan")
_MENU_ATTEMPTS = 3
_MARKET_MENU = re.compile(
    r"^\s*\W{0,2}\s*Pasar\s*$", re.IGNORECASE
)  # ikon menu kadang terbaca sebagai simbol
_UNIT_MENU_TITLE = re.compile(r"Preferensi\s*Unit|^\s*Unit\s*$")
_UNIT_MENU_USDT = re.compile(r"dalam\s+USDT", re.IGNORECASE)
# OCR membaca lingkaran radio sebagai huruf ("C. Ukuran Order"); huruf besar membedakannya dari
# keterangan "...ukuran order dalam USDT".
_UNIT_RADIO = re.compile(r"Ukuran\s*Order")
_ACTION_HEADER = re.compile(r"Tindakan", re.IGNORECASE)
_EXTRA_SCROLL_SHIFT = 0.05  # banner setinggi ini atau lebih: gulir satu langkah lagi
_FIFTEEN_MINUTES = re.compile(r"\b15\s*mnt\b")
# Legenda "MA(7) ... MA(25) ... MA(99)" menandakan grafik sudah termuat. OCR Windows sering salah
# baca: kurung jadi huruf ("MAC7)"), atau garis MA99 yang melintasi label membuang awalannya
# ("7) 0,026157 MA(25) ..."). Cukup salah satu garis terbaca; angka lain (MA(77)) tidak cocok.
_CHART_LEGEND = re.compile(r"MA\s*[(\[{<C]?\s*(?:7|25|99)(?!\d)|\b7\)\s*[\d.,]+\s*MA")
_USDT_UNIT = re.compile(r"\bUSDT\b")
_MARGIN_MODE = re.compile(r"Margin\s*Awal", re.IGNORECASE)
_SHORT_BUTTON = re.compile(r"(Jual|Sell)\s*/\s*Short", re.IGNORECASE)
# Teks di dalam tombol (dibaca dari kanal minimum): cukup salah satu kata, OCR sering memotong.
_SHORT_TEXT = re.compile(r"(Jual|Sell)\s*/?\s*Short|Short|Jual", re.IGNORECASE)
_LONG_TEXT = re.compile(r"(Beli|Buy)\s*/?\s*Long|Long|Beli", re.IGNORECASE)
_POSITIONS_TAB = re.compile(r"^\s*(Posisi|Positions?)\s*\([\dOo]+\)", re.IGNORECASE)  # "Posisi(O)"
# "Posisi(1)"; OCR seluruh jendela kadang membaca angkanya sebagai huruf ("Posisi(O)", "Posisi(l)").
_POSITIONS_COUNT = re.compile(r"(?:Posisi|Positions?)\s*\(([\dOoIl|]+)\)", re.IGNORECASE)
# Sesudah tombol Jual/Short ditekan: bukti posisi terbuka ditunggu sampai sekian detik. Uji nyata
# (20 Okt, BRUSDT dan AGTUSDT): bot mencatat posisi sungguhan padahal Binance tidak membukanya.
_ORDER_CONFIRM_S = 10.0
_CLOSE_SCROLL_NOTCHES = 2  # gulir halaman sedikit bila baris posisi belum terlihat
_SCROLL_UP_NOTCHES = 7  # satu scroll_up = 7 langkah roda
_DIGIT_LOOKALIKE = str.maketrans("OoIl|", "00111")
_FORM_COLUMN = (0.78, 0.0, 1.0, 1.0)  # kolom form order (tempat tombol dicari lewat warna)
# Toast Binance sesudah order pasar terisi (uji nyata 20 Okt: "Order Dimasukkan", "Order Jual
# Market Terisi"). Hanya toast yang BARU muncul sesudah klik yang dihitung sebagai bukti.
_ORDER_FILLED = re.compile(r"Order\s+Jual\b.*Terisi|Sell\b.*Order.*Filled", re.IGNORECASE)
# Pesan penolakan order Binance (toast), dicatat sebagai alasan bila order tidak masuk.
# Bukan kata "gagal" saja: jendela konfirmasi order memuat kalimat peringatan "...order Anda akan
# gagal" (uji nyata 20 Okt 10.00) yang bukan penolakan.
_ORDER_MESSAGE = re.compile(
    r"order\s+gagal|gagal\s+(?:ditempatkan|dipasang|dibuat)|ditolak|tidak cukup|tidak mencukupi"
    r"|selesaikan kuis|melebihi|order failed|rejected|insufficient|quiz",
    re.IGNORECASE,
)
_MARKET_CLOSE = re.compile(r"\bMarket\b")
# Dialog leverage: Binance "Sesuaikan Leverage", Tebbit "Modify leverage".
# Angka leverage (label di atas form dan kolom dialog); OCR bisa menggabungkannya dengan
# tombol - dan + ("— 10x +").
_LEVERAGE_VALUE = re.compile(r"(?<![\d.,])(\d{1,3})\s*[xX](?![A-Za-z])")
_SEARCHED_PAIR = re.compile(r"\b[A-Z0-9]{2,16}USDT\b")  # isi kotak cari daftar Pasar
_SEARCH_PLACEHOLDER = re.compile(r"Cari\s+Nama|Search", re.IGNORECASE)  # kotak cari kosong
_LEVERAGE_TITLE = re.compile(r"(Sesuaikan|Modify|Adjust)\s+Leverage", re.IGNORECASE)
_CONFIRM = re.compile(r"^\s*(Konfirmasi|Confirm)\s*$", re.IGNORECASE)
_CLOSE = re.compile(r"^\s*[xX\u00d7]\s*$")  # ikon tutup (x atau tanda kali)


def _leverage_of(text: str) -> int | None:
    """Angka di kolom leverage setelah diketik; "x" boleh tidak ada (Tebbit: "2" lalu "X")."""
    match = re.search(r"(?<![\d.,])(\d{1,3})\s*[xX]?(?![\d.,A-Za-z])", text)
    return int(match.group(1)) if match else None


_CHART_LOAD_TIMEOUT_S = 25.0  # aplikasi bisa lambat memuat grafik
_CHART_RETRY_TIMEOUT_S = 15.0  # tunggu sesudah klik "15 mnt" diulang
_FORM_SHIFT_MIN = 0.02  # pergeseran lebih kecil dari ini dianggap galat ukur, bukan banner


class _OrderEvidence(NamedTuple):
    """Bukti order di layar: jumlah "Posisi(n)", saldo Tersedia, toast terisi, pesan penolakan."""

    positions: int | None
    available: float | None
    filled: list[str]
    rejected: list[str]


def _shifted(
    area: tuple[float, float, float, float], shift: float
) -> tuple[float, float, float, float]:
    """`area` digeser `shift` (pecahan tinggi jendela) ke bawah, dipotong di tepi bawah jendela."""
    x0, y0, x1, y1 = area
    return x0, min(1.0, y0 + shift), x1, min(1.0, y1 + shift)


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
        self._turn = ScreenTurn(settings.screen_lock_path)

    @contextmanager
    def screen_turn(self) -> Iterator[None]:
        """Giliran layar untuk satu rangkaian aksi; bot lain di laptop ini menunggu gilirannya."""
        with self._turn.hold():
            if self._turn.changed_hands:
                self._turn.changed_hands = False
                self._forget_page()
            yield

    def _forget_page(self) -> None:
        """Bot lain memakai layar sejak giliran terakhir: halaman yang tampil belum tentu yang
        terakhir dibuka bot ini, jadi daftar dan halaman koin dibuka ulang, bukan diingat."""
        logger.info("Giliran layar dari bot lain: halaman %s dibaca ulang", self._settings.app_name)
        self._on_list = False
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
        try:
            wait_until_frontmost(
                self._apps,
                settings.app_bundle_id,
                timeout_s=min(_FRONT_WAIT_S, settings.launch_timeout_s),
                interval_s=settings.poll_interval_s,
                sleep=self._sleep,
                clock=self._clock,
            )
        except AppTimeoutError:
            # Windows menolak memindahkan fokus (mis. jendela notifikasi memegangnya): klik asli
            # di titik kosong bilah judul, lalu tunggu seperti biasa.
            self._focus_by_click(None)
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
        # OCR sesekali melewatkan satu label: coba beberapa kali sebelum memakai posisi tetap.
        for attempt in range(_MENU_ATTEMPTS):
            found = self._find_text(layout.SIDEBAR_AREA, _MARKET_MENU)
            if found is not None:
                return found
            if attempt + 1 < _MENU_ATTEMPTS:
                self._sleep(0.5)
        logger.warning("Menu Pasar tidak terbaca di sidebar; memakai posisi tetap")
        return layout.SIDEBAR_MARKET

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
        if self._clear_market_search():
            # Sesudah kotak cari dikosongkan, Binance belum memuat ulang isi tab Futures ("Tidak
            # ada Rekaman", uji kertas 21 Okt): tab diklik lagi supaya daftarnya dimuat ulang.
            self._click(tab)
            self._sleep(self._settings.settle_delay_s)
            self._locate_list()
        if layout.FUTURES_USDM_TAB:
            self._click(self._shifted(layout.FUTURES_USDM_TAB))

    def _clear_market_search(self) -> bool:
        """Kosongkan kotak cari daftar Pasar bila masih berisi nama pair (sisa `search_symbol`,
        bisa dari bot lain): daftar yang tersaring hanya berisi satu koin, bukan Top 5.

        Teks pair-nya sendiri yang diklik (pasti memberi fokus ke kolom), baru Cmd+A dan hapus:
        tanpa fokus, Cmd+A dan hapus mengenai halaman (uji nyata 21 Okt: halaman pindah tab).
        """
        area = layout.MARKET_SEARCH_AREA
        if area is None:
            return False
        text = self._find_text(area, _SEARCHED_PAIR)
        if text is None:
            return False
        logger.info("Kotak cari daftar Futures masih berisi nama pair: dikosongkan")
        self._click(text)
        self._window.clear_field()
        self._sleep(self._settings.settle_delay_s)
        if self._find_text(area, _SEARCHED_PAIR) is not None:
            raise ScreenReadError("Kotak cari daftar Futures tidak bisa dikosongkan")
        return True

    def search_symbol(self, symbol: str) -> str:
        """Buka koin lewat kotak cari daftar Futures, walau sudah keluar Top 5.

        Untuk koin yang baru terjual di target (pernah lolos Top 5 saat pertama masuk). Ikon cari
        diklik agar kotak melebar; mengetik hanya setelah tulisan "Cari Nama Koin" terlihat dan
        tulisan itu diklik (fokus pasti di kolom). Hanya nama pair yang diketik, tanpa Enter, lalu
        dicek dengan OCR; baris yang namanya persis sama dibuka lewat ikon trade-nya. Kotak
        dikosongkan lagi saat daftar Futures dibuka berikutnya (`_clear_market_search`).
        """
        area = layout.MARKET_SEARCH_AREA
        if layout.MARKET_SEARCH is None or area is None:
            raise ScreenReadError("Pencarian daftar Futures belum tersedia di profil layar ini")
        self._click(self._market_menu_position())
        self._on_trade_page = False
        self._on_list = False
        self._row_y = {}
        self._open_futures_list()  # juga mengosongkan sisa pencarian sebelumnya
        self._click(layout.MARKET_SEARCH)
        field = None
        for _attempt in range(_SEARCH_READ_ATTEMPTS):  # aplikasi yang lambat butuh waktu melebar
            self._sleep(_VERIFY_RETRY_DELAY_S * 2)
            field = self._find_text(area, _SEARCH_PLACEHOLDER)
            if field is not None:
                break
        if field is None:
            raise ScreenReadError(
                "Kotak cari daftar Futures tidak terbuka (tulisan Cari tak terlihat)"
            )
        self._click(field)  # fokus ke kolom; tidak ada ketikan sebelum ini
        self._window.type_symbol(symbol)
        self._sleep(self._settings.settle_delay_s)
        # Nama persis (bukan 1000PEPEUSDT untuk PEPEUSDT); kursor atau ikon boleh ikut terbaca.
        exact = re.compile(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])")
        if self._find_text(area, exact) is None:
            raise ScreenReadError(f"Kotak cari daftar Futures tidak menampilkan {symbol}")
        rows: list[GainerRow] = []
        row = None
        for attempt in range(_SEARCH_READ_ATTEMPTS):  # hasil saringan butuh waktu untuk tampil
            rows = self.read_top_gainers()
            row = next((r for r in rows if r.symbol == symbol), None)
            if row is not None or attempt + 1 == _SEARCH_READ_ATTEMPTS:
                break
            self._sleep(1.0)
        if row is None:
            raise ScreenReadError(
                f"{symbol} tidak ditemukan lewat pencarian Futures "
                f"(terbaca: {[r.symbol for r in rows]})"
            )
        opened = self.open_gainer(row.rank)
        if opened != symbol:
            raise ScreenReadError(f"Pencarian {symbol} membuka {opened}")
        return opened

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
        Halaman yang lambat tampil ditunggu. Klik ikon yang hilang (uji nyata: NILUSDT, daftar
        Pasar tetap di layar) diulang sekali, tetapi hanya bila daftar terbukti masih tampil.
        """
        attempt = 1
        while True:
            self._click(self._trade_icon(rank))
            self._on_trade_page = True
            self._on_list = False
            self._chart_shift = 0.0
            try:
                symbol = self._read_symbol_waiting()
            except ScreenReadError as exc:
                if attempt >= _OPEN_PAGE_ATTEMPTS or not self._list_still_shown():
                    shot = self._save_debug_shot("halaman-trade")
                    raise ScreenReadError(f"{exc} Foto layar yang dilihat bot: {shot}") from exc
                logger.warning(
                    "Klik ikon trade #%d tidak membuka halaman koin (daftar masih tampil): diulang",
                    rank,
                )
                self._on_trade_page, self._on_list = False, True
                attempt += 1
                continue
            logger.info("Top gainer #%d: %s", rank, symbol)
            return symbol

    def _read_symbol_waiting(self) -> str:
        """Pair di halaman trade. Halaman yang baru dibuka bisa lambat tampil: dibaca ulang."""
        attempt = 1
        while True:
            try:
                return self.read_symbol()
            except ScreenReadError:
                if attempt >= _PAGE_READ_ATTEMPTS:
                    raise
            attempt += 1
            self._sleep(_PAGE_READ_DELAY_S)

    def _list_still_shown(self) -> bool:
        """Daftar Futures masih di layar (judul kolom "Tindakan" terbaca): klik ikon tadi hilang.

        Dicek lewat OCR dulu agar klik ulang tidak pernah mendarat di halaman trade.
        """
        if layout.FUTURES_ACTION_AREA is None:
            return False
        return self._find_text(layout.FUTURES_ACTION_AREA, _ACTION_HEADER) is not None

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
        timeout = _CHART_LOAD_TIMEOUT_S
        for attempt in (1, 2):
            button = self._find_timeframe_button()
            if button is None:
                shot = self._save_debug_shot("tombol-15-mnt")
                raise ScreenReadError(
                    f"Tombol '15 mnt' tidak ditemukan di halaman trade. Foto layar: {shot}"
                )
            self._click(button)
            self._chart_shift = button[1] - layout.TIMEFRAME_15M[1]
            try:
                self._wait_for_chart(timeout)
                return
            except ScreenReadError as exc:
                shot = self._save_debug_shot("grafik-15-menit")
                if attempt == 2:
                    raise ScreenReadError(f"{exc}. Foto layar: {shot}") from exc
                # Klik bisa hilang saat halaman koin masih berpindah: ulangi sekali.
                logger.warning("%s; klik tab Grafik dan 15 mnt diulang (foto: %s)", exc, shot)
                timeout = _CHART_RETRY_TIMEOUT_S

    def _find_timeframe_button(self) -> tuple[float, float] | None:
        """Klik tab "Grafik" bila tampak, lalu cari tombol "15 mnt".

        Halaman koin yang baru dibuka tampil bertahap (uji nyata: BRUSDT, toolbar belum ada saat
        dicari): ditunggu sampai `_TOOLBAR_WAIT_S`, tidak langsung menyerah.
        """
        deadline = self._clock() + _TOOLBAR_WAIT_S
        while True:
            chart_tab = self._find_text(layout.CHART_TOOLBAR_AREA, _CHART_TAB)
            if chart_tab is not None:
                self._click(chart_tab)
            button = self._find_text(layout.CHART_TOOLBAR_AREA, _FIFTEEN_MINUTES)
            if button is not None or self._clock() >= deadline:
                return button
            self._sleep(1.0)

    def _wait_for_chart(self, timeout: float = _CHART_LOAD_TIMEOUT_S) -> None:
        """Tunggu grafik selesai dimuat (legenda garis MA terbaca), bukan animasi loading."""
        deadline = self._clock() + timeout
        while True:
            lines = self._read_lines(self._chart_area())
            if any(_CHART_LEGEND.search(line.text) for line in lines):
                return
            if self._clock() >= deadline:
                raise ScreenReadError(f"Grafik 15 menit belum termuat setelah {timeout:g} detik")
            self._sleep(1.0)

    def _chart_area(self) -> Rect:
        x0, y0, x1, y1 = layout.CHART_AREA
        shift = self._chart_shift
        return self.rect.sub(x0, y0 + shift, x1, min(1.0, y1 + shift))

    @property
    def _form_shift(self) -> float:
        """Banner di halaman koin tertentu (uji nyata: BRUSDT, QUSDT) menggeser SELURUH isi halaman
        ke bawah sama jauh: grafik, form order, dan tombolnya. Pergeseran yang diukur dari tombol
        "15 mnt" dipakai juga untuk form; tanpa itu klik tetap mengenai tempat lama (mis. tombol
        "Cross" di atas form, bukan tab Pasar)."""
        return self._chart_shift if abs(self._chart_shift) >= _FORM_SHIFT_MIN else 0.0

    def _form_area(
        self, area: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return _shifted(area, self._form_shift)

    def _form_point(self, point: tuple[float, float]) -> tuple[float, float]:
        return point[0], point[1] + self._form_shift

    @property
    def _unit_min_y(self) -> float:
        return layout.ORDER_UNIT_MIN_Y + self._form_shift

    def available_usdt(self) -> float | None:
        """Saldo "Tersedia" di form order (USDT), atau None bila tidak terbaca."""
        area = self.rect.sub(*self._form_area(layout.ORDER_AVAILABLE_AREA))
        return parse_available_usdt(self._read_texts(area))

    def read_margin_settings(self) -> MarginSettings:
        texts = self._read_texts(self.rect.sub(*self._margin_area()))
        margin = parse_margin(texts)
        if margin.leverage is None and self._leverage_box_x() is not None:
            # "2x" sependek itu sering dijatuhkan OCR: baca kotaknya bersama kata pendamping.
            margin = parse_margin(texts + self._leverage_with_companion())
        return margin

    def _leverage_box_x(self) -> tuple[float, float] | None:
        """Kotak angka leverage di area margin (pecahan lebar), atau None. Tebbit menimpanya."""
        return layout.LEVERAGE_BOX_X

    def _leverage_with_companion(self) -> list[str]:
        """Teks kotak leverage, dibaca sebagai baris "Leverage 2x" (kata pendamping digambar).

        OCR sering menjatuhkan teks sependek "2x" yang berdiri sendiri; dengan kata di sebelahnya
        ia terbaca. Kotak dipotong sempit supaya tombol di kiri kanannya tidak ikut terbaca.
        """
        from PIL import Image, ImageChops, ImageDraw, ImageFont

        box_x = self._leverage_box_x()
        assert box_x is not None
        left, right = box_x
        found: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            raw, composed = Path(tmp) / "m.png", Path(tmp) / "m_c.png"
            self._ensure_front()
            self._window.capture(self.rect.sub(*self._margin_area()), raw)
            with Image.open(raw) as image:
                r, g, b = image.convert("RGB").split()
                box = ImageChops.lighter(ImageChops.lighter(r, g), b)
                box = box.crop((int(box.width * left), 0, int(box.width * right), box.height))
            for scale in (4, 3):
                big = box.resize((box.width * scale, box.height * scale), Image.Resampling.LANCZOS)
                font: Any
                try:
                    font = ImageFont.truetype("arial.ttf", int(big.height * 0.42))
                except OSError:
                    font = ImageFont.load_default()
                canvas = Image.new("L", (big.width + 900, big.height + 40), 0)
                draw = ImageDraw.Draw(canvas)
                draw.text((20, 20 + int(big.height * 0.18)), "Leverage", fill=235, font=font)
                canvas.paste(big, (20 + int(draw.textlength("Leverage  ", font=font)), 20))
                canvas.save(composed)
                found += [line.text for line in self._reader.read_lines(composed)]
        return found

    def _leverage_button(self) -> tuple[float, float] | None:
        """Tengah tombol leverage (relatif jendela) dari tata letak tetap; hanya bila angkanya
        sudah terbaca di tempat itu (OCR gagal menemukan posisi barisnya, bukan tombolnya)."""
        box_x = self._leverage_box_x()
        if box_x is None:
            return None
        x0, y0, x1, y1 = self._margin_area()
        return x0 + (box_x[0] + box_x[1]) / 2 * (x1 - x0), (y0 + y1) / 2

    def _margin_area(self) -> tuple[float, float, float, float]:
        return self._form_area(layout.MARGIN_AREA)

    def _leverage_dialog_area(self) -> tuple[float, float, float, float]:
        return layout.LEVERAGE_DIALOG_AREA

    def ensure_leverage(self, leverage: int) -> MarginSettings:
        """Ubah leverage koin yang terbuka ke `leverage` bila belum (bursa menyimpannya per koin).

        Klik label leverage di atas form, ketik angka di dialog, cek angkanya dengan OCR, lalu
        Konfirmasi. Hasilnya dibaca ulang dari label; bila bursa menolak, dialog ditutup.
        """
        margin = self.read_margin_settings()
        if margin.leverage == leverage:
            return margin
        if not self._on_coin_page():
            raise SafetyError("Leverage hanya diubah di halaman koin")
        label = self._find_text(self._margin_area(), _LEVERAGE_VALUE)
        if label is None and margin.leverage is not None:
            label = self._leverage_button()
        if label is None:
            shot = self._save_debug_shot("tombol-leverage")
            raise ScreenReadError(
                f"Tombol leverage di atas form order tidak ditemukan. Foto layar: {shot}"
            )
        self._click(label)
        dialog = self._leverage_dialog_area()
        if self._find_text(dialog, _LEVERAGE_TITLE) is None:
            raise ScreenReadError("Dialog leverage tidak terbuka")
        try:
            self._type_leverage(dialog, leverage)
            confirm = self._find_text(dialog, _CONFIRM)
            if confirm is None:
                raise ScreenReadError("Tombol Konfirmasi di dialog leverage tidak ditemukan")
            self._click(confirm)
            margin = self._await_leverage(dialog, leverage)
        finally:
            self._close_leverage_dialog(dialog)
        logger.info("Leverage diubah ke %dx", leverage)
        return margin

    def _await_leverage(
        self, dialog: tuple[float, float, float, float], leverage: int
    ) -> MarginSettings:
        """Sesudah Konfirmasi: tunggu dialog tertutup dan label di atas form menunjukkan
        `leverage`. Dialog menutup dengan animasi; dibaca terlalu cepat (uji nyata 21 Okt) judulnya
        masih terlihat sehingga dikira macet, padahal leverage sudah berubah."""
        margin = MarginSettings(isolated=None, leverage=None)
        for _attempt in range(_LEVERAGE_SETTLE_ATTEMPTS):
            self._sleep(_VERIFY_RETRY_DELAY_S)
            if self._find_text(dialog, _LEVERAGE_TITLE) is not None:
                continue  # dialog masih menutup
            margin = self.read_margin_settings()
            if margin.leverage == leverage:
                return margin
        raise ScreenReadError(
            f"Bursa tidak mengubah leverage (masih {margin.leverage}x, bukan {leverage}x)"
        )

    def _type_leverage(self, dialog: tuple[float, float, float, float], leverage: int) -> None:
        # Kolom angka ada di antara tombol - dan +, di atas label slider (1x, 2x, ...) yang
        # tulisannya sama bentuknya: ambil yang paling atas.
        x0, y0, x1, y1 = dialog
        values = [
            line
            for line in self._read_lines(self.rect.sub(*dialog))
            if _LEVERAGE_VALUE.search(line.text)
        ]
        if not values:
            raise ScreenReadError("Kolom angka di dialog leverage tidak ditemukan")
        field = min(values, key=lambda line: line.y)
        target = (x0 + field.x * (x1 - x0), y0 + field.y * (y1 - y0))
        self._click(target)
        self._ensure_front()
        # Bukan clear_field: kolom kosong langsung terisi minimum 1, lalu "2" menjadi "12".
        self._window.select_field()
        self._window.type_number(str(leverage))
        self._sleep(self._settings.settle_delay_s / 2)
        shown = ""
        for attempt in range(_VERIFY_ATTEMPTS):
            lines = self._read_lines(self.rect.sub(*dialog))
            near = [line for line in lines if abs(line.y - field.y) < 0.04]
            shown = " ".join(line.text for line in near)
            if any(_leverage_of(line.text) == leverage for line in near):
                return
            if attempt + 1 < _VERIFY_ATTEMPTS:
                self._sleep(_VERIFY_RETRY_DELAY_S)
        raise ScreenReadError(f"Kolom leverage menampilkan {shown!r}, bukan {leverage}x")

    def _close_leverage_dialog(self, dialog: tuple[float, float, float, float]) -> None:
        """Tutup dialog leverage bila masih terbuka (mis. bursa menolak perubahan)."""
        if self._find_text(dialog, _LEVERAGE_TITLE) is None:
            return
        x0, y0, x1, y1 = dialog
        close = self._find_text((x0 + (x1 - x0) / 2, y0, x1, y0 + (y1 - y0) / 2), _CLOSE)
        if close is None:
            raise SafetyError("Dialog leverage tidak bisa ditutup: putaran dihentikan")
        self._click(close)

    def fill_quantity(self, text: str) -> None:
        """Isi kolom "Jumlah" (ukuran order USDT) pada form market order, lalu cek dengan OCR.

        Satuan kolom harus USDT dengan mode "Ukuran Order"; bila tidak, berhenti tanpa mengetik.
        Hanya mengetik angka. Tidak menekan Enter dan tidak menekan tombol order.
        """
        if not self._on_trade_page:
            raise SafetyError("Kolom Jumlah hanya diisi di halaman trade")
        self._click(self._form_point(layout.ORDER_TAB_MARKET))
        self._ensure_usdt_unit()
        self._check_order_unit()
        self._click(self._form_point(layout.ORDER_QTY_FIELD))
        self._ensure_front()  # ketikan angka hanya boleh masuk ke Binance
        self._window.clear_field()
        self._window.type_number(text)
        self._sleep(self._settings.settle_delay_s / 2)
        shown: list[str] = []
        for attempt in range(_VERIFY_ATTEMPTS):
            shown = self._read_texts(self.rect.sub(*self._quantity_area()))
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
        joined = " ".join(self._read_texts(self.rect.sub(*self._quantity_area())))
        if _USDT_UNIT.search(joined) and not _MARGIN_MODE.search(joined):
            return
        logger.info("Satuan kolom Jumlah bukan USDT: memilih USDT lewat menu satuan")
        if not self._unit_menu_open():
            self._click(self._form_point(layout.ORDER_UNIT_BUTTON))
            if not self._unit_menu_open():
                shot = self._save_debug_shot("menu-satuan")
                raise ScreenReadError(f"Menu satuan Jumlah tidak terbuka. Foto layar: {shot}")
        area = self._form_area(layout.ORDER_UNIT_MENU_AREA)
        radio = self._find_text(area, _UNIT_RADIO)
        if radio is None or radio[1] < self._unit_min_y:
            shot = self._save_debug_shot("menu-satuan")
            raise ScreenReadError(
                f"Pilihan 'Ukuran Order' di menu satuan tidak ada di tempat aman. Foto: {shot}"
            )
        self._click_in_unit_menu(radio)
        shown = " ".join(self._read_texts(self.rect.sub(*self._quantity_area())))
        if not _USDT_UNIT.search(shown) or _MARGIN_MODE.search(shown):
            shot = self._save_debug_shot("menu-satuan")
            raise ScreenReadError(
                f"Satuan kolom Jumlah masih bukan USDT (terbaca: {shown}). {shot}"
            )

    def _unit_menu_open(self) -> bool:
        """Menu "Preferensi Unit" tampil: judulnya dan keterangan USDT-nya sama-sama terbaca."""
        assert layout.ORDER_UNIT_MENU_AREA is not None
        area = self._form_area(layout.ORDER_UNIT_MENU_AREA)
        texts = self._read_texts(self.rect.sub(*area))
        return any(_UNIT_MENU_TITLE.search(t) for t in texts) and any(
            _UNIT_MENU_USDT.search(t) for t in texts
        )

    def _click_in_unit_menu(self, target: tuple[float, float]) -> None:
        """Klik di dalam menu satuan, di zona yang biasanya terlarang (menu menutupi tombol order).

        Hanya lewat jalur ini, dan hanya bila menu terbukti masih terbuka tepat sebelum klik dan
        titiknya di bawah garis ORDER_UNIT_MIN_Y (di bawah tombol Beli/Long dan Jual/Short).
        """
        if target[1] < self._unit_min_y or not self._unit_menu_open():
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
        shown = self._read_texts(self.rect.sub(*self._quantity_area()))
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
        if self._unit_menu_click and target[1] >= self._unit_min_y:
            return False
        if not self._on_trade_page:
            return False
        shift = self._form_shift
        if layout.in_order_button_zone(target) or (
            shift != 0.0 and layout.in_order_button_zone((target[0], target[1] - shift))
        ):
            return True
        # Zona tetap bisa meleset: uji nyata (20 Okt) halaman koin bergeser naik ~100-200 piksel
        # sesudah posisi terbuka, sehingga Jual/Short tampil di y 0,32, di LUAR zona tetap dan tepat
        # di tempat kolom Jumlah biasanya. Karena itu tombol yang benar-benar tampil dicari lewat
        # warnanya, dan klik ke dalamnya selalu ditolak.
        return any(
            x0 <= target[0] <= x1 and y0 <= target[1] <= y1
            for x0, y0, x1, y1 in self._button_boxes(target)
        )

    def _button_boxes(self, target: tuple[float, float]) -> list[tuple[float, float, float, float]]:
        """Kotak tombol Beli/Long dan Jual/Short yang tampil (relatif jendela, diperlebar sedikit).

        Hanya dicari bila titik klik berada di kolom form order; tanpa gambar (tes) daftar kosong.
        """
        x0, y0, x1, y1 = _FORM_COLUMN
        if not self._COLOR_BUTTONS or not (x0 <= target[0] <= x1):
            return []
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kolom.png"
            self._window.capture(self.rect.sub(*_FORM_COLUMN), path)
            try:
                with Image.open(path) as opened:
                    image = opened.convert("RGB")
            except (OSError, ValueError):
                return []
        pair = find_pair(image)
        if pair is None:
            return []
        w, h = image.width, image.height
        margin = 0.01
        return [
            (
                x0 + box.x0 / w * (x1 - x0) - margin,
                y0 + box.y0 / h * (y1 - y0) - margin,
                x0 + box.x1 / w * (x1 - x0) + margin,
                y0 + box.y1 / h * (y1 - y0) + margin,
            )
            for box in (pair.left, pair.right)
        ]

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
                if attempt + 1 == _FOCUS_CLICK_AFTER:
                    self._focus_by_click(self._rect)
        self._sleep(0.5)

    def _focus_by_click(self, rect: Rect | None) -> None:
        """Cara terakhir merebut fokus: klik titik kosong di bilah judul Binance.

        Windows menolak SetForegroundWindow dari proses yang bukan pemilik fokus. Uji nyata:
        jendela notifikasi sistem memegang fokus 30 menit lebih dan semua putaran gagal; Alt,
        AttachThreadInput dan SwitchToThisWindow ditolak semua. Klik asli selalu mengaktifkan
        jendela yang diklik. Titiknya tanpa kontrol apa pun dan jauh dari form order, jadi klik
        ini hanya memberi fokus. Tidak dipakai (None) bila tata letak tidak mendefinisikannya.
        """
        if layout.FOCUS_POINT is None:
            return
        try:
            if rect is None:
                rect = self._window.bounds(self._settings.app_name)
        except WindowError:
            return
        if rect.width <= 0 or rect.height <= 0:
            return
        logger.warning(
            "Fokus tak bisa direbut dengan cara biasa: klik titik kosong bilah judul %s",
            self._settings.app_name,
        )
        self._window.click(*rect.point_at(*layout.FOCUS_POINT))
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
        return [self._form_area(zone) for zone in layout.ORDER_BUTTON_ZONES if zone[0] >= 0.5]

    def _quantity_area(self) -> tuple[float, float, float, float]:
        return self._form_area(layout.ORDER_QTY_AREA)

    # Tombol dicari lewat warna pekatnya (hijau Long, merah Short), lalu dipastikan dengan teksnya.
    # Tebbit memakai warna dan susunan lain: ia tetap mencari teksnya saja.
    _COLOR_BUTTONS = True

    def short_button(self) -> tuple[float, float]:
        """Posisi tombol Jual/Short di form order. Tidak mengklik apa pun.

        Utama: dua persegi pekat hijau dan merah berdampingan; yang kanan harus terbaca "Short"
        (atau yang kiri "Long"), dan tidak boleh tertukar. Cadangan: teks "Jual/Short" lewat OCR.
        """
        if not self._on_coin_page():
            raise SafetyError("Tombol Short hanya dicari di halaman koin")
        if self._COLOR_BUTTONS:
            located = self._locate_order_buttons()
            if located is not None:
                return located[1]
        for zone in self._order_form_zones():
            found = self._find_text(zone, _SHORT_BUTTON)
            if found is not None:
                return found
        raise ScreenReadError("Tombol Jual/Short di form order tidak ditemukan")

    def long_button(self) -> tuple[float, float]:
        """Posisi tombol Beli/Long (untuk memastikan pasangan; bot tidak pernah menekannya)."""
        if not self._on_coin_page():
            raise SafetyError("Tombol Long hanya dicari di halaman koin")
        if self._COLOR_BUTTONS:
            located = self._locate_order_buttons()
            if located is not None:
                return located[0]
        raise ScreenReadError("Tombol Beli/Long di form order tidak ditemukan")

    def _locate_order_buttons(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """(tengah Long, tengah Short) relatif jendela, atau None bila pasangannya tak terbukti."""
        for zone in self._order_form_zones():
            found = self._buttons_in(zone)
            if found is not None:
                return found
        return None

    def _buttons_in(
        self, zone: tuple[float, float, float, float]
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "form.png"
            self._ensure_front()
            self._window.capture(self.rect.sub(*zone), path)
            try:
                with Image.open(path) as opened:
                    image = opened.convert("RGB")
            except (OSError, ValueError):
                return None  # tanpa gambar (mis. tes): pencarian lewat teks yang dipakai
            pair = find_pair(image)
            if pair is None:
                return None
            left_text = self._button_text(image, pair.left, Path(tmp) / "kiri.png")
            right_text = self._button_text(image, pair.right, Path(tmp) / "kanan.png")
        if not self._pair_is_long_short(left_text, right_text):
            logger.warning(
                "Pasangan tombol order tidak terbukti (kiri %r, kanan %r): tidak dipakai",
                left_text,
                right_text,
            )
            return None
        x0, y0, x1, y1 = zone

        def center(box: object) -> tuple[float, float]:
            cx, cy = box.center  # type: ignore[attr-defined]
            return x0 + cx / image.width * (x1 - x0), y0 + cy / image.height * (y1 - y0)

        return center(pair.left), center(pair.right)

    def _button_text(self, image: Any, box: Any, path: Path) -> str:
        text_image(image, box).save(path)
        return " ".join(line.text for line in self._reader.read_lines(path))

    @staticmethod
    def _pair_is_long_short(left_text: str, right_text: str) -> bool:
        """Kanan harus Short (atau kiri Long). Tertukar (kanan Long atau kiri Short) ditolak."""
        short_right = bool(_SHORT_TEXT.search(right_text))
        long_right = bool(_LONG_TEXT.search(right_text))
        long_left = bool(_LONG_TEXT.search(left_text))
        short_left = bool(_SHORT_TEXT.search(left_text))
        if (long_right and not short_right) or (short_left and not long_left):
            return False
        return short_right or long_left

    def press_short(self, plan: OrderPlan) -> None:
        """Order sungguhan: tekan Jual/Short. Terkunci kecuali Real Fund Trading dinyalakan.

        Urutan: kunci, halaman koin, kolom jumlah berisi angka rencana, cari tombol, klik.
        Satu-satunya jalur yang boleh mengklik zona tombol order.
        """
        if not live_orders_enabled():
            raise SafetyError("Order sungguhan terkunci (Real Fund Trading belum dinyalakan)")
        if not self._on_coin_page():
            raise SafetyError("Order hanya di halaman koin")
        matches, shown = self._quantity_matches(plan)
        if not matches:
            shot = self._save_debug_shot("kolom-jumlah")
            raise SafetyError(
                f"Kolom jumlah menampilkan {shown}, bukan {plan.order_text}: order dibatalkan. "
                f"Foto layar: {shot}"
            )
        target = self.short_button()
        before = self._order_evidence()
        logger.warning("ORDER SUNGGUHAN: tekan Jual/Short %s %s USDT", plan.symbol, plan.order_text)
        self._ensure_front()
        self._window.click(*self.rect.point_at(*target))
        # Tombol TIDAK pernah diklik ulang: bila order pertama ternyata masuk terlambat, klik kedua
        # membuka posisi ganda.
        self._await_order(plan, before, _ORDER_CONFIRM_S, photo="setelah-klik-short")

    def _quantity_matches(self, plan: OrderPlan) -> tuple[bool, list[str]]:
        shown: list[str] = []
        for attempt in range(_VERIFY_ATTEMPTS):
            shown = self._read_texts(self.rect.sub(*self._quantity_area()))
            if any(same_number(value, plan.order_text) for value in shown):
                return True, shown
            if attempt + 1 < _VERIFY_ATTEMPTS:
                # Uji nyata (AGTUSDT): bacaan "24" padahal kolom berisi 20, 0,17 detik setelah
                # bacaan "20" (kursor berkedip mengganggu OCR). Baca ulang seperti saat mengisi;
                # angkanya tetap harus persis sama dengan rencana.
                self._sleep(_VERIFY_RETRY_DELAY_S)
        return False, shown

    def _order_messages(self) -> list[str]:
        """Teks penolakan atau galat order yang tampil di jendela (toast Binance), bila ada."""
        return self._order_evidence().rejected

    def _order_evidence(self) -> _OrderEvidence:
        """Bukti order dari SELURUH jendela (satu kali OCR).

        Dibaca di seluruh jendela, bukan di area tetap: uji nyata (20 Okt, BRUSDT) halaman Binance
        bergeser naik ~100 piksel tepat sesudah order terisi, sehingga baris Tersedia dan tab
        Posisi keluar dari area tetap dan bukti yang jelas di layar terbaca kosong.
        """
        texts = [line.text for line in self._read_lines(self.rect)]
        count = None
        for text in texts:
            match = _POSITIONS_COUNT.search(text)
            if match:
                count = int(match.group(1).translate(_DIGIT_LOOKALIKE))
                break
        return _OrderEvidence(
            positions=count,
            available=parse_available_usdt(texts),
            filled=[t for t in texts if _ORDER_FILLED.search(t)],
            rejected=[t for t in texts if _ORDER_MESSAGE.search(t)],
        )

    def _positions_count(self) -> int | None:
        return self._order_evidence().positions

    def _await_order(
        self, plan: OrderPlan, before: _OrderEvidence, timeout_s: float, *, photo: str
    ) -> None:
        """Tunggu bukti Binance membuka posisi sesudah tombol Jual/Short ditekan.

        Bukti: toast "Order Jual Market Terisi" yang baru muncul, jumlah di tab "Posisi(n)"
        bertambah, atau saldo Tersedia turun setidaknya separuh margin. Selama menunggu bot tidak
        mengklik apa pun; foto layar diambil sekali di awal (toast Binance hanya tampil sebentar).

        Tanpa bukti sampai batas waktu, galat HANYA dilempar bila layar jelas menunjukkan order
        tidak masuk (Posisi dan Tersedia terbaca dan tidak berubah, atau ada pesan penolakan).
        Bila bacaannya tidak lengkap, posisi dianggap TERBUKA dan tetap diawasi: posisi sungguhan
        yang tak tercatat (uji nyata 20 Okt 10.00 dan 10.11) jauh lebih berbahaya daripada posisi
        tercatat yang ternyata tidak ada (penjualannya hanya gagal).
        """
        deadline = self._clock() + timeout_s
        first = True
        now = before
        while True:
            self._sleep(1.0)
            if first:
                logger.info("Foto layar sesudah klik order: %s", self._save_debug_shot(photo))
                first = False
            now = self._order_evidence()
            new_toast = [t for t in now.filled if t not in before.filled]
            more = (
                now.positions is not None
                and before.positions is not None
                and now.positions > before.positions
            )
            spent = (
                now.available is not None
                and before.available is not None
                and before.available - now.available >= plan.margin_usdt * 0.5
            )
            if new_toast or more or spent:
                logger.info(
                    "Order Short %s terkonfirmasi: Posisi %s -> %s, Tersedia %s -> %s, toast %s",
                    plan.symbol,
                    before.positions,
                    now.positions,
                    before.available,
                    now.available,
                    new_toast or "-",
                )
                return
            if now.rejected:
                self._fail_order(plan, before, now, f"Binance menampilkan: {now.rejected}")
            if self._clock() >= deadline:
                break
        unchanged = (
            now.positions is not None
            and before.positions is not None
            and now.positions == before.positions
            and now.available is not None
            and before.available is not None
            and abs(before.available - now.available) < plan.margin_usdt * 0.5
        )
        if unchanged:
            self._fail_order(plan, before, now, "Posisi dan saldo Tersedia tidak berubah")
        shot = self._save_debug_shot("order-belum-pasti")
        logger.error(
            "Order Short %s BELUM PASTI (Posisi %s -> %s, Tersedia %s -> %s): dicatat TERBUKA dan "
            "diawasi demi keamanan. Periksa Binance secara manual. Foto layar: %s",
            plan.symbol,
            before.positions,
            now.positions,
            before.available,
            now.available,
            shot,
        )

    def _fail_order(
        self, plan: OrderPlan, before: _OrderEvidence, now: _OrderEvidence, detail: str
    ) -> NoReturn:
        """Order jelas TIDAK masuk: jurnal tidak mencatat posisi sungguhan yang tidak ada."""
        shot = self._save_debug_shot("order-tidak-terkonfirmasi")
        logger.error(
            "Order Short %s TIDAK masuk di Binance (%s). Foto layar: %s", plan.symbol, detail, shot
        )
        raise ScreenReadError(
            f"Order Short {plan.symbol} tidak masuk: {detail} (Posisi {before.positions} -> "
            f"{now.positions}, Tersedia {before.available} -> {now.available}); "
            f"tidak dicatat sebagai posisi sungguhan. Foto layar: {shot}"
        )

    def close_position(self, symbol: str) -> None:
        """Tutup posisi `symbol` di bursa: tab Posisi -> baris koin -> tombol Market.

        Hanya saat Real Fund Trading. Tombol Market di baris posisi langsung menutup seluruh posisi
        koin itu (tanpa dialog). Tab, baris, dan tombol dicari di SELURUH jendela, bukan area tetap:
        uji nyata (20 Okt) halaman koin bergeser 100-200 piksel sesudah posisi terbuka, dan baris
        posisi bisa berada di bawah tepi jendela. Dengan 3-5 posisi terbuka baris koin bisa di
        bawah: halaman/tabel digulir satu langkah demi satu langkah di atas panel Posisi (bukan di
        atas grafik) sampai baris ketemu atau isinya tidak berubah lagi, lalu dikembalikan. Nama
        koin harus persis: "PEPEUSDT" tidak cocok dengan "1000PEPEUSDT". Sesudah klik, tertutup bila
        Posisi(n) berkurang, atau (bila angkanya tak terbaca) baris koin tidak terlihat lagi.
        """
        if not live_orders_enabled():
            raise SafetyError(
                "Tutup posisi sungguhan terkunci (Real Fund Trading belum dinyalakan)"
            )
        with self.screen_turn():
            self._close_position(symbol)

    def _close_position(self, symbol: str) -> None:
        if self._rect is None:  # menu Posisi (Sell manual): Binance belum disiapkan
            self.prepare()
        scrolled = 0
        sideways = False
        point = self.rect.point_at(0.30, 0.95)
        try:
            tab = self._find_text((0.0, 0.0, 1.0, 1.0), _POSITIONS_COUNT)
            if tab is None:
                self._scroll_page_down(point, _CLOSE_SCROLL_NOTCHES)
                scrolled += _CLOSE_SCROLL_NOTCHES
                tab = self._find_text((0.0, 0.0, 1.0, 1.0), _POSITIONS_COUNT)
            if tab is None and not self._on_trade_page:
                # Bot lain meninggalkan layar di halaman lain (mis. daftar top gainers). Tab Posisi
                # ada di halaman koin mana pun: buka koin teratas lewat ikon trade-nya.
                rows = self.open_top_gainers()
                if rows:
                    self.open_gainer(rows[0].rank)
                    tab = self._find_text((0.0, 0.0, 1.0, 1.0), _POSITIONS_COUNT)
            if tab is None:
                raise ScreenReadError("Tab Posisi di panel bawah Binance tidak ditemukan")
            self._click(tab)
            point = self.rect.point_at(0.30, min(0.95, tab[1] + 0.06))
            row, texts = self._position_row(symbol, tab[1])
            seen: list[str] | None = None
            for _ in range(_POSITION_PAGES):
                if row is not None or texts == seen:
                    break
                seen = texts
                self._scroll_page_down(point, 1)
                scrolled += 1
                tab = self._find_text((0.0, 0.0, 1.0, 1.0), _POSITIONS_COUNT) or tab
                row, texts = self._position_row(symbol, tab[1])
            if row is None:
                raise PositionNotFoundError(f"Posisi {symbol} tidak ada di tab Posisi Binance")
            target = self._market_button(row)
            if target is None:
                # Kolom tombol bisa tersembunyi di kanan tabel: geser tabel ke kanan.
                self._ensure_front()
                self._window.scroll_horizontal(
                    *self.rect.point_at(0.40, row), layout.POSITIONS_SCROLL_NOTCHES
                )
                sideways = True
                self._sleep(0.8)
                row = self._position_row(symbol, tab[1])[0] or row
                target = self._market_button(row)
            if target is None:
                shot = self._save_debug_shot("tombol-market")
                raise ScreenReadError(
                    f"Tombol Market di baris posisi {symbol} tidak ditemukan. Foto layar: {shot}"
                )
            before = self._order_evidence().positions
            logger.warning("ORDER SUNGGUHAN: tutup posisi %s (Market)", symbol)
            self._click(target)
            self._sleep(self._settings.settle_delay_s)
            after = self._order_evidence().positions
            still = self._position_row(symbol, tab[1])[0]
        finally:
            if sideways:
                self._ensure_front()
                self._window.scroll_horizontal(*point, -layout.POSITIONS_SCROLL_NOTCHES)
            for _ in range(-(-scrolled // _SCROLL_UP_NOTCHES)):  # kembali ke atas halaman/tabel
                self._ensure_front()
                self._window.scroll_up(*point)
                self._sleep(0.5)
        # Posisi(n) berkurang = tertutup; angka tak terbaca: baris koin tidak terlihat lagi.
        known = after is not None and before is not None
        closed = (after < before) if known else still is None  # type: ignore[operator]
        if not closed:
            raise ScreenReadError(f"Posisi {symbol} masih terlihat di tab Posisi setelah ditutup")
        logger.info("Posisi %s sudah tertutup di Binance", symbol)

    def _scroll_page_down(self, point: tuple[int, int], notches: int) -> None:
        self._ensure_front()
        self._window.scroll_down(*point, notches)
        self._sleep(0.8)

    def _position_row(self, symbol: str, below: float) -> tuple[float | None, list[str]]:
        """(tinggi baris posisi `symbol` atau None, teks di bawah tab Posisi).

        Dibatasi di kiri kolom form (x < 0,80) dan di bawah tab, supaya judul halaman koin
        ("BRUSDT Perpetual") dan toast di kanan bawah tidak dikira baris posisi. Nama harus
        persis: "PEPEUSDT" tidak cocok dengan baris "1000PEPEUSDT".
        """
        name = re.compile(rf"(?<![A-Z0-9]){re.escape(symbol.upper())}(?:PERP|(?![A-Z0-9]))")
        lines = [ln for ln in self._read_lines(self.rect) if ln.y > below + 0.02 and ln.x < 0.80]
        for line in lines:
            if name.search(line.text.replace(" ", "").upper()):
                return line.y, [ln.text for ln in lines]
        return None, [ln.text for ln in lines]

    def _market_button(self, row_y: float) -> tuple[float, float] | None:
        """Tombol "Market" di baris posisi (sejajar baris, di kiri kolom form), atau None."""
        for line in self._read_lines(self.rect):
            match = _MARKET_CLOSE.search(line.text)
            if not match or abs(line.y - row_y) >= 0.02 or line.x >= 0.80:
                continue
            x = line.x
            if line.width and len(line.text) > len(match.group()):
                mid = (match.start() + match.end()) / 2
                x = line.x - line.width / 2 + line.width * mid / len(line.text)
            return x, line.y
        return None

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
            factor = layout.OCR_UPSCALE
            if factor:  # layar kecil: teks 12-14 px diperbesar dulu agar OCR Windows membacanya
                from PIL import Image

                with Image.open(image) as raw:
                    size = (raw.width * factor, raw.height * factor)
                    raw.convert("RGB").resize(size, Image.Resampling.LANCZOS).save(image)
            return self._reader.read_lines(image)

    def _read_texts(self, area: Rect) -> list[str]:
        return [line.text for line in self._read_lines(area)]
