# Menjalankan di Windows

Bot sekarang punya lapisan sistem Windows (`src/binance_bot/windows/`) di samping lapisan macOS.
`system.py` memilih otomatis sesuai OS. Logika SOP, jurnal, hub, dan AI tidak berubah.

| Fungsi | macOS | Windows |
|---|---|---|
| Buka / cek aplikasi | `open`, `lsappinfo` | `os.startfile`, `tasklist`, Win32 (`Binance.exe`) |
| Posisi jendela | `osascript` | Win32 `DwmGetWindowAttribute` |
| Klik, gulir, ketik angka | CoreGraphics | Win32 `SendInput` (tanpa Enter, hanya angka) |
| Screenshot | `screencapture` | Pillow `ImageGrab` |
| OCR | Vision framework | `Windows.Media.Ocr` (bawaan Windows 10/11) |

Pengaman tetap sama: tombol order tidak pernah ditekan, hanya angka yang bisa diketik.

## Setup

PowerShell, dari folder repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env     # lalu isi VIKEY_API_KEY dst.
```

Perintah `make` tidak dipakai di Windows. Panggil CLI langsung:

```powershell
.\.venv\Scripts\binance-bot open
.\.venv\Scripts\binance-bot window-size --atur
.\.venv\Scripts\binance-bot uji-isi --rank 1 --jumlah 200
.\.venv\Scripts\binance-bot single --ranks 1,2,3 --modal 100
.\.venv\Scripts\binance-bot jurnal
```

Parameter SOP sama dengan tabel di Makefile (`--sl`, `--target`, `--min-naik`, `--min-tanda`,
`--batas-jam`, `--maks-posisi`, `--sinyal`, `--no-fill`). Token hub: `openssl rand -hex 16`
diganti `python -c "import secrets; print(secrets.token_hex(16))"`.

## Syarat

1. Binance Desktop untuk Windows (diuji v2.5.2), **bahasa Indonesia**, sudah login. Bila
   `binance-bot open` tidak menemukan aplikasinya, isi `BOT_APP_PATH` di `.env`.
2. **Layar 1920x1080** dengan jendela Binance di-maximize (area 1920x1020). Atur lewat
   `binance-bot window-size --atur`. Resolusi lain butuh ukur ulang `layout_windows.py`.
3. **Izinkan screenshot di Binance.** Secara bawaan Binance Desktop memblokir tangkapan layar
   (`WDA_EXCLUDEFROMCAPTURE`), sehingga bot hanya melihat jendela di belakangnya. Matikan
   pengaturan "perlindungan layar" di aplikasi (jangan klik "Aktifkan perlindungan layar" pada
   banner keamanan). Bot tidak mencoba menembus proteksi ini.
4. Paket OCR Windows: Settings > Time & language > Language & region, pastikan ada bahasa dengan
   fitur OCR (English cukup).
5. Jalankan terminal **bukan sebagai Administrator** kecuali Binance juga dijalankan sebagai
   Administrator (Windows memblokir input ke jendela yang lebih tinggi hak aksesnya).
6. Jangan menyentuh mouse/keyboard saat bot bekerja: bot memakai kursor dan keyboard sungguhan,
   dan memastikan Binance di depan sebelum klik, mengetik, atau mengambil screenshot.

## Kalibrasi

Posisi klik Windows ada di `binance_desktop/layout_windows.py` (menimpa `layout.py` yang diukur
dari macOS). `BOT_LAYOUT=mac|windows` memaksa profil tertentu. Ukuran: piksel / (1920, 1020).

Alur Windows: Pasar > tab Futures > gulir 1 langkah (agar 5 baris terlihat) > pilih sub-tab
Futures USD-M > urutkan "Perubahan 24jam" > klik ikon candle di kolom "Tindakan" > halaman trade.

Uji kalibrasi (hasilnya harus `BERHASIL`; lalu kosongkan kolom Jumlah):

```powershell
.\.venv\Scripts\binance-bot window-size --atur
.\.venv\Scripts\binance-bot uji-isi --rank 1 --jumlah 200
```

Gunakan jumlah di atas kuantitas minimum pair itu. Angka terlalu kecil memunculkan tooltip
"Kuantitas Minimum ..." dan OCR kerap gagal membaca satu digit.

## Perbedaan perilaku dibanding macOS

- Zona tombol order (Beli/Long, Jual/Short, dan "Aktifkan Akun Futures") ditolak untuk diklik.
- OCR Windows lebih goyah pada teks kecil: potongan pendek diperbesar dan dibaca dengan beberapa
  varian, serta verifikasi kolom Jumlah diulang sampai 4 kali (kursor berkedip mengganggu).
- Akun Futures belum aktif tetap bisa dipakai: halaman trade dan kolom Jumlah tetap tampil.

## Status verifikasi

Diuji langsung terhadap Binance Desktop 2.5.2 (Indonesia, 1920x1020): buka aplikasi, urut top
gainer (6 dari 6 percobaan), buka rank 1 dan 2, baca pair, baca "Cross 20x", isi dan verifikasi
kolom Jumlah (`uji-isi` berhasil). **Belum diuji:** alur `single`/`leader` penuh (analisis AI
terhadap grafik, jurnal) di Binance Windows, dan layar selain 1920x1080.
