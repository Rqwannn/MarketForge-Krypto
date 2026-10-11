# Mode Single

Satu laptop menjalankan **SOP penuh** (lihat [SOP.md](SOP.md)): membuka Top Gainers Futures,
menilai tanda pucuk di chart 15 menit dengan AI, mengecek biaya, menghitung ukuran posisi,
mengisi kolom **Jumlah**, lalu mencatat posisi **uji kertas**.

Pakai mode ini bila hanya ada satu laptop. Bila beberapa laptop menjalankan SOP bersamaan,
pakai [Mode Banyak](MODE_BANYAK.md) agar AI cukup dipanggil sekali per koin.

> Tombol Jual/Short **tidak pernah** ditekan. Setiap "masuk" adalah uji kertas.

---

## 1. Prasyarat

Lakukan sekali per laptop (langkah lengkap di bagian **Setup** pada [README](../README.md)).

- [ ] `make install` sudah dijalankan, dan `.env` berisi `VIKEY_API_BASE` dan `VIKEY_API_KEY`.
- [ ] VS Code/Terminal punya izin **Accessibility** dan **Screen & System Audio Recording**.
- [ ] Binance Desktop terbuka dan login, bahasa **Indonesia**, akun **Futures aktif**.
- [ ] Halaman Futures memakai tata letak **Pro** (dipilih sekali saat pertama membuka Futures).
- [ ] `make window-size` menampilkan **OK** (jendela Binance 1470x859 pt).
- [ ] Sekali di awal: `make uji-isi RANK=1 JUMLAH=1`. Kolom Jumlah di Binance harus terisi
      `1` dan log berakhir dengan `BERHASIL`. Kosongkan kolom itu sesudahnya.

## 2. Menjalankan

| Perintah | Yang dilakukan |
|---|---|
| `make single MODAL=100` | SOP pada rank 1, 2, 3; ukuran posisi dari modal 100 USDT |
| `make single MODAL=100 RANKS=1` | Hanya top gainer #1 |
| `make single JUMLAH=150 RANKS=2` | Jumlah koin manual 150 (rumus tidak dipakai) |
| `make single MODAL=100 SL=4 TARGET=3` | Mengubah angka usulan SOP |
| `make single MODAL=100 MAKS_POSISI=3` | Boleh masuk sampai 3 posisi uji per jalan |
| `make single MODAL=100 SINYAL=data` | Tanda pucuk dari data candle, tanpa AI (gratis) |
| `make single MODAL=100 NO_FILL=1` | Semua langkah kecuali mengisi kolom Jumlah |
| `make single-fast MODAL=100` | AI tanpa *thinking*: lebih cepat, kurang teliti |
| `make jurnal` | Nilai posisi uji yang terbuka dan tampilkan rekap |

Semua parameter dan default-nya ada di [SOP.md](SOP.md#parameter).

**Jangan memakai mouse atau keyboard selama bot berjalan.** Bot menggerakkan kursor dan
mengetik sungguhan.

## 3. Apa yang dilakukan bot

1. Mengevaluasi posisi uji yang masih terbuka. Bila hari ini sudah 3 stop-loss berturut-turut,
   bot berhenti sesuai SOP.
2. Membawa Binance ke depan dan memeriksa ukuran jendela; bila tidak sesuai, berhenti tanpa klik.
3. **Pasar → Futures**, lalu mengklik judul kolom "Perubahan 24jam" sampai OCR memastikan urutan
   dari kenaikan tertinggi.
4. Untuk setiap rank di `RANKS`: membuka halaman trade lewat ikon di kolom Tindakan, lalu
   membaca nama pair di halaman itu (peringkat bisa bergeser dalam hitungan detik).
5. Saringan gratis: pair USDT, naik ≥ `MIN_NAIK`, funding, spread. Gagal → dilewati tanpa AI.
6. Klik **15 mnt**, screenshot grafik, AI menilai 4 tanda pucuk. Kurang dari `MIN_TANDA` →
   dilewati. Versi data ikut dicatat sebagai pembanding.
7. Menghitung ukuran posisi, membaca mode margin/leverage (peringatan bila bukan Isolated 1x),
   mengisi kolom **Jumlah** pada tab Pasar, lalu memeriksa angkanya dengan OCR.
8. **Pintu order dry run**: mencatat rencana short (jumlah, target, stop-loss) tanpa menekan tombol.
9. Mencatat ke jurnal. Berhenti bila `MAKS_POSISI` tercapai.

Contoh log, diringkas dari uji nyata 11 Okt 2026 (modal 100 USDT, tanpa mengisi kolom):

```
INFO    | Top gainers Futures: #1 STRKUSDT +54.45%, #2 LUMIAUSDT +50.33%, #3 CFXUSDT +35.58%, ...
INFO    | Top gainer #1: STRKUSDT
INFO    | #1 STRKUSDT tanda pucuk AI: 2/4 (data: 1/4) | Pucuk sudah lewat di 0,12390; harga sideways, volume menurun.
WARNING | Margin Cross 20x: SOP mewajibkan Isolated 1x. Wajib diubah sebelum order sungguhan.
WARNING | [DRY RUN] Tombol Jual/Short TIDAK ditekan. Rencana: SHORT 182,9 STRKUSDT (~20.00 USDT) | masuk ~0.10934 | target 0.104966 | stop-loss 0.114807 | ISOLATED 1x
INFO    | #1 STRKUSDT MASUK UJI KERTAS: short 182,9 @ 0.10934 | target 0.104966 | stop-loss 0.114807 | tutup paling lambat 20:37
```

## 4. Hasil

| Lokasi | Isi |
|---|---|
| `journal/sop.jsonl` | Satu baris per koin yang dinilai: status (`skipped`, `open`, `target`, `stop`, `timeout`), alasan dilewati, tanda AI dan data, funding, spread, harga masuk, target, stop-loss, hasil |
| `screenshots/<waktu>_<PAIR>_rank<N>.png` | Halaman trade saat dinilai |
| `screenshots/<waktu>_<PAIR>_rank<N>_15m.png` | Grafik 15 menit yang dinilai AI |
| `logs/bot.log` | Log lengkap |

Jalankan `make jurnal` kapan saja. Bentuk rekapnya (angka ilustrasi, bukan hasil nyata):

```
Selesai 12 (target 8, stop-loss 3, batas waktu 1) | terbuka 1 | dilewati 40
Win rate 66.7% vs titik impas 61.1% | hasil bersih +9.50% (+1.90 USDT)
Stop-loss berturut-turut: 0 | AI dan data sepakat: 31 dari 45 koin
Belum cukup data: 12/50 trade uji selesai
```

## 5. Pemecahan masalah

| Pesan | Penyebab | Solusi |
|---|---|---|
| `Parameter SOP tidak valid: isi MODAL (USDT) atau JUMLAH (koin)` | Modal belum diisi | `make single MODAL=100` |
| `Binance belum berjalan...` | Aplikasi tertutup | `make open`, login, ulangi |
| `Ukuran jendela ... berbeda dari 1470x859` | Jendela diubah ukurannya | Sesuaikan sampai `make window-size` OK |
| `Daftar Futures tidak terurut dari kenaikan tertinggi...` | Halaman belum termuat / tata letak berubah | Naikkan `BOT_SETTLE_DELAY_S=3`; cek tab Futures di halaman Pasar |
| `Pair Futures tidak terbaca di halaman trade` | Halaman trade belum termuat | Naikkan `BOT_SETTLE_DELAY_S=3` |
| `Kolom Jumlah menampilkan [...], bukan ...` | Klik tidak mengenai kolom, atau tanda desimal berbeda | Jalankan `make uji-isi`; bila desimal salah, isi `BOT_DECIMAL_SEPARATOR=.` di `.env` |
| `Klik ke zona tombol order ditolak` | Pengaman bekerja: ada posisi klik yang jatuh di tombol order | Jangan diabaikan; laporkan, posisi di `layout.py` perlu dicek |
| `naik ... < 30% dalam 24 jam` / `funding ...` / `spread ...` | Koin gugur di saringan SOP | Normal |
| `tanda pucuk 1/4, butuh 2` | Belum ada tanda kelelahan | Normal; SOP: pantau lalu lewati |
| `... stop-loss berturut-turut hari ini` | Aturan SOP | Berhenti hari itu dan tinjau jurnal |
| `Gateway menolak permintaan (HTTP 402)` | Saldo vikey habis | Isi saldo, atau `SINYAL=data` |
| `No module named 'binance_bot'` | Flag hidden macOS | `make fix-hidden` |
