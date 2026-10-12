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
.\.venv\Scripts\binance-bot uji-isi --rank 1 --jumlah 1
.\.venv\Scripts\binance-bot single --ranks 1,2,3 --modal 100
.\.venv\Scripts\binance-bot jurnal
```

Parameter SOP sama dengan tabel di Makefile (`--sl`, `--target`, `--min-naik`, `--min-tanda`,
`--batas-jam`, `--maks-posisi`, `--sinyal`, `--no-fill`). Token hub: `openssl rand -hex 16`
diganti `python -c "import secrets; print(secrets.token_hex(16))"`.

## Syarat

1. Binance Desktop untuk Windows, bahasa Indonesia, tata letak Futures **Pro**, sudah login.
   Bila `binance-bot open` tidak menemukan aplikasinya, isi `BOT_APP_PATH` di `.env` dengan path
   lengkap `Binance.exe`.
2. Paket OCR Windows: Settings > Time & language > Language & region, pastikan ada bahasa dengan
   fitur OCR (English cukup).
3. Jalankan terminal **bukan sebagai Administrator** kecuali Binance juga dijalankan sebagai
   Administrator (Windows memblokir input ke jendela yang lebih tinggi hak aksesnya).

## Kalibrasi (wajib dilakukan sekali)

Posisi klik di `binance_desktop/layout.py` diukur dari Binance Desktop **di macOS**, jendela
1470x859. Versi Windows bisa punya bingkai/judul jendela dan tata letak yang sedikit beda, jadi
pastikan dulu sebelum mempercayai hasilnya:

1. `binance-bot window-size --atur` harus menampilkan `OK` (ukuran dalam piksel fisik).
2. `binance-bot uji-isi --rank 1 --jumlah 1` harus berakhir `BERHASIL`, lalu kosongkan kolom Jumlah.
3. Bila klik meleset, ukur ulang konstanta di `layout.py` (titik relatif 0..1 terhadap jendela).
   Screenshot jendela ada di folder `screenshots/` untuk membantu mengukur.

Layar dengan scaling (125%/150%) aman: proses memakai piksel fisik, tetapi ukuran 1470x859
piksel harus muat di layar Anda.

## Belum terverifikasi

Lapisan Windows diuji terhadap Notepad (cari jendela, bounds, klik, ketik angka, screenshot,
OCR) dan unit test lulus. **Belum diuji terhadap Binance Desktop** karena aplikasinya belum
terpasang di mesin pengembangan. Kalibrasi layout di atas adalah langkah yang membuktikannya.
