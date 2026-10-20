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

PowerShell, dari root repo. Engine ada di `engine/`; `.env` dibaca dari folder tempat bot dijalankan,
jadi jalankan perintah dari `engine\`:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e "engine[dev]"
cd engine
copy .env.example .env     # lalu isi VIKEY_API_KEY dst.
```

Perintah `make` tidak dipakai di Windows. Panggil CLI langsung (dari `engine\`):

```powershell
..\.venv\Scripts\binance-bot cek                 # kesiapan laptop (JSON)
..\.venv\Scripts\binance-bot open
..\.venv\Scripts\binance-bot window-size --atur
..\.venv\Scripts\binance-bot uji-isi --rank 1 --jumlah 200
..\.venv\Scripts\binance-bot single --ranks 1,2,3 --modal 100
..\.venv\Scripts\binance-bot jurnal
```

Parameter SOP sama dengan tabel di Makefile (`--sl`, `--target`, `--min-naik`, `--min-tanda`,
`--batas-jam`, `--sinyal`, `--no-fill`). Token hub: `openssl rand -hex 16`
diganti `python -c "import secrets; print(secrets.token_hex(16))"`.

## Syarat

1. Binance Desktop untuk Windows (diuji v2.5.2), **bahasa Indonesia**, sudah login. Bila
   `binance-bot open` tidak menemukan aplikasinya, isi `BOT_APP_PATH` di `.env`.
2. **Layar 1920x1080 (skala 125%)** atau **1366x768 (skala 100%)** dengan jendela Binance
   di-maximize (area 1920x1020 atau 1366x720). Atur lewat `binance-bot window-size --atur`. Profil
   dipilih otomatis dari lebar area kerja layar utama (di bawah 1700 px = profil 1366). Resolusi atau
   skala lain butuh ukur ulang.
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

Posisi klik Windows ada di `engine/src/binance_bot/binance_desktop/layout_windows.py` (layar 1920x1080;
menimpa `layout.py` yang diukur dari macOS) dan `layout_windows_1366.py` (layar 1366x768).
`BOT_LAYOUT=mac|windows|windows-1366` memaksa profil tertentu. Ukuran: piksel / (1920, 1020) atau
piksel / (1366, 720).

### Tombol Beli/Long dan Jual/Short

Tombolnya dicari lewat **warna** (persegi pekat hijau dan merah berdampingan di form order), lalu dipastikan
dengan teksnya ("Beli/Long" di kiri, "Jual/Short" di kanan; pasangan yang tertukar ditolak). Sebelumnya hanya
lewat OCR teks, yang menemukan Jual/Short di 7 dari 33 foto layar Full HD karena teks putih di atas warna
pekat sulit dibaca. Sekarang ketemu di 54 dari 54 foto yang tombolnya tampil (Full HD dan 1366x768, termasuk
halaman berbanner); yang tidak ketemu hanya foto saat belum login (form berisi "Daftar" dan "Masuk").
Pencarian lewat teks tetap jadi cadangan, dan Tebbit memakainya saja. Kode: `binance_desktop/order_buttons.py`.
Tombol hanya **dicari**; yang menekannya tetap hanya `press_short` saat Real Fund Trading menyala.

### Layar 1366x768

Profil 1366 diukur 19 Okt 2026 pada laptop 1366x768 skala 100% (Binance Desktop 2.5.2). Bedanya dari
profil 1920: teks Binance hanya 12-14 px, jadi semua bacaan OCR diperbesar 2x dulu (`OCR_UPSCALE`);
baris daftar Futures lebih rapat (64 px); dan panel "Posisi" di bawah halaman trade tidak tampil di
tinggi 720 px, sehingga tutup posisi sungguhan lewat tab Posisi tidak tersedia di layar ini (uji
kertas tidak terpengaruh). Diuji: `uji-isi`, dua putaran `single` lima koin (daftar, grafik 15 menit,
AI), dan bacaan leverage 2x. Belum diuji: koin berbanner di layar ini, dialog Sesuaikan Leverage
sampai Konfirmasi, dan Tebbit (zoom Chrome otomatis 75%, tapi tata letaknya belum dikalibrasi).

Alur Windows: Pasar > tab Futures > gulir 1 langkah (agar 5 baris terlihat) > pilih sub-tab
Futures USD-M > urutkan "Perubahan 24jam" > klik ikon candle di kolom "Tindakan" > halaman trade.

Uji kalibrasi (hasilnya harus `BERHASIL`; lalu kosongkan kolom Jumlah):

```powershell
..\.venv\Scripts\binance-bot window-size --atur
..\.venv\Scripts\binance-bot uji-isi --rank 1 --jumlah 200
```

Gunakan jumlah di atas kuantitas minimum pair itu. Angka terlalu kecil memunculkan tooltip
"Kuantitas Minimum ..." dan OCR kerap gagal membaca satu digit.

## Perbedaan perilaku dibanding macOS

- Zona tombol order (Beli/Long, Jual/Short, dan "Aktifkan Akun Futures") ditolak untuk diklik.
- OCR Windows lebih goyah pada teks kecil: potongan pendek diperbesar dan dibaca dengan beberapa
  varian, serta verifikasi kolom Jumlah diulang sampai 4 kali (kursor berkedip mengganggu).
- Akun Futures belum aktif tetap bisa dipakai: halaman trade dan kolom Jumlah tetap tampil.
- Saldo "Tersedia": huruf O di dalam angka dibaca nol (dompet kosong terbaca "O,OO", uji nyata 19 Okt),
  jadi dilaporkan "saldo 0,00 kurang dari margin", bukan "tidak terbaca". Teks tanpa angka atau pemisah
  desimal tetap dianggap tidak terbaca (bot tidak masuk).
- Halaman koin yang lambat tampil ditunggu: pair dibaca sampai 3 kali dan toolbar "15 mnt" ditunggu
  sampai 15 detik, tidak langsung menyerah (uji nyata 20 Okt: BRUSDT terlewat karena halaman masih memuat).
- Klik ikon trade yang hilang (daftar Pasar tetap di layar, uji nyata: NILUSDT, AVAUSDT) diulang sekali,
  hanya bila judul kolom "Tindakan" terbukti masih terbaca; bila daftarnya sudah tidak ada, tidak ada klik
  ulang supaya tidak mendarat di halaman koin. Pengecekan kolom Jumlah sebelum klik order juga dibaca sampai
  4 kali dan tetap harus persis angka rencana (uji nyata: AGTUSDT terbaca "24" padahal 20).
- Fokus macet: Windows bisa menolak `SetForegroundWindow`. Uji nyata 20 Okt: jendela "New notification"
  (ShellExperienceHost) memegang fokus berjam-jam dan Alt, AttachThreadInput, serta SwitchToThisWindow
  ditolak semua. Setelah dua usaha biasa gagal, bot mengklik titik kosong di bilah judul Binance
  (`FOCUS_POINT` di tata letak; tanpa kontrol apa pun dan jauh dari zona order), karena klik asli selalu
  mengaktifkan jendela. Profil macOS tidak punya titik itu, jadi tidak ada klik. Selama uji tanpa
  pengawasan, nyalakan "Jangan Ganggu" Windows agar notifikasi tidak merebut fokus.

## Status verifikasi

Diuji langsung terhadap Binance Desktop 2.5.2 (Indonesia, 1920x1020): buka aplikasi, urut top
gainer (6 dari 6 percobaan), buka rank 1 dan 2, baca pair, baca "Cross 20x", isi dan verifikasi
kolom Jumlah (`uji-isi` berhasil). **Belum diuji:** alur `single`/`leader` penuh (analisis AI
terhadap grafik, jurnal) di Binance Windows, dan layar selain 1920x1080.

## Aplikasi desktop (interface/)

Aplikasi Electron di `interface/` (lihat [APLIKASI.md](APLIKASI.md)) jalan di Windows. Tanpa `make`:

```powershell
cd interface
npm ci          # sekali: memasang Electron
npm start       # membuka aplikasi
npm test        # tes interface (tanpa membuka jendela)
```

Yang disesuaikan untuk Windows:

- `engine.js` memilih virtualenv yang pustakanya lengkap (ada Pillow): `engine\.venv` atau `.venv` di
  root repo. Venv kosong (mis. sisa Python lama) dilewati. Engine dijalankan dengan `python.exe -m binance_bot` (bukan `binance-bot.exe`, yang hanya peluncur sehingga
  menghentikannya tidak menghentikan engine).
- Tombol **Hentikan** memakai `taskkill /T /F` karena Windows tidak punya SIGINT untuk proses anak.
  Engine berhenti seketika; posisi uji yang sedang berjalan tidak diselesaikan dulu.
- `npm start` memakai `start.js` (pengganti `env -u ELECTRON_RUN_AS_NODE`).
- Halaman **Cek laptop** menampilkan petunjuk Windows (blokir screenshot, bukan izin macOS).
- Engine dijalankan dengan `PYTHONUTF8=1` agar log berbahasa Indonesia tidak gagal di konsol.

Pengaturan `interface\.env` (opsional) menimpa `engine\.env`, sama seperti di macOS.

## Platform Tebbit (website di Chrome)

Alur Tebbit (`--bursa tebbit`, atau pilih Tebbit di aplikasi) sudah berjalan di Windows. Yang berbeda
dari macOS:

- **Kendali Chrome:** jendela Chrome baru dibuka lewat `chrome.exe --new-window` (Chrome dicari di
  `Program Files`; atau isi `BOT_CHROME_PATH` di `.env`). Alamat tab dibaca lewat UI Automation
  (PowerShell), bukan AppleScript. Sesi login Chrome yang terakhir dipakai terbawa; **login ke
  Tebbit sekali di Chrome**, lalu jalankan bot.
- **Pengaman fokus:** Windows tidak bisa mengirim tombol ke jendela tertentu, jadi tombol selalu
  masuk ke jendela aktif. Sebelum mengetik alamat atau mengatur zoom, bot memastikan jendela Tebbit
  miliknya yang aktif (dan memeriksa lagi saat mengetik). Bila Windows menolak membawanya ke depan,
  bot berhenti dan tidak mengirim tombol apa pun. Satu-satunya teks yang diketik ke Chrome adalah
  alamat `tebbit.io`.
- **Zoom mengikuti skala layar:** zoom Chrome x skala tampilan Windows dijaga mendekati 1,0
  (skala 125% memakai zoom 80%, skala 100% memakai 100%), seperti tampilan Mac yang diukur.
- **Posisi relatif terhadap isi halaman** (`Chrome_RenderWidgetHostHWND`), bukan seluruh jendela,
  sehingga bilah bookmark atau ekstensi tidak menggeser kalibrasi. Profilnya ada di
  `engine/src/binance_bot/tebbit_web/layout_tebbit_windows.py`.
- **OCR:** teks tabel Tebbit kecil, jadi gambar diperbesar 2x sebelum dibaca (`OCR_UPSCALE`).
- Jendela Chrome yang dibuka bot tidak ditutup otomatis di akhir putaran (sama seperti di macOS);
  tutup sendiri bila menumpuk.

Diverifikasi di Windows 11 (layar 1920x1080, skala 125%, Chrome 14 Okt 2026): daftar Top 5, halaman
koin, grafik 15 menit, margin, bid/ask, mengisi kolom Quantity (USDT), dan satu putaran `single`
lengkap dengan AI. Belum diuji: mode pemimpin/pengikut lewat Tebbit, layar skala selain 125%.
