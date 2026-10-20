"""Posisi elemen di Binance Desktop, sebagai titik relatif terhadap jendela (0..1).

Diukur dari Binance Desktop 2.6.0 bahasa Indonesia, jendela 1470x859 pt, halaman Futures
bertata letak "Pro". Jika tata letak, bahasa, atau ukuran jendela berubah, ukur ulang file ini.

Nilai di file ini adalah profil macOS. Di Windows, `layout_windows.py` menimpanya. Profil bisa
dipaksa lewat variabel lingkungan `BOT_LAYOUT=mac|windows` (dipakai tes agar tidak bergantung OS).
"""

import os
import sys
from collections.abc import Sequence

from binance_bot.macos.window import Rect

# True: ukuran jendela diatur dengan men-maximize (bukan mengubah ukurannya). Dipakai di Windows.
WINDOW_MAXIMIZED = False
EXPECTED_WINDOW = (1470, 859)
WINDOW_TOLERANCE = 0.02


def window_size_problem(width: float, height: float) -> str | None:
    """Pesan bila ukuran jendela berbeda dari ukuran saat posisi klik diukur, atau None."""
    want_w, want_h = EXPECTED_WINDOW
    if abs(width - want_w) <= want_w * WINDOW_TOLERANCE and (
        abs(height - want_h) <= want_h * WINDOW_TOLERANCE
    ):
        return None
    return (
        f"Ukuran jendela {width:g}x{height:g} berbeda dari {want_w}x{want_h} "
        "yang dipakai untuk mengukur posisi klik. Atur ulang ukuran jendela Binance "
        "atau ukur ulang posisi di binance_desktop/layout.py."
    )


def window_ready(window: Rect, areas: Sequence[Rect]) -> bool:
    """Ukuran sesuai kalibrasi dan jendela utuh di dalam satu area layar."""
    size_ok = window_size_problem(window.width, window.height) is None
    return size_ok and any(area.contains(window) for area in areas)


def window_target(window: Rect, areas: Sequence[Rect]) -> Rect | None:
    """Tempat jendela Binance: ukuran kalibrasi di kiri atas area layar. None bila tak muat.

    Layar tempat jendela berada didahulukan, supaya Binance tidak pindah layar tanpa perlu.
    """
    want_w, want_h = EXPECTED_WINDOW
    center_x, center_y = window.x + window.width // 2, window.y + window.height // 2

    def holds_center(area: Rect) -> bool:
        return area.contains(Rect(center_x, center_y, 0, 0))

    for area in sorted(areas, key=lambda a: not holds_center(a)):
        if area_fits(area):
            return Rect(area.x, area.y, min(want_w, area.width), min(want_h, area.height))
    return None


def area_fits(area: Rect) -> bool:
    """Area layar cukup untuk jendela kalibrasi, dengan toleransi yang sama dengan cek ukuran
    jendela (area sedikit lebih kecil, mis. karena Dock, tetap bisa dipakai)."""
    want_w, want_h = EXPECTED_WINDOW
    return area.width >= want_w * (1 - WINDOW_TOLERANCE) and area.height >= want_h * (
        1 - WINDOW_TOLERANCE
    )


def screen_too_small(areas: Sequence[Rect]) -> str:
    want_w, want_h = EXPECTED_WINDOW
    biggest = max(areas, key=lambda a: a.width * a.height, default=None)
    have = f"{biggest.width}x{biggest.height}" if biggest else "tidak terbaca"
    return (
        f"Layar terlalu kecil untuk jendela Binance {want_w}x{want_h} (area layar {have}). "
        "Pakai resolusi layar yang lebih besar (macOS: 'More Space' di Displays) atau "
        "sembunyikan Dock/taskbar otomatis."
    )


# --------------------------------------------------------------------------- daftar Top Gainers

# Menu "Pasar" di sidebar kiri, agar navigasi selalu mulai dari halaman yang sama.
SIDEBAR_MARKET = (0.023, 0.173)
# Bila diisi, label "Pasar" di sidebar dicari dengan OCR (tata letak tiap laptop bisa berbeda) dan
# SIDEBAR_MARKET hanya dipakai bila label tidak terbaca. None = posisi tetap.
SIDEBAR_AREA: tuple[float, float, float, float] | None = None
# Tab "Futures" pada daftar pasar (sub-tab USDⓈ-M terpilih secara default).
MARKET_FUTURES_TAB = (0.267, 0.388)
# Gulir halaman Pasar setelah tab Futures dibuka (0 = tidak perlu), di titik gulir ini.
FUTURES_LIST_SCROLL_NOTCHES = 0
FUTURES_LIST_SCROLL_POINT = (0.5, 0.7)
# Sub-tab USD-M bila perlu dipilih eksplisit (setelah tergulir). None = sudah terpilih bawaan.
FUTURES_USDM_TAB: tuple[float, float] | None = None
# Banner promo (mis. "Listing Baru") bisa menggeser halaman Pasar ke bawah. Bila area ini diisi,
# tab Futures dan judul kolom "Perubahan" dicari dengan OCR dan seluruh posisi daftar digeser
# sebesar selisihnya. None = posisi tetap, tanpa pencarian.
MARKET_TABS_AREA: tuple[float, float, float, float] | None = None
FUTURES_HEADER_AREA: tuple[float, float, float, float] | None = None
# Judul kolom "Perubahan 24jam": klik pertama = turun terdalam, klik kedua = naik tertinggi.
FUTURES_CHANGE_HEADER = (0.5325, 0.5133)
# Area OCR daftar: kolom nama pair dan perubahan 24 jam, baris 1..6.
FUTURES_LIST_AREA = (0.11, 0.53, 0.60, 0.97)
# Ikon trade di kolom "Tindakan" untuk baris 1..5 (baris 6 terpotong di layar).
FUTURES_TRADE_ICON_X = 0.924
# Bila diisi, judul kolom "Tindakan" dicari dengan OCR dan ikon trade diklik di x judul + DX; y-nya
# dari baris hasil OCR. Tanpa ini, posisi ikon dihitung dari nilai tetap di atas.
FUTURES_ACTION_AREA: tuple[float, float, float, float] | None = None
FUTURES_TRADE_ICON_DX = 0.0
FUTURES_FIRST_ROW_Y = 0.574
FUTURES_ROW_STEP = 0.0745
MAX_RANK = 5

# --------------------------------------------------------------------------- halaman trade

# Judul pair (mis. "STRKUSDT Perp") untuk dibaca dengan OCR.
SYMBOL_AREA = (0.05, 0.05, 0.36, 0.17)
# Tombol timeframe "15 mnt" di atas grafik: posisi acuan saja. Navigator mencarinya dengan OCR
# di CHART_TOOLBAR_AREA karena banner di halaman koin tertentu menggeser tata letak ke bawah.
TIMEFRAME_15M = (0.1265, 0.2416)
CHART_TOOLBAR_AREA = (0.05, 0.15, 0.62, 0.40)
# Grafik: dari baris OHLC/MA sampai sumbu waktu, termasuk panel volume.
CHART_AREA = (0.0485, 0.2725, 0.6015, 0.7815)
# Label mode margin dan leverage di atas form (mis. "Cross", "20x").
MARGIN_AREA = (0.81, 0.11, 0.95, 0.15)
# Pembesaran gambar sebelum OCR (None = tidak). Layar kecil memakai teks 12-14 px yang dibaca buruk.
OCR_UPSCALE: int | None = None
# Kotak angka leverage ("2x") di dalam MARGIN_AREA, pecahan lebarnya. None = tidak dipakai.
LEVERAGE_BOX_X: tuple[float, float] | None = None
# Dialog "Sesuaikan Leverage" yang terbuka dari label leverage (di tengah jendela).
LEVERAGE_DIALOG_AREA = (0.30, 0.15, 0.75, 0.90)
# Tab "Pasar" (market order) di form, lalu kolom "Jumlah" pada tab itu.
ORDER_TAB_MARKET = (0.8575, 0.1782)
ORDER_QTY_FIELD = (0.85, 0.2939)
ORDER_QTY_AREA = (0.812, 0.268, 0.992, 0.318)
# Baris "Tersedia 58,70 USDT" (saldo yang bisa dipakai sebagai margin) di atas kolom Jumlah.
ORDER_AVAILABLE_AREA = (0.80, 0.20, 1.0, 0.25)

# Dropdown satuan kolom Jumlah (koin/USDT) dan menu "Preferensi Unit" yang terbuka darinya. Binance
# mengembalikan satuan ke koin tiap pindah koin, jadi bot memilih USDT sendiri. None = tidak
# diotomatiskan (bot berhenti dan meminta pengguna memilih USDT). Menu itu menutupi tombol order,
# jadi klik di zona terlarang HANYA boleh pada ORDER_UNIT_MIN_Y ke bawah (di bawah tombol).
ORDER_UNIT_BUTTON: tuple[float, float] | None = None
ORDER_UNIT_MENU_AREA: tuple[float, float, float, float] | None = None
ORDER_UNIT_MIN_Y = 1.0

# Panel bawah halaman trade: tab "Posisi(n)" dan tabel posisi terbuka. Tabelnya lebih lebar dari
# jendela: tombol tutup "Market" (langsung menutup, tanpa dialog) baru terlihat setelah tabel
# digulir ke kanan. Klik di sini hanya lewat navigator.close_position (Real Fund Trading).
POSITIONS_TAB_AREA = (0.05, 0.79, 0.60, 0.85)
POSITIONS_TABLE_AREA = (0.05, 0.85, 0.82, 1.0)
POSITIONS_SCROLL_NOTCHES = 12

# Tinggi tab "Posisi(n)" saat halaman tanpa banner; None = pergeseran panel tidak diukur.
POSITIONS_TAB_Y: float | None = None

# Titik kosong di bilah judul Binance (tanpa kontrol apa pun). Cara terakhir merebut fokus lewat
# klik asli, bila Windows menolak SetForegroundWindow (mis. jendela notifikasi memegang fokus).
# None = tidak dipakai.
FOCUS_POINT: tuple[float, float] | None = None

# Zona tombol order di halaman trade (x0, y0, x1, y1). Klik ke sini SELALU ditolak oleh
# navigator: beli/short belum boleh dijalankan oleh bot.
ORDER_BUTTON_ZONES: tuple[tuple[float, float, float, float], ...] = (
    # Beli/Long dan Jual/Short pada tab Pasar dan Limit. Satu zona lebar: opsi form yang dicentang
    # (mis. Toleransi Slippage dengan kolom isiannya) menggeser tombol ke bawah sampai ~0,56.
    (0.80, 0.45, 1.00, 0.67),
    (0.05, 0.38, 0.30, 0.45),  # widget Beli/Long-Jual/Short yang melayang di atas grafik
)


def in_order_button_zone(target: tuple[float, float]) -> bool:
    x, y = target
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in ORDER_BUTTON_ZONES)


def trade_icon(rank: int) -> tuple[float, float]:
    """Ikon trade pada baris `rank` daftar Futures yang sudah diurutkan."""
    if not 1 <= rank <= MAX_RANK:
        raise ValueError(f"Rank harus 1..{MAX_RANK}, bukan {rank}")
    return FUTURES_TRADE_ICON_X, FUTURES_FIRST_ROW_Y + (rank - 1) * FUTURES_ROW_STEP


def rank_at(window_y: float) -> int:
    """Nomor baris daftar Futures untuk posisi vertikal (relatif jendela)."""
    return round((window_y - FUTURES_FIRST_ROW_Y) / FUTURES_ROW_STEP) + 1


def _work_area_width() -> int | None:
    """Lebar area kerja layar utama Windows dalam piksel fisik (di luar taskbar), atau None."""
    try:
        import ctypes
        from ctypes import wintypes

        from binance_bot.windows import win32

        win32.ensure_dpi_aware()
        area = wintypes.RECT()
        spi_getworkarea = 0x0030
        if not ctypes.windll.user32.SystemParametersInfoW(
            spi_getworkarea, 0, ctypes.byref(area), 0
        ):
            return None
        return int(area.right - area.left)
    except (AttributeError, ImportError, OSError):
        return None


def _profile() -> str:
    """Profil posisi: `BOT_LAYOUT` memaksa (mac, windows, windows-1366); selain itu dipilih dari
    sistem dan ukuran layar. Layar Windows yang lebih sempit dari 1700 px (mis. laptop 1366x768)
    memakai profil 1366; yang lebih lebar memakai profil 1920x1080."""
    forced = os.environ.get("BOT_LAYOUT")
    if forced:
        return forced
    if sys.platform != "win32":
        return "mac"
    width = _work_area_width()
    return "windows-1366" if width is not None and width < 1700 else "windows"


PROFILE = _profile()
if PROFILE == "windows":
    from binance_bot.binance_desktop.layout_windows import *  # noqa: F403
elif PROFILE == "windows-1366":
    from binance_bot.binance_desktop.layout_windows_1366 import *  # noqa: F403
