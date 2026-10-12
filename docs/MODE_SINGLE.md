# Mode Single

Satu laptop menjalankan **SOP V2 penuh** (lihat [SOP.md](SOP.md)): memantau 5 Top Gainers
Futures, membaca garis kuning (MA7) di chart 15 menit dengan AI, mengecek biaya dan slot,
menghitung ukuran posisi (margin 50% × 2x), mengisi kolom **Jumlah**, lalu mencatat posisi
**uji kertas**.

Pakai mode ini bila hanya ada satu laptop. Bila beberapa laptop menjalankan SOP bersamaan,
pakai [Mode Banyak](MODE_BANYAK.md) agar AI cukup dipanggil sekali per koin.

> Tombol Jual/Short **tidak pernah** ditekan. Setiap "masuk" adalah uji kertas.

---

## 1. Prasyarat

Lakukan sekali per laptop (langkah lengkap di bagian **Setup** pada [README](../README.md)).

- [ ] `make install` sudah dijalankan, dan `.env` berisi `VIKEY_API_BASE` dan `VIKEY_API_KEY`.
- [ ] VS Code/Terminal punya izin **Accessibility** dan **Screen & System Audio Recording**.
- [ ] Binance Desktop terbuka dan login, bahasa **Indonesia**, akun **Futures aktif**.
- [ ] Halaman Futures memakai tata letak **Pro**.
- [ ] `make window-size` menampilkan **OK** (jendela Binance 1470x859 pt).
- [ ] Jaringan bisa menjangkau API publik Binance (`fapi.binance.com`). Bila diblokir
      (Internet Positif), semua koin akan dilewati dengan alasan "Data pasar Binance tidak bisa
      diambil".
- [ ] Sekali di awal: `make uji-isi RANK=1 JUMLAH=1`. Kolom Jumlah harus terisi `1` dan log
      berakhir dengan `BERHASIL`. Kosongkan kolom itu sesudahnya.

## 2. Menjalankan

| Perintah | Yang dilakukan |
|---|---|
| `make single MODAL=100` | Pantau top 5 sekali; masuk koin yang polanya OK, maksimal 2 posisi |
| `make single MODAL=100 INTERVAL=5` | Pantau ulang tiap 5 menit sampai dihentikan (Ctrl+C) |
| `make single MODAL=100 RANKS=1,2` | Hanya top gainer #1 dan #2 (pilihan 1 sampai 5) |
| `make single MODAL=100 MARGIN=25` | Tahap modal kecil di PDF (satu stop-loss sekitar 1% modal) |
| `make single MODAL=100 TARGET=1` | Target 1% (rentang beliau 1-4%) |
| `make single MODAL=100 MIN_TURUN=3` | Pola OK baru bila MA7 minimal 3 kali di bawah MA25 |
| `make single JUMLAH=150 RANKS=2` | Jumlah koin manual 150 (rumus tidak dipakai) |
| `make single MODAL=100 SINYAL=data` | Pola dari data candle, tanpa AI (gratis, butuh API) |
| `make single MODAL=100 NO_FILL=1` | Semua langkah kecuali mengisi kolom Jumlah |
| `make jurnal` | Nilai posisi uji yang terbuka dan tampilkan rekap |

**Jangan memakai mouse atau keyboard selama bot berjalan.** Bot menggerakkan kursor dan
mengetik sungguhan.

## 3. Apa yang dilakukan bot (satu putaran)

1. Mengevaluasi posisi uji yang terbuka. Bila hari ini sudah 3 stop-loss berturut-turut, berhenti.
2. **Cek slot**: bila sudah 2 posisi terbuka, atau posisi pertama sedang rugi, tidak memindai.
3. Membawa Binance ke depan dan memeriksa ukuran jendela.
4. **Pasar → Futures**, urutkan "Perubahan 24jam" sampai OCR memastikan urutan dari kenaikan
   tertinggi; klik ulang tab Futures bila daftar belum tampil.
5. Untuk setiap rank: buka halaman trade, baca nama pair (setiap pair dinilai sekali).
6. Saringan biaya: pair USDT, funding, spread (dan kenaikan minimal bila `MIN_NAIK` diisi).
7. Klik "Grafik" dan "15 mnt" (dicari dengan OCR), tunggu grafik termuat, screenshot, lalu
   **Haiku menghitung berapa kali MA7 di bawah MA25** → JANGAN / TUNGGU / OK.
8. Bila OK: ukuran posisi (margin × leverage), baca mode margin/leverage (peringatan bila bukan
   2x / Isolated), isi kolom **Jumlah**, lalu **pintu order dry run** mencatat rencana short.
9. Mencatat ke jurnal; berhenti bila 2 slot sudah terisi.

Contoh jawaban Haiku dari uji nyata (12 Okt 2026, tanpa API):

```
#1 WUSDT    MA7 di bawah MA25: 1x | sekarang di bawah: False -> TUNGGU
   "Garis kuning sempat di bawah magenta di awal grafik, lalu naik menembus ke atas sekitar
    pukul 23:00 dan tetap di atas."
#2 CKBUSDT  MA7 di bawah MA25: 2x | sekarang di bawah: True  -> OK
   "Garis kuning sempat di bawah magenta di awal grafik, lalu kembali turun di bawahnya sekitar
    pukul 08:30 dan tetap di bawah."
```

## 4. Hasil

| Lokasi | Isi |
|---|---|
| `journal/sop.jsonl` | Satu baris per koin yang dinilai: status (`skipped`, `open`, `target`, `stop`, `timeout`), alasan, hitungan pola AI dan data, keputusan, funding, spread, modal, margin, leverage, harga masuk/keluar/tertinggi, hasil bersih (% posisi, USDT, % modal) |
| `screenshots/<waktu>_<PAIR>_rank<N>.png` | Halaman trade saat dinilai |
| `screenshots/<waktu>_<PAIR>_rank<N>_15m.png` | Grafik 15 menit yang dibaca Haiku |
| `logs/bot.log` | Log lengkap |

Bentuk rekap `make jurnal` (angka ilustrasi, bukan hasil nyata):

```
Selesai 12 (target 9, stop-loss 2, batas waktu 1) | terbuka 1 | dilewati 40
Win rate 75.0% vs titik impas 52.5% | hasil bersih +12.40% modal (+12.40 USDT)
Harga paling jauh melawan posisi: +1.85% | stop-loss berturut-turut: 0 | AI dan data sepakat soal pola OK: 31 dari 45 koin
Belum cukup data: 12/50 trade uji selesai
```

## 5. Pemecahan masalah

| Pesan | Penyebab | Solusi |
|---|---|---|
| `Parameter SOP tidak valid: isi MODAL (USDT) atau JUMLAH (koin)` | Modal belum diisi | `make single MODAL=100` |
| `Data pasar Binance tidak bisa diambil: ... certificate ... internetpositif` | Jaringan memblokir domain Binance | Pakai jaringan yang tidak memblokir; engine tidak mengakali pemblokiran |
| `Tidak masuk putaran ini: sudah 2 posisi terbuka` | Slot penuh (SOP) | Normal; tunggu posisi selesai (`make jurnal`) |
| `posisi X sedang rugi; koin berikutnya belum boleh dibuka` | Aturan koin kedua (SOP) | Normal |
| `pola garis kuning JANGAN/TUNGGU` | Pola belum OK | Normal; SOP: tidak masuk, pantau ulang |
| `Tombol '15 mnt' tidak ditemukan` / `Grafik 15 menit belum termuat` | Halaman belum termuat atau tab lain terbuka | Naikkan `BOT_SETTLE_DELAY_S=3`; cek koneksi aplikasi |
| `Daftar Futures tidak terurut ...` | Halaman Pasar lambat | Naikkan `BOT_SETTLE_DELAY_S=3` |
| `Kolom Jumlah menampilkan [...], bukan ...` | Klik tidak kena kolom / desimal berbeda | `make uji-isi`; bila desimal salah, `BOT_DECIMAL_SEPARATOR=.` |
| `Margin di aplikasi: leverage 20x, SOP 2x` | Leverage aplikasi belum diubah | Ubah ke 2x sebelum order sungguhan |
| `Klik ke zona tombol order ditolak` | Pengaman bekerja | Jangan diabaikan; posisi di `layout.py` perlu dicek |
| `... stop-loss berturut-turut hari ini` | Aturan SOP | Berhenti hari itu dan tinjau jurnal |
| `Ukuran jendela ... berbeda dari 1470x859` | Jendela diubah ukurannya | Sesuaikan sampai `make window-size` OK |
| `No module named 'binance_bot'` | Flag hidden macOS | `make fix-hidden` (perintah `make` lain sudah menjalankannya otomatis) |
