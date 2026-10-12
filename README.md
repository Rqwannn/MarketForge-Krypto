# Binance Bot

Engine untuk menjalankan **SOP "Short Top Gainers (Futures 1x)"** milik Pak Saputra di Binance
Desktop (macOS). Bot membuka Top Gainers Futures, menilai tanda "pucuk" di chart 15 menit
dengan AI visual (default Claude Haiku 5.5), mengecek funding dan spread, menghitung ukuran
posisi sesuai rumus SOP, mengisi kolom **Jumlah**, lalu mencatat posisi **uji kertas** di jurnal.

**Beli/short sengaja dimatikan pada tahap ini.** Tombol order tidak pernah ditekan; setiap
"masuk" dinilai dari candle sungguhan untuk fase uji 50 trade di SOP.

## Dokumen

| Dokumen | Isi |
|---|---|
| [docs/SOP.md](docs/SOP.md) | Pemetaan PDF ke engine: langkah, parameter, 4 tanda pucuk, titik impas, pengaman, hal yang perlu disepakati |
| [docs/MODE_SINGLE.md](docs/MODE_SINGLE.md) | Satu laptop menjalankan SOP penuh |
| [docs/MODE_BANYAK.md](docs/MODE_BANYAK.md) | Beberapa laptop di satu WiFi; AI dipanggil sekali per koin oleh leader |

## Setup (sekali per laptop)

Butuh macOS, Python 3.11+, dan Binance Desktop (bahasa Indonesia, akun Futures aktif).

```bash
make install       # buat .venv dan pasang bot
make env           # buat .env dari .env.example, lalu isi nilainya
```

Lalu:

1. **System Settings > Privacy & Security**: aktifkan **VS Code** (atau Terminal) di
   **Accessibility** dan **Screen & System Audio Recording**, lalu restart aplikasinya.
2. `make open` untuk membuka Binance (tidak mengganggu sesi login yang sudah ada), lalu login.
3. Buka menu Futures sekali dan pilih tata letak **Pro**.
4. `make window-size` harus menampilkan **OK**.
5. `make uji-isi RANK=1 JUMLAH=1`: bot membuka top gainer #1 dan mengisi kolom Jumlah dengan 1.
   Pastikan log berakhir `BERHASIL`, lalu kosongkan kolom itu.

Isi `.env` (lihat `.env.example`):

| Variable | Dibutuhkan oleh |
|---|---|
| `VIKEY_API_BASE`, `VIKEY_API_KEY` | single, leader |
| `BOT_HUB_TOKEN` | leader, follower (sama di semua laptop; buat dengan `make token`) |
| `BOT_HUB_URL` | follower (opsional, pengganti `HUB=`) |

## Perintah (Makefile)

Ketik `make` untuk daftar lengkap.

| Perintah | Yang dilakukan |
|---|---|
| `make single MODAL=100` | SOP penuh di satu laptop (rank 1,2,3), modal 100 USDT |
| `make single JUMLAH=150 RANKS=2` | Jumlah koin manual, hanya top gainer #2 |
| `make leader RANKS=1,2,3 INTERVAL=15` | Mode banyak, leader: AI tanda pucuk sekali per koin, lewat hub |
| `make follower HUB=http://IP:8765 RANK=2 MODAL=100` | Mode banyak, follower: SOP penuh pakai hasil AI leader |
| `make jurnal` | Nilai uji kertas dan rekap terhadap titik impas SOP |
| `make uji-isi RANK=1 JUMLAH=1` | Uji kalibrasi kolom Jumlah |
| `make open` / `window-size` / `hub-health` / `token` | Pembantu setup |
| `make check` | Lint, cek tipe, dan tes |
| `make bench-cases` / `bench-smoke` / `bench-run` | Benchmark model AI (`make bench-install` dulu) |

Rank top gainer yang bisa dipilih: **1 sampai 5**, satu atau beberapa (`RANKS=4`,
`RANKS=1,2,3,4,5`) di single/leader, dan satu (`RANK=5`) di follower. Default: `RANKS=1,2,3`.

Parameter SOP yang bisa diubah: `MODAL`, `JUMLAH`, `RISIKO`, `SL`, `TARGET`, `MIN_NAIK`,
`MIN_TANDA`, `BATAS_JAM`, `MAKS_POSISI`, `SINYAL` (`ai`/`data`), `NO_FILL=1`. Default dan asalnya
ada di [docs/SOP.md](docs/SOP.md#parameter).

## Struktur

```
src/binance_bot/
├── cli.py                 # perintah: open, single, leader, follower, jurnal, uji-isi
├── config.py              # Settings dari env BOT_* dan .env
├── exceptions.py          # hierarki error (semua turunan BotError)
├── macos/                 # sistem: aplikasi, jendela, klik/gulir, ketik angka, screenshot, OCR
├── binance_desktop/       # tampilan Binance
│   ├── layout.py          #   posisi klik/potongan + zona tombol order terlarang
│   ├── screen_text.py     #   teks OCR -> data (daftar gainers, pair, margin)
│   └── navigator.py       #   Pasar -> Futures -> Top Gainers -> halaman trade -> isi Jumlah
├── market/                # data pasar publik Binance Futures (tanpa API key)
├── analysis/              # AI visual: 4 tanda pucuk dari chart 15 menit
├── strategy/              # SOP: parameter, tanda versi data, ukuran posisi, jurnal, evaluasi,
│                          #   pintu order (dry run)
├── hub/                   # berbagi hasil AI lewat LAN: store, server (leader), client (follower)
└── workflows/             # sop.py (inti SOP) + single, leader, follower, jurnal, uji-isi
docs/                      # SOP dan panduan mode
benchmarks/chart_vision.py # benchmark akurasi dan kecepatan model visual
tests/                     # pytest, semua memakai tiruan (tests/fakes.py)
```

Hanya `macos/` yang menyentuh sistem, jadi lapisan lain bisa diuji tanpa layar. Algoritma SOP
hanya ada di satu tempat (`workflows/sop.py` + `strategy/`); mode hanya mengatur siapa yang
memanggil AI.

## Kalibrasi

Posisi klik ada di `src/binance_bot/binance_desktop/layout.py`, diukur dari Binance Desktop
2.6.0 bahasa Indonesia, jendela 1470x859 pt, Futures tata letak Pro. Jika ukuran jendela
berbeda lebih dari 2%, bot berhenti tanpa mengklik. Jika tata letak, bahasa, atau ukuran layar
berbeda, ukur ulang file itu lalu uji dengan `make uji-isi` dan `make single ... NO_FILL=1`.

## Pengembangan

```bash
make check     # ruff + mypy (strict) + pytest
make format    # rapikan format kode
```
