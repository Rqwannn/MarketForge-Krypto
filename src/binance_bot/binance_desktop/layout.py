"""Posisi elemen di Binance Desktop, sebagai titik relatif terhadap jendela (0..1).

Diukur dari Binance Desktop 2.6.0 bahasa Indonesia, jendela 1470x859 pt, halaman Futures
bertata letak "Pro". Jika tata letak, bahasa, atau ukuran jendela berubah, ukur ulang file ini.

Nilai di file ini adalah profil macOS. Di Windows, `layout_windows.py` menimpanya. Profil bisa
dipaksa lewat variabel lingkungan `BOT_LAYOUT=mac|windows` (dipakai tes agar tidak bergantung OS).
"""

import os
import sys

# True: `window-size --atur` men-maximize jendela, bukan mengubah ukurannya.
WINDOW_MAXIMIZED = False
EXPECTED_WINDOW = (1470, 859)
WINDOW_TOLERANCE = 0.02

# --------------------------------------------------------------------------- daftar Top Gainers

# Menu "Pasar" di sidebar kiri, agar navigasi selalu mulai dari halaman yang sama.
SIDEBAR_MARKET = (0.023, 0.173)
# Tab "Futures" pada daftar pasar (sub-tab USDⓈ-M terpilih secara default).
MARKET_FUTURES_TAB = (0.267, 0.388)
# Gulir halaman Pasar setelah tab Futures dibuka (0 = tidak perlu), di titik gulir ini.
FUTURES_LIST_SCROLL_NOTCHES = 0
FUTURES_LIST_SCROLL_POINT = (0.5, 0.7)
# Sub-tab USD-M bila perlu dipilih eksplisit (setelah tergulir). None = sudah terpilih bawaan.
FUTURES_USDM_TAB: tuple[float, float] | None = None
# Judul kolom "Perubahan 24jam": klik pertama = turun terdalam, klik kedua = naik tertinggi.
FUTURES_CHANGE_HEADER = (0.5325, 0.5133)
# Area OCR daftar: kolom nama pair dan perubahan 24 jam, baris 1..6.
FUTURES_LIST_AREA = (0.11, 0.53, 0.60, 0.97)
# Ikon trade di kolom "Tindakan" untuk baris 1..5 (baris 6 terpotong di layar).
FUTURES_TRADE_ICON_X = 0.924
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
# Tab "Pasar" (market order) di form, lalu kolom "Jumlah" pada tab itu.
ORDER_TAB_MARKET = (0.8575, 0.1782)
ORDER_QTY_FIELD = (0.85, 0.2939)
ORDER_QTY_AREA = (0.812, 0.268, 0.992, 0.318)

# Zona tombol order di halaman trade (x0, y0, x1, y1). Klik ke sini SELALU ditolak oleh
# navigator: beli/short belum boleh dijalankan oleh bot.
ORDER_BUTTON_ZONES: tuple[tuple[float, float, float, float], ...] = (
    (0.80, 0.47, 1.00, 0.55),  # Beli/Long dan Jual/Short pada tab Pasar
    (0.80, 0.59, 1.00, 0.67),  # Beli/Long dan Jual/Short pada tab Limit
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


if (os.environ.get("BOT_LAYOUT") or ("windows" if sys.platform == "win32" else "mac")) == "windows":
    from binance_bot.binance_desktop.layout_windows import *  # noqa: F403
