"""Posisi elemen Binance Desktop untuk Windows di layar 1366x768 (skala 100%).

Diukur dari Binance Desktop 2.5.2 bahasa Indonesia, jendela di-maximize (area kerja 1366x720,
taskbar 48 px), halaman Futures bertata letak "Pro". Dipilih otomatis bila lebar area kerja layar
utama kurang dari 1700 px (lihat `layout.py`); layar 1920x1080 memakai `layout_windows.py`.

Nilai relatif = piksel / (1366, 720). Piksel hasil ukur dicatat di komentar. Perbedaan penting dari
profil 1920x1020: tinggi jendela hanya 720 px, jadi panel Posisi di bawah halaman trade tidak
tampil (tutup posisi sungguhan lewat tab Posisi tidak tersedia di layar ini), dan baris daftar
Futures lebih rapat (64 px, bukan 80 px).
"""

# Jendela di-maximize: `binance-bot window-size --atur` melakukannya.
WINDOW_MAXIMIZED = True
EXPECTED_WINDOW = (1366, 720)

# Bilah judul Binance setinggi 45 px: (341, 22) kosong, di antara tombol muat ulang dan kotak
# pencarian. Cara terakhir merebut fokus (lihat layout.FOCUS_POINT).
FOCUS_POINT = (0.25, 0.0306)

# Teks Binance di layar ini 12-14 px: semua bacaan OCR diperbesar 2x dulu.
OCR_UPSCALE = 2

# --------------------------------------------------------------------------- daftar Top Gainers

# Sidebar "Pasar" (34, 155); labelnya dicari dengan OCR, posisi tetap hanya bila tak terbaca.
SIDEBAR_MARKET = (0.0249, 0.2153)
SIDEBAR_AREA = (0.0, 0.05, 0.14, 0.75)
# Tab "Futures" pada halaman Pasar (341, 334).
MARKET_FUTURES_TAB = (0.2496, 0.4639)
# Halaman Pasar digulir 1 langkah (100 px) agar 5 baris pertama tidak tertutup ticker di bawah.
FUTURES_LIST_SCROLL_NOTCHES = 1
FUTURES_LIST_SCROLL_POINT = (0.5124, 0.6944)
# Pencarian tab Futures (y 216..576 mencakup posisi normal 334 dan bergeser banner) dan judul kolom
# "Perubahan" sesudah digulir.
MARKET_TABS_AREA = (0.10, 0.30, 0.60, 0.80)
FUTURES_HEADER_AREA = (0.30, 0.20, 0.75, 0.80)
# Sub-tab "Futures USD-M" setelah digulir (180, 288) dan judul "Perubahan 24jam" (734, 342).
FUTURES_USDM_TAB = (0.1318, 0.4)
FUTURES_CHANGE_HEADER = (0.5373, 0.475)
# Area OCR: kolom nama pair sampai perubahan 24 jam, baris 1..5 (x 110..820, y 360..688).
FUTURES_LIST_AREA = (0.08, 0.50, 0.60, 0.955)
# Ikon candle di kolom "Tindakan" (x=1308), baris 1 di y=394, jarak antarbaris 64 px.
FUTURES_TRADE_ICON_X = 0.9575
FUTURES_ACTION_AREA = (0.60, 0.20, 1.0, 0.80)
FUTURES_TRADE_ICON_DX = 0.0102
FUTURES_FIRST_ROW_Y = 0.5472
FUTURES_ROW_STEP = 0.0889
MAX_RANK = 5

# --------------------------------------------------------------------------- halaman trade

# Judul pair: tab "ARIAUSDT Perpetual" (y 60) dan "ARIAUSDT Perp" (y 118) di kiri atas.
SYMBOL_AREA = (0.05, 0.05, 0.25, 0.18)
# Tombol timeframe "15 mnt" (186, 210).
TIMEFRAME_15M = (0.1362, 0.2917)
# Toolbar grafik: tab "Grafik" (y 171) dan baris timeframe (y 210). Dibuat tinggi karena banner di
# halaman koin tertentu menggeser toolbar sekitar 60 px ke bawah.
CHART_TOOLBAR_AREA = (0.05, 0.15, 0.60, 0.45)
# Grafik: dari baris OHLC (y 247) sampai sumbu waktu (y 658), termasuk panel volume (x 70..820).
CHART_AREA = (0.0512, 0.326, 0.60, 0.928)
# Tombol "Cross", leverage ("2x") dan "M" di atas form (x 1115..1305, y 100..126). Area lebar karena
# OCR menjatuhkan teks sependek "2x" pada potongan sempit; kotak angkanya dibaca terpisah.
MARGIN_AREA = (0.80, 0.11, 1.0, 0.21)
LEVERAGE_BOX_X = (0.42, 0.57)
# Tab "Pasar" (1178, 155), lalu kolom "Jumlah" pada tab itu (1190, 252; satuan USDT di 1330).
ORDER_TAB_MARKET = (0.8624, 0.2153)
ORDER_QTY_FIELD = (0.8712, 0.35)
ORDER_QTY_AREA = (0.80, 0.28, 1.0, 0.39)
ORDER_AVAILABLE_AREA = (0.80, 0.24, 1.0, 0.29)

# Dropdown satuan di kolom Jumlah (panah di ujung kanan, 1330, 252). Menunya "Preferensi Unit"
# (x 980..1340, y 280..553) memuat kartu koin dan USDT dengan pilihan "Ukuran Order" (y 515) dan
# menutupi tombol Beli/Long dan Jual/Short (y 422..457). "Ukuran Order" ada di BAWAH tombol, jadi
# klik di zona terlarang hanya boleh dari y 0,68 ke bawah.
ORDER_UNIT_BUTTON = (0.9737, 0.35)
ORDER_UNIT_MENU_AREA = (0.70, 0.36, 1.0, 0.80)
ORDER_UNIT_MIN_Y = 0.68

# Zona tombol order (Beli/Long dan Jual/Short, y 422..457 pada form bersih; opsi yang dicentang
# menggesernya ke bawah). Klik ke sini SELALU ditolak oleh navigator.
ORDER_BUTTON_ZONES = (
    (0.80, 0.52, 1.00, 0.85),
    (0.05, 0.44, 0.33, 0.55),  # widget melayang di atas grafik (x 85..427, y 335..380)
)
