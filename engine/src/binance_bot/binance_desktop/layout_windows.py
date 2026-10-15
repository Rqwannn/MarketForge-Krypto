"""Posisi elemen Binance Desktop untuk Windows, sebagai titik relatif terhadap jendela (0..1).

Diukur dari Binance Desktop 2.5.2 bahasa Indonesia, jendela di-maximize pada layar 1920x1080
(area jendela 1920x1020), halaman Futures bertata letak "Pro". Nilai di sini menimpa
`layout.py` (profil macOS) saat bot berjalan di Windows. Ukur ulang bila bahasa, versi
aplikasi, tata letak, atau resolusi layar berubah.

Nilai relatif = piksel / (1920, 1020). Piksel hasil ukur dicatat di komentar.
"""

# Jendela di-maximize: `binance-bot window-size --atur` melakukannya.
WINDOW_MAXIMIZED = True
EXPECTED_WINDOW = (1920, 1020)

# --------------------------------------------------------------------------- daftar Top Gainers

# Sidebar "Pasar" (43, 195).
SIDEBAR_MARKET = (0.0224, 0.1912)
# Label "Pasar" di sidebar (44, 209) dicari dengan OCR: tinggi menu bergantung pada tampilan
# Binance di tiap laptop (Dasbor, Pasar, Beli Kripto, ... dari y 120 sampai 560).
SIDEBAR_AREA = (0.0, 0.05, 0.14, 0.60)
# Tab "Futures" pada halaman Pasar (533, 418); sub-tab Futures USD-M terpilih secara default.
MARKET_FUTURES_TAB = (0.2776, 0.4098)
# Halaman Pasar harus digulir 1 langkah (125 px) agar 5 baris pertama tidak tertutup ticker
# di bawah jendela. Titik gulir di area tabel (900, 700).
FUTURES_LIST_SCROLL_NOTCHES = 1
FUTURES_LIST_SCROLL_POINT = (0.4688, 0.6863)
# Pencarian tab Futures (y 306..673 mencakup posisi normal 418 dan bergeser banner 508) dan judul
# kolom "Perubahan" sesudah digulir (y 204..816).
MARKET_TABS_AREA = (0.10, 0.30, 0.60, 0.66)
FUTURES_HEADER_AREA = (0.30, 0.20, 0.75, 0.80)
# Sub-tab "Futures USD-M" setelah digulir (332, 405). Binance mengingat sub-tab terakhir,
# jadi dipilih ulang agar tidak jatuh ke COIN-M.
FUTURES_USDM_TAB = (0.1729, 0.3971)
# Judul kolom "Perubahan 24jam" setelah digulir (1023, 471).
FUTURES_CHANGE_HEADER = (0.5328, 0.4618)
# Area OCR: kolom nama pair sampai perubahan 24 jam, baris 1..6 (x 230..1152, y 500..985).
FUTURES_LIST_AREA = (0.12, 0.49, 0.60, 0.965)
# Ikon candle di kolom "Tindakan" (x=1742), baris 1 di y=538, jarak antarbaris 80 px.
FUTURES_TRADE_ICON_X = 0.9073
# Judul "Tindakan" (x 1724, y 471) dicari dengan OCR; ikon trade 18 px di kanan judulnya, dan di y
# yang sama dengan nama pair pada barisnya. Lebar kolom dan jarak antarbaris berbeda di tiap
# laptop, jadi posisi ikon tidak dihitung dari nilai tetap bila judulnya terbaca.
FUTURES_ACTION_AREA = (0.60, 0.20, 1.0, 0.80)
FUTURES_TRADE_ICON_DX = 0.0094
FUTURES_FIRST_ROW_Y = 0.5275
FUTURES_ROW_STEP = 0.0784
MAX_RANK = 5

# --------------------------------------------------------------------------- halaman trade

# Judul pair: tab "WUSDT Perpetual" dan "WUSDT Perp" di kiri atas (x 96..480, y 51..173).
SYMBOL_AREA = (0.05, 0.05, 0.25, 0.17)
# Tombol timeframe "15 mnt" (233, 260).
TIMEFRAME_15M = (0.1214, 0.2549)
# Toolbar grafik: tab "Grafik" (y=213) dan baris timeframe "Waktu 1 dtk 15 mnt ..." (y=260).
CHART_TOOLBAR_AREA = (0.047, 0.19, 0.642, 0.29)
# Grafik: dari baris OHLC/MA sampai sumbu waktu, termasuk panel volume (x 90..1232, y 285..845).
CHART_AREA = (0.047, 0.28, 0.642, 0.828)
# Label "Cross" dan "20x" di atas form (x 1563..1800, y 120..158).
MARGIN_AREA = (0.81, 0.118, 0.945, 0.155)
# Tab "Pasar" (1641, 193), lalu kolom "Jumlah" pada tab itu (1730, 315).
ORDER_TAB_MARKET = (0.8547, 0.1892)
ORDER_QTY_FIELD = (0.9010, 0.3088)
ORDER_QTY_AREA = (0.80, 0.26, 1.0, 0.345)

# Dropdown satuan di kolom Jumlah (panah di ujung kanan, 1735, 315). Menunya "Preferensi Unit"
# memuat kartu koin dan kartu USDT dengan pilihan "Ukuran Order"/"Margin Awal" (y 0,37..0,74), dan
# menutupi tombol Beli/Long dan Jual/Short (y 0,514..0,558). Yang diklik: "Ukuran Order" (y 0,63),
# di BAWAH tombol; klik di zona terlarang hanya boleh dari y 0,575 ke bawah.
ORDER_UNIT_BUTTON = (0.9740, 0.3088)
ORDER_UNIT_MENU_AREA = (0.60, 0.30, 1.0, 0.70)
ORDER_UNIT_MIN_Y = 0.575

# Zona tombol order (Beli/Long, Jual/Short, dan tombol "Aktifkan Akun Futures" yang menempati
# tempat yang sama bila akun belum aktif). Klik ke sini SELALU ditolak oleh navigator.
ORDER_BUTTON_ZONES = (
    (0.80, 0.50, 1.00, 0.85),
    (0.05, 0.38, 0.30, 0.45),  # widget melayang di atas grafik (jaga-jaga, sama seperti macOS)
)
