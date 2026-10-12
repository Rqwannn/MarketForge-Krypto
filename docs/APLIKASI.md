# Aplikasi desktop MarketForge

Aplikasi untuk menjalankan SOP V2 tanpa terminal. Pengguna cukup memilih peran laptop, modal,
top gainers yang dipantau, lalu menekan **Mulai memantau**. Semua istilah teknis disembunyikan;
detailnya tetap tersimpan di `engine/logs/bot.log` untuk admin.

> Mode uji kertas: aplikasi tidak pernah menekan tombol beli atau jual di Binance.

## Untuk pengguna

| Halaman | Isi |
|---|---|
| **Pantau** | Pilih peran (Sendiri, Pemimpin, Pengikut), modal, top gainers (Sendiri dan Pemimpin bisa lebih dari satu; Pengikut satu), dan seberapa sering diulang. Kartu **Alur putaran** menyorot langkah yang sedang berjalan (mis. Haiku baca grafik) dan hitung mundur ke putaran berikutnya. Tabel "Putaran ini" menampilkan keputusan Haiku dan **tindakan**-nya (mis. Tunggu = tidak ada tindakan; Layak short = pengikut boleh membuka posisi uji). |
| **Hasil uji** | Progres 50 trade uji, tingkat menang dibanding titik impas, hasil bersih dalam % modal, dan trade terakhir. |
| **Cek laptop** | Daftar kesiapan: izin macOS, Binance terbuka, ukuran jendela, koneksi data Binance, AI, dan kerja sama antar laptop. Tombol **Lihat laptop** menampilkan laptop lain di WiFi yang sama yang sedang membuka MarketForge (nama, OS, peran, status bot). |

Arti keputusan di tabel:

| Keputusan | Arti |
|---|---|
| Layak short | Garis kuning berkali-kali turun di bawah garis tren; bila ada slot, posisi uji dibuka |
| Tunggu | Garis kuning baru sekali turun; harga masih bisa naik lagi |
| Jangan short | Garis kuning selalu di atas; harga masih naik terus |
| Dilewati | Koin tidak dinilai (mis. jaringan memblokir data Binance) |

Selama bot bekerja, mouse dan keyboard laptop itu jangan dipakai.

### Kelompok pemimpin dan pengikut

1. Admin mengisi `BOT_HUB_TOKEN` yang **sama** di `interface/.env` setiap laptop (`make token`).
2. Admin menjalankan `make leader-key` **sekali** di laptop pemimpin:
   - `BOT_LEADER_KEY` (kunci privat) hanya di `interface/.env` laptop pemimpin. Rahasia.
   - `BOT_LEADER_PUBLIC` (kunci publik) di `interface/.env` semua laptop pengikut.
   Tanpa kunci privat, tombol Pemimpin terkunci. Token hub saja tidak cukup: pengikut hanya
   menerima ajakan dan sinyal putaran yang ditandatangani kunci privat itu (Ed25519), jadi
   laptop lain tidak bisa mengaku pemimpin walau membuat kuncinya sendiri.
3. Laptop pemimpin: halaman **Pantau**, pilih peran **Pemimpin**.
4. Halaman **Cek laptop** > **Lihat laptop**: pilih Top untuk laptop lain, tekan **Jadikan pengikut**.
5. Laptop yang diajak menampilkan ajakan; pemiliknya mengisi modal lalu menekan **Terima**.
   Perannya otomatis menjadi Pengikut untuk Top itu, dengan alamat hub dari laptop pemimpin.
6. Setiap pemimpin memulai putaran, bot di laptop pengikut ikut mulai sendiri. Pengikut tidak
   membaca grafik: ia menunggu keputusan Haiku pemimpin untuk Top-nya. Tunggu/Jangan = tidak
   ada tindakan (Binance tidak disentuh). Layak short = pengikut membuka **koin yang sama**
   (dicari dari nama pair, karena peringkat bisa bergeser), cek biaya dan slot, lalu entry.
   Pengikut bisa keluar lewat **Keluar dari kelompok**; pemimpin bisa menekan **Lepas**.

Peran laptop selalu diatur di halaman Pantau (tombol **Ubah peran** di daftar laptop menuju ke
sana). Ajakan dan sinyal mulai ditandatangani dengan token hub; laptop dengan token lain tidak
bisa memalsukannya. Keanggotaan kelompok hilang bila aplikasi ditutup.

## Untuk admin (sekali per laptop)

1. Siapkan engine: `make install` di root repo, lalu ikuti langkah **Setup** di
   [README](../README.md) (izin macOS, Binance login, tata letak Pro, ukuran jendela).
2. Pasang aplikasi: `make app-install`.
3. Isi pengaturan: salin `interface/.env.example` menjadi `interface/.env`, lalu isi:

   | Kunci | Laptop |
   |---|---|
   | `VIKEY_API_BASE`, `VIKEY_API_KEY` | Sendiri dan Pemimpin |
   | `BOT_HUB_TOKEN` | Pemimpin dan Pengikut (sama di semua laptop; buat dengan `make token`) |
   | `BOT_HUB_URL` | Pengikut: alamat laptop Pemimpin, mis. `http://192.168.1.24:8765` |

   Nilai di `interface/.env` diteruskan ke engine dan menimpa `engine/.env`. File ini tidak
   masuk git; jangan dibagikan.
4. Buka aplikasi: `make app`. Untuk saat ini aplikasi dijalankan dari repo; paket `.app` yang
   tinggal diklik dua kali menyusul.
5. Izin macOS (Accessibility dan Screen Recording) diberikan ke aplikasi yang membuka
   MarketForge. Saat dijalankan lewat `make app` dari Terminal/VS Code, izinkan aplikasi itu.

> **Windows:** `make` tidak tersedia. Pasang dan buka aplikasi dengan `npm ci` lalu `npm start` di
> folder `interface`, dan siapkan engine mengikuti [WINDOWS.md](WINDOWS.md). Izin macOS diganti
> syarat Windows di sana (izinkan screenshot di Binance, layar 1920x1080).

## Cara kerja

```
interface/ (Electron)                       engine/ (Python)
renderer  --IPC-->  main.js  --spawn-->  python -m binance_bot --events single|leader|follower
                    engine.js            python -m binance_bot cek          (JSON kesiapan)
                                         python -m binance_bot jurnal --json (rekap)
```

- Argumen dibangun dan divalidasi di `interface/engine.js` (tanpa shell). Parameter SOP
  memakai default V2 di engine; perubahan angka SOP dilakukan admin lewat Makefile/CLI.
- Engine menulis satu JSON per baris (`--events`). Event `coin`, `cycle`, dan `hub`
  dipakai untuk tabel dan status; pesan lain diterjemahkan ke bahasa sehari-hari.
- Engine dijalankan dari `engine/src` (PYTHONPATH), bukan skrip `binance-bot`, supaya tidak
  terpengaruh flag "hidden" macOS pada file `.pth` instalasi editable.
- Saat bot mulai, jendela aplikasi diperkecil agar tidak menutupi Binance (bot membaca layar),
  lalu ditampilkan lagi saat bot selesai.
- Daftar laptop memakai Bonjour/mDNS (pustaka `bonjour-service`): setiap aplikasi MarketForge
  mengumumkan layanan `_marketforge._tcp` berisi nama laptop, OS, peran, dan status bot selama
  aplikasi terbuka. Jaringan tidak dipindai, jadi HP dan perangkat lain tidak pernah muncul.
  macOS bisa meminta izin **Jaringan Lokal** untuk aplikasi ini; Windows bisa meminta izin
  firewall. WiFi tamu yang memblokir multicast membuat laptop lain tidak terlihat.
- Tombol Hentikan mengirim SIGINT (sama dengan Ctrl+C).
- Debugging tetap lewat terminal: `make single MODAL=100`, `make cek`, `make jurnal`.

## Pemecahan masalah (admin)

| Gejala | Solusi |
|---|---|
| "Mesin bot belum terpasang di laptop ini" | `make install` |
| Aplikasi tidak terbuka dari terminal VS Code | `make app` sudah menghapus `ELECTRON_RUN_AS_NODE`; jalankan lewat `make app`, bukan `npx electron` |
| "Pengaturan AI di laptop ini belum lengkap" | Isi `VIKEY_API_BASE` dan `VIKEY_API_KEY` di `interface/.env` |
| "Belum terhubung ke laptop pemimpin" | Samakan `BOT_HUB_TOKEN`, cek `BOT_HUB_URL` dan WiFi |
| Detail kendala lain | `engine/logs/bot.log` |
