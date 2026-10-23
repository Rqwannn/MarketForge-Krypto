# Prompt untuk laptop Windows: fitur momentum dan perbaikan 20–21 Okt 2026

Salin seluruh isi di bawah garis ke Claude Code di laptop Windows.

---

Kamu bekerja di repo MarketForge Kripto (engine Python di `engine/`, aplikasi Electron di
`interface/`) di laptop **Windows** dengan Binance Desktop. Branch `origin/raqwan-dev` (commit
terakhir `aaf70d0`) berisi fitur dan perbaikan yang dibuat dan diuji kertas di **macOS**. Tugasmu:
tarik `origin/raqwan-dev` ke branch kerjamu, pelajari commit-commit di bawah, lalu pastikan semuanya
jalan di Windows (profil layar `windows` 1920 dan `windows-1366`). Laporkan ke Raqwan sebelum
mengubah apa pun yang menyentuh keputusan masuk atau keluar posisi.

## Aturan yang tidak boleh dilanggar

- **Algoritma AI tidak diubah**: `engine/src/binance_bot/analysis/`, `binance_desktop/pattern_rules.py`,
  ambang pola (minimal 2 kali di bawah MA25, aturan garis berdekatan). Rumus SOP juga tetap:
  margin 50% modal, leverage 2x, jual short di −3% dan long di +4%. Cutloss 10% dan batas waktu
  hanya aktif bila dipilih pengguna (lihat Tambahan 23 Okt).
- **Uji kertas dulu**: tanpa `--uang-sungguhan`, dan jangan pernah menekan tombol Short saat uji.
  Pakai jurnal, foto, dan log sementara lewat `BOT_JOURNAL_PATH`, `BOT_SCREENSHOT_DIR`,
  `BOT_LOG_DIR`, supaya jurnal asli tidak tersentuh. Pakai `--no-fill` bila tidak perlu mengisi
  kolom Jumlah.
- Teks yang tampil di aplikasi tanpa istilah internal (SOP, V2, V3).
- `make check` (ruff, mypy strict, pytest, node --test) harus hijau, dengan tes untuk setiap
  perubahan.

## Yang berubah (baca diff-nya)

| Commit | Isi |
|---|---|
| `aaf70d0` | **Momentum.** Koin yang terjual di target dipantau 2 jam: dicek ulang langsung, lalu sekali tiap candle 15 menit baru (1 menit setelah candle tutup), juga di sela jeda putaran. Koin di luar Top 5 dibuka lewat **kotak cari** daftar Pasar → Futures (`BinanceNavigator.search_symbol`). Kotak cari dikosongkan saat daftar dibuka lagi (`_clear_market_search`). Pantauan dilanjutkan dari jurnal saat bot dijalankan ulang (`SopTrader.recent_target_sales`). Kode: `workflows/single.py` (`_remember`, `_due`, `_recheck`, `_recheck_between_rounds`, `_resume_watch`), `binance_desktop/navigator.py`, `macos/keyboard.py` dan `windows/window.py` (`type_symbol`: hanya A–Z dan 0–9, tanpa Enter). Di aplikasi, koin yang dicek lewat pencarian (rank 0) tampil dengan tanda ↻. |
| `a38a460` | **Leverage**: sesudah Konfirmasi, bot menunggu dialog benar-benar tertutup dan label menunjukkan 2x (`_await_leverage`, sampai ±5 detik). Dulu bot membaca terlalu cepat, mengira dialog macet, dan berhenti. |
| `de6244f` | **Uang sungguhan**: kalau leverage tidak terbukti 2x (salah atau tidak terbaca), koin dilewati dan order tidak dikirim (`workflows/sop.py`). Kejadian nyata 21 Okt: JCTUSDT terbuka di Cross 20x. Penyebabnya, OCR Mac membaca "20x" sebagai "20" + huruf ha Kiril, jadi pola tidak cocok. Perbaikannya `latinize()` di `macos/ocr.py`, hanya dipakai `MacTextReader`. |
| `7a1941e` | Aplikasi menahan layar dan laptop tetap menyala selama bot berjalan: `powerSaveBlocker.start('prevent-display-sleep')`, sebelumnya `prevent-app-suspension`. |
| `a05b06f` | **Modal 50%**: modal = setengah saldo USDT tersedia. Engine memakai `--modal setengah` (`SopParams.capital_share`); aplikasi punya tombol 50% di samping Max. |
| `abebaf4` | **Beberapa bot di satu laptop** bergiliran memakai layar lewat `filelock.ScreenTurn`, file `marketforge-screen.lock` di folder sementara. Bot yang dapat giliran setelah bot lain membuka ulang halamannya. Jurnal dikunci (`.write.lock`) dan ditulis di atas isi terbaru (`Journal.replace`/`rewrite`). Batas masuk ulang: 1 + 3 kali per koin per hari, uji kertas dan uang sungguhan dihitung terpisah (`SopParams.max_reentries`). |
| `445923a` | Cek jaringan di aplikasi: `net.fetch` Chromium; peringatan baru muncul setelah gagal 2 kali beruntun. |

## Tugas di Windows, urut prioritas

1. **Ukur kotak cari daftar Pasar → Futures** di Binance Windows, lalu isi `MARKET_SEARCH` dan
   `MARKET_SEARCH_AREA` di `binance_desktop/layout_windows.py` dan `layout_windows_1366.py`.
   - `MARKET_SEARCH` = titik ikon kaca pembesar saat kotak kosong, relatif jendela.
   - `MARKET_SEARCH_AREA` = area OCR tempat placeholder atau teks muncul setelah kotak melebar.
   - Sekarang keduanya `None`, sehingga di Windows koin yang sudah keluar Top 5 **tidak** dicek
     ulang (`search_symbol` melempar ScreenReadError, dicatat sebagai dilewati).
   - Acuan Mac: ikon di (0,892; 0,39), sebaris dengan tab Futures. Setelah diklik, kotak melebar
     ke kiri dan menampilkan "Cari Nama Koin" di x≈0,76.
   - Di Windows tab Futures dicari lewat OCR (`MARKET_TABS_AREA`) dan daftar bisa digulir atau
     tergeser banner. Hitung posisi kotak cari relatif terhadap tab Futures yang ditemukan bila
     ternyata ikut bergeser, jangan pakai angka tetap.
   - Placeholder bisa berbeda per bahasa. Pola saat ini `_SEARCH_PLACEHOLDER = Cari\s+Nama|Search`.
2. **Uji `search_symbol` dan `_clear_market_search` di Windows.** Pelajaran dari uji Mac:
   - Klik ikon hanya melebarkan kotak; fokus belum ada di kolom. Mengetik, select-all, atau hapus
     tanpa fokus mengenai halaman (di Mac halaman pindah ke tab Kripto). Karena itu bot mengklik
     tulisan placeholder dulu, baru mengetik. Pastikan perilaku yang sama di Windows
     (`clear_field` = `win32.select_all_and_delete`).
   - Hasil saringan butuh waktu tampil; dibaca ulang sampai 5 kali.
   - Setelah kotak dikosongkan, daftar Futures tidak dimuat ulang ("Tidak ada Rekaman"), jadi tab
     Futures diklik lagi.
   - Saat koneksi Binance putus-sambung (ikon pojok kanan bawah merah), daftar bisa kosong.
     Putaran itu dilewati dan dicoba lagi; jangan dianggap bug pencarian.
3. **OCR Windows dan huruf Kiril.** Cek apakah `windows/ocr.py` (`WinTextReader`) juga membaca
   huruf Latin sebagai Kiril, terutama "2x"/"20x" di label leverage. Kalau ya, pakai `latinize`
   yang sama; pindahkan ke modul bersama bila perlu.
4. **Leverage di Windows.** Uji kertas pada koin yang leverage-nya bukan 2x: harus terbaca,
   diubah, lalu terbaca ulang 2x (log "Leverage diubah ke 2x"). Dengan uang sungguhan, leverage
   yang tidak terbukti 2x berarti koin dilewati. Jadi kalau pembacaan leverage di Windows sering
   gagal, bot tidak akan pernah masuk: perbaiki pembacaannya, jangan longgarkan pengamannya.
5. **Antrean layar dan kunci jurnal di Windows** (`msvcrt.locking`, token ditulis ke file kunci,
   file `.waiting` untuk bergantian). Jalankan dua bot uji kertas bersamaan dengan Top berbeda dan
   jurnal yang sama. Harapannya:
   - bergantian per koin;
   - log memuat "Menunggu giliran layar" dan "Giliran layar dari bot lain";
   - tidak ada klik yang bertabrakan;
   - tidak ada baris jurnal yang hilang.
6. **Penahan layar.** Pastikan layar Windows tidak mati atau terkunci selama jeda putaran 30 menit
   saat bot berjalan dari aplikasi.

## Tambahan 23 Okt: LONG, cutloss 10%, batas waktu 2,5–3 jam (SOP V4)

Algoritma short **tidak berubah**: prompt dan aturan short di `pattern_rules.py` tetap sama, dan tanpa
opsi baru bot berperilaku persis seperti dulu. Yang baru:

- **Arah per Top** `--top-short 2,3,4 --top-long 1,5` (aplikasi: Pengaturan putaran → tabel Top
  gainers dan arahnya). Top yang dipantau = gabungan keduanya; tiap Top hanya membuka arahnya
  sendiri. Tanpa kedua opsi: short di semua Top (aturan lama). LONG memakai prompt AI terpisah
  (`LONG_PROMPT`, tiga tanda: berbalik dari dasar, datar dengan tiga garis menyatu, garis cepat
  jauh di atas), dibaca hanya untuk Top yang boleh long, dan satu tanda cukup. Grafik yang layak
  short sekaligus menunjukkan tanda long **tidak dimasuki**. Target long minimal 4% (harga naik),
  masuk di ask. Momentum (cek ulang setelah terjual di target) masuk ulang searah posisi yang
  terjual. Tebbit memakai padanan garis MA 5/10/30.
- **Cutloss** `--cutloss 10` dan **batas waktu** `--batas-waktu`: sesudah 2,5 jam jual bila untung
  bersih, di jam ke-3 jual apa pun kondisinya. Keduanya dijalankan bot (cek tiap 60 detik, lalu
  Market), bukan order di bursa, jadi hanya bekerja selama bot atau `posisi --pantau` berjalan.
  Status jurnal: `stop` (cutloss) dan `timeout` (batas waktu).
- Jurnal: field baru `side`, `cutloss_price`, `green_exit_at`, `time_exit_at`, `long_ai`,
  `long_data`, `long_signs`. Baris lama tanpa `side` dibaca sebagai short.
- Pemimpin mengumumkan pembagian Top dan aturan keluar lewat field TXT `st`
  (`<Top short>:<Top long>:<cutloss>:<waktu>`, mis. `234:15:1:1`), dan pengikut memakainya.
- Pengikut tetap mengawasi posisinya sesudah putaran (uang sungguhan; uji kertas Tebbit) sampai
  terjual, sampai putaran pemimpin berikutnya, atau sampai aplikasi membuat `--berkas-berhenti`
  (Sell dari pemimpin). Uji ini juga di Windows: berkas dibuat di folder sementara.

Tugas Windows:

1. **Tombol Beli/Long**: uji kertas dengan `--top-long 1,2,3,4,5` pada koin yang menunjukkan tanda long; log
   harus berisi "Tombol Beli/Long ditemukan di (…); TIDAK ditekan". Cadangan teks memakai
   `_LONG_BUTTON = (Beli|Buy)/Long`.
2. **Toast order Beli**: teks toast sesudah order Long belum pernah terlihat langsung. Pola sekarang
   `Order Beli … Terisi | Buy … Order … Filled` (`_ORDER_FILLED["LONG"]`). Cocokkan dengan foto layar
   asli sebelum LONG dipakai dengan uang sungguhan.

## Resep uji kertas fitur momentum (dipakai di Mac)

1. Buat jurnal sementara berisi satu posisi uji kertas pada koin **di luar Top 5** yang targetnya
   sudah tercapai:
   - `status: "open"`, `real: false`, `created_at` 15 menit lalu;
   - `entry_price` = harga sekarang × 1,06, `target_price` = `entry_price` × 0,97;
   - `notional: 50`, `capital_usdt: 50`, `leverage: 2`.
2. Jalankan:
   `binance-bot single --ranks 1 --interval 30 --modal 50 --no-fill`
   dengan `BOT_JOURNAL_PATH` menunjuk ke jurnal itu.
3. Urutan log yang diharapkan:
   1. "… terjual di target: dicek ulang tiap candle 15 menit selama 2 jam"
   2. "… dicek ulang (lewat pencarian)"
   3. "Ketik nama pair …", lalu AI membaca grafik dan memberi keputusan
   4. Top 1 dinilai normal (kotak cari sudah kosong)
   5. sekitar 1 menit setelah candle 15 menit berikutnya: "Candle 15 menit baru: cek ulang …"
4. Pastikan **hanya satu** bot uji yang berjalan, dan hentikan bot uji sebelum menjalankan yang
   baru. Di Mac, bot uji lama yang belum berhenti ikut mengecek ulang dan berebut halaman daftar.

## Selesai bila

- Pencarian dan pengosongan kotak cari jalan di kedua profil Windows, dibuktikan dengan uji
  kertas dan foto layar.
- Leverage terbaca dan bisa diubah ke 2x di Windows.
- `make check` hijau, dengan tes untuk setiap perubahan.
- Ringkasan hasil dan hal yang belum bisa diuji dikirim ke Raqwan.
