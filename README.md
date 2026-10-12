# Binance Bot

Engine untuk menjalankan **SOP V2 "Short Top Gainers (Futures 2x)"** milik Pak Saputra di
Binance Desktop (macOS). Bot memantau 5 Top Gainers Futures, membaca pola garis kuning (MA7)
terhadap MA25 di chart 15 menit dengan AI visual (default Claude Haiku 5.5), mengecek biaya dan
slot (maksimal 2 posisi), menghitung ukuran posisi (margin 50% × 2x), mengisi kolom **Jumlah**,
lalu mencatat posisi **uji kertas** di jurnal.

**Beli/short sengaja dimatikan pada tahap ini.** Tombol order tidak pernah ditekan; setiap
"masuk" dinilai dari candle sungguhan untuk fase uji 50 trade di SOP.

## Dokumen

| Dokumen | Isi |
|---|---|
| [docs/SOP.md](docs/SOP.md) | Pemetaan PDF V2 ke engine: langkah, pola garis kuning, parameter, titik impas, pengaman, hal yang perlu disepakati |
| [docs/MODE_SINGLE.md](docs/MODE_SINGLE.md) | Satu laptop menjalankan SOP penuh |
| [docs/MODE_BANYAK.md](docs/MODE_BANYAK.md) | Beberapa laptop di satu WiFi; AI dipanggil sekali per koin oleh leader |
| [docs/APLIKASI.md](docs/APLIKASI.md) | Aplikasi desktop (Electron) untuk pengguna non-teknis, dan langkah admin |

## Setup (sekali per laptop)

Butuh macOS, Python 3.11+, dan Binance Desktop (bahasa Indonesia, akun Futures aktif).

```bash
make install       # buat engine/.venv dan pasang bot
make env           # buat engine/.env dari .env.example, lalu isi nilainya
make app-install   # pasang aplikasi desktop (Electron)
```

Lalu:

1. **System Settings > Privacy & Security**: aktifkan **VS Code** (atau Terminal) di
   **Accessibility** dan **Screen & System Audio Recording**, lalu restart aplikasinya.
2. `make open` untuk membuka Binance (tidak mengganggu sesi login yang sudah ada), lalu login.
3. Buka menu Futures sekali dan pilih tata letak **Pro**.
4. `make window-size` harus menampilkan **OK**.
5. `make uji-isi RANK=1 JUMLAH=1`: bot membuka top gainer #1 dan mengisi kolom Jumlah dengan 1.
   Pastikan log berakhir `BERHASIL`, lalu kosongkan kolom itu.

Isi `engine/.env` (lihat `engine/.env.example`). Untuk aplikasi desktop, admin mengisi
`interface/.env` (lihat `interface/.env.example`); nilainya menimpa `engine/.env`:

| Variable | Dibutuhkan oleh |
|---|---|
| `VIKEY_API_BASE`, `VIKEY_API_KEY` | single, leader |
| `BOT_HUB_TOKEN` | leader, follower (sama di semua laptop; buat dengan `make token`) |
| `BOT_HUB_URL` | follower (opsional, pengganti `HUB=`) |

## Perintah (Makefile)

Ketik `make` untuk daftar lengkap. Semua perintah dijalankan dari root repo.

| Perintah | Yang dilakukan |
|---|---|
| `make app` | Buka aplikasi desktop (pengguna non-teknis) |
| `make single MODAL=100` | SOP V2 di satu laptop: pantau top 5, masuk bila pola OK (maks 2 posisi) |
| `make single MODAL=100 INTERVAL=5` | Pantau ulang tiap 5 menit sampai dihentikan |
| `make single JUMLAH=150 RANKS=2` | Jumlah koin manual, hanya top gainer #2 |
| `make leader INTERVAL=15` | Mode banyak, leader: AI pola garis kuning sekali per koin, lewat hub |
| `make follower HUB=http://IP:8765 RANK=2 MODAL=100` | Mode banyak, follower: SOP penuh pakai hasil AI leader |
| `make jurnal` | Nilai uji kertas dan rekap terhadap titik impas SOP |
| `make uji-isi RANK=1 JUMLAH=1` | Uji kalibrasi kolom Jumlah |
| `make cek` | Cek kesiapan laptop (JSON, sama dengan halaman Cek laptop) |
| `make open` / `window-size` / `hub-health` / `token` | Pembantu setup |
| `make check` | Lint, cek tipe, dan tes engine + tes interface |
| `make bench-cases` / `bench-smoke` / `bench-run` | Benchmark model AI (`make bench-install` dulu) |

Rank top gainer yang bisa dipilih: **1 sampai 5**, satu atau beberapa (`RANKS=4`,
`RANKS=1,2,3,4,5`) di single/leader, dan satu (`RANK=5`) di follower. Default: top 5.

Parameter SOP V2 yang bisa diubah: `MODAL`, `JUMLAH`, `MARGIN`, `LEVERAGE`, `SL`, `TARGET`,
`MIN_TURUN`, `MIN_NAIK`, `BATAS_JAM`, `MAKS_POSISI`, `SINYAL` (`ai`/`data`), `NO_FILL=1`. Default dan asalnya
ada di [docs/SOP.md](docs/SOP.md#parameter).

## Struktur

```
engine/                      # Python: otomasi Binance + SOP V2 (CLI `binance-bot`, Makefile debug)
├── src/binance_bot/
│   ├── cli.py               # perintah: open, cek, single, leader, follower, jurnal, uji-isi
│   ├── config.py            # Settings dari env BOT_* dan .env
│   ├── logging_setup.py     # log teks, atau JSON per baris untuk aplikasi (--events)
│   ├── macos/               # sistem: aplikasi, jendela, klik/gulir, ketik angka, screenshot, OCR, izin
│   ├── binance_desktop/     # tampilan Binance: layout, teks OCR, navigator
│   ├── market/              # data pasar publik Binance Futures (tanpa API key)
│   ├── analysis/            # AI visual: pola garis kuning (MA7 vs MA25) dari chart 15 menit
│   ├── strategy/            # SOP V2: parameter, pola MA, ukuran posisi, jurnal, evaluasi, dry run
│   ├── hub/                 # berbagi hasil AI lewat LAN
│   └── workflows/           # sop.py (inti SOP) + single, leader, follower, jurnal, cek, uji-isi
├── tests/  benchmarks/  Makefile  pyproject.toml
interface/                   # Electron: aplikasi desktop untuk pengguna non-teknis
├── main.js  preload.js      # jendela dan IPC (contextIsolation, sandbox)
├── engine.js                # menjalankan engine, validasi isian, baca interface/.env
├── renderer/                # tampilan: Pantau, Hasil uji, Cek laptop
└── test/                    # node:test
docs/                        # SOP, mode, dan aplikasi
Makefile                     # perintah root (meneruskan ke engine/ + target aplikasi)
```

Hanya `engine/src/binance_bot/macos/` yang menyentuh sistem, jadi lapisan lain bisa diuji tanpa
layar. Algoritma SOP hanya ada di satu tempat (`workflows/sop.py` + `strategy/`); mode dan
aplikasi hanya mengatur siapa yang memanggil AI dan bagaimana hasilnya ditampilkan.

## Kalibrasi

Posisi klik ada di `engine/src/binance_bot/binance_desktop/layout.py`, diukur dari Binance Desktop
2.6.0 bahasa Indonesia, jendela 1470x859 pt, Futures tata letak Pro. Jika ukuran jendela
berbeda lebih dari 2%, bot berhenti tanpa mengklik. Jika tata letak, bahasa, atau ukuran layar
berbeda, ukur ulang file itu lalu uji dengan `make uji-isi` dan `make single ... NO_FILL=1`.

## Pengembangan

```bash
make check     # ruff + mypy (strict) + pytest
make format    # rapikan format kode
```
