"""Posisi di website Tebbit (tebbit.io), Chrome zoom 80%, relatif terhadap jendela (0..1).

Diukur dari jendela Chrome 1470x863 pt. Zoom 80% dipakai karena pada 100% panel order di kanan
terpotong pada layar selebar 1470 pt. Hampir semua klik dicari lewat teks di layar (OCR); konstanta
di sini hanya area pencarian, area baca, dan zona terlarang.
"""

from __future__ import annotations

import os
import sys

EXPECTED_WINDOW = (1470, 863)
MIN_WINDOW = (1400, 780)  # layar lebih kecil dari ini: tata letak Tebbit tidak muat
ZOOM_STEPS_DOWN = 2  # Cmd+0 (100%) lalu dua kali Cmd+minus = 80%

# Jangkar zoom: tulisan "Futures" di menu atas berada di sekitar x ini pada zoom 80%.
NAV_FUTURES_AREA = (0.0, 0.10, 0.6, 0.17)
NAV_FUTURES_X = 0.221
NAV_FUTURES_TOLERANCE = 0.03

# Area teks menu atas untuk memeriksa login ("Log in"/"Sign up" tampil bila belum masuk).
LOGIN_AREA = (0.0, 0.10, 1.0, 0.17)

# Windows OCR membaca teks kecil (±12 px) dengan buruk: gambar diperbesar sekian kali sebelum
# dibaca (koordinat hasil tetap relatif). None = tanpa pembesaran (macOS Vision tidak butuh ini).
OCR_UPSCALE: int | None = None

# Halaman depan: daftar Gainers (tab "Gainers", sub-tab "Futures") di bawah halaman.
LIST_SEARCH_AREA = (0.0, 0.17, 0.75, 0.99)
LIST_ROWS_AREA = (0.05, 0.17, 0.90, 0.99)
SCROLL_POINT = (0.5, 0.6)
SCROLL_NOTCHES = 6
SCROLL_STEPS = 8
FUTURES_PERCENT_X = (0.70, 0.88)  # kolom "Change"
FUTURES_NAME_X = (0.05, 0.30)  # kolom nama pair
MAX_ROWS = 5

# Halaman koin (futures/contract/...).
HEADER_AREA = (0.0, 0.16, 0.34, 0.24)  # nama koin, harga, perubahan 24 jam
TIMEFRAME_AREA = (0.0, 0.26, 0.70, 0.315)  # tombol 1m 5m 15m ...
LEGEND_AREA = (0.0, 0.31, 0.665, 0.365)  # "MA 5 close 0 ..."
CHART_AREA = (0.0, 0.265, 0.665, 0.845)  # yang dikirim ke AI: toolbar, legenda, lilin, volume
ORDERBOOK_AREA = (0.665, 0.25, 0.83, 0.835)
MARGIN_AREA = (0.84, 0.185, 1.0, 0.225)  # "Cross·Merge  75X"
ORDER_TAB_AREA = (0.84, 0.22, 1.0, 0.27)  # "Limit  Market  Plan"
ORDER_FORM_AREA = (0.84, 0.22, 1.0, 0.45)  # kolom Quantity
QTY_CLICK_X = 0.87  # bagian kiri kolom (satuan USDT ada di kanan)
MA_DIALOG_AREA = (0.2, 0.35, 0.75, 0.8)  # dialog pengaturan "MA" (Length / Ok / Cancel)

# Zona terlarang: browser dan menu situs (selalu); tombol order, slider, Transfer, dan tab bawah
# (hanya di halaman koin). Bot tidak pernah perlu mengklik apa pun di sana.
ALWAYS_FORBIDDEN: tuple[tuple[float, float, float, float], ...] = (
    (0.0, 0.0, 1.0, 0.17),  # tab dan bilah alamat Chrome (ekstensi, dompet) + menu akun situs
)
CONTRACT_FORBIDDEN: tuple[tuple[float, float, float, float], ...] = (
    (0.83, 0.38, 1.0, 1.0),  # Buy/Long, Sell/Short, Stop Limit, slider, Assets, Transfer
    (0.0, 0.85, 0.83, 1.0),  # tab Open positions, Limit Order, dst.
)


def in_zone(
    target: tuple[float, float], zones: tuple[tuple[float, float, float, float], ...]
) -> bool:
    x, y = target
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in zones)


if (os.environ.get("BOT_LAYOUT") or ("windows" if sys.platform == "win32" else "mac")) == "windows":
    from binance_bot.tebbit_web.layout_tebbit_windows import *  # noqa: F403
