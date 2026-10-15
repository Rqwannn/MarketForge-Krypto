"""Profil Windows untuk tata letak Tebbit: menimpa nilai di `layout_tebbit.py` (profil macOS).

Semua posisi relatif terhadap ISI HALAMAN Chrome (tanpa tab, bilah alamat, dan bilah bookmark;
lihat `WinChromeController.content_bounds`), bukan seluruh jendela. Dengan begitu tinggi bilah
atas Chrome yang berbeda di tiap laptop tidak menggeser apa pun.

Diukur dari Chrome di layar 1920x1080 skala 125% (isi halaman 1919x869 piksel), zoom 80%. Zoom
dipilih agar zoom x skala tampilan mendekati 1,0 seperti di Mac Raqwan: layar skala 125% memakai
zoom 80%, skala 100% memakai 100%. Ukur ulang bila tata letak situs Tebbit berubah.
"""

from __future__ import annotations

# Jendela Chrome mengisi area kerja layar (di luar taskbar).
EXPECTED_WINDOW = (1920, 1040)
MIN_WINDOW = (1400, 780)

_ZOOM_LEVELS = (100, 90, 80, 75, 67, 50, 33, 25)  # urutan Ctrl+minus di Chrome


def _display_scale() -> float:
    """Skala tampilan Windows (125% = 1,25). Proses harus sadar-DPI agar angkanya sebenarnya."""
    from binance_bot.windows import win32

    win32.ensure_dpi_aware()
    try:
        return float(win32.user32.GetDpiForSystem()) / 96.0
    except (AttributeError, OSError):
        return 1.0


def zoom_steps_down(scale: float) -> int:
    """Jumlah Ctrl+minus (dari 100%) supaya zoom x skala tampilan mendekati 1,0."""
    wanted = 100.0 / scale
    return min(range(len(_ZOOM_LEVELS)), key=lambda i: abs(_ZOOM_LEVELS[i] - wanted))


ZOOM_STEPS_DOWN = zoom_steps_down(_display_scale())

OCR_UPSCALE = 2
OCR_QUOTE_VARIANTS = (("max", 3), ("max", 2), ("gray", 2))
OCR_LEGEND_VARIANTS = (("max", 2), ("max", 3), ("max", 4), ("gray", 2))

# Menu atas situs: "Futures" di x 0,21 y 0,04 (jangkar zoom); bila login, email tampil di kanan.
NAV_FUTURES_AREA = (0.0, 0.0, 0.6, 0.09)
NAV_FUTURES_X = 0.212
NAV_FUTURES_TOLERANCE = 0.03
LOGIN_AREA = (0.0, 0.0, 1.0, 0.09)

# Beranda setelah digulir 6 langkah: tab "Gainers" di y 0,345, "Futures" 0,41, baris pertama 0,525
# dengan jarak 0,0645; kolom "Change" di x 0,70 dan nama pair di x 0,25.
LIST_SEARCH_AREA = (0.0, 0.05, 0.75, 0.99)
LIST_ROWS_AREA = (0.05, 0.45, 0.90, 0.99)
SCROLL_POINT = (0.5, 0.6)
FUTURES_PERCENT_X = (0.65, 0.80)
FUTURES_NAME_X = (0.05, 0.32)

# Halaman koin (diukur pada TRUTHUSDT).
HEADER_AREA = (0.0, 0.09, 0.36, 0.16)  # nama koin, harga, perubahan 24 jam
TIMEFRAME_AREA = (0.0, 0.20, 0.55, 0.26)  # "Time 1m 5m 15m 30m 1H ..." di y 0,23
LEGEND_AREA = (0.0, 0.285, 0.655, 0.325)  # "MA 5 close 0 ... MA 30 close 0" di y 0,30
CHART_AREA = (0.0, 0.20, 0.655, 0.925)  # toolbar, legenda, lilin, volume
ORDERBOOK_AREA = (0.668, 0.19, 0.826, 0.91)
MARGIN_AREA = (0.835, 0.10, 1.0, 0.155)  # "Cross-Merge  75X"
ORDER_TAB_AREA = (0.835, 0.15, 1.0, 0.21)  # "Limit  Market  Plan"
ORDER_FORM_AREA = (0.835, 0.21, 1.0, 0.40)  # kolom Quantity
QTY_CLICK_X = 0.87

# Zona terlarang. Menu atas situs (akun, dompet): tidak pernah perlu diklik. Di halaman koin:
# semua di bawah kolom Quantity (slider, Buy/Long, Sell/Short, Transfer) dan tab bawah.
ALWAYS_FORBIDDEN = ((0.0, 0.0, 1.0, 0.075),)
CONTRACT_FORBIDDEN = (
    (0.83, 0.335, 1.0, 1.0),
    (0.0, 0.92, 0.83, 1.0),
)
