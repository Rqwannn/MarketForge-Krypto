# Mode Banyak (Leader & Follower)

Beberapa laptop di **WiFi yang sama** menjalankan [SOP V2](SOP.md) bersama. Hanya laptop
**leader** yang memanggil AI, dan setiap koin cukup dinilai **sekali**. Laptop **follower**
membuka koinnya sendiri sampai halaman trade, mengambil hasil AI dari leader, lalu menjalankan
sisa SOP (biaya, ukuran posisi, isi kolom Jumlah, uji kertas) dengan **modal dan jurnalnya
sendiri**.

> Tombol Jual/Short **tidak pernah** ditekan. Setiap "masuk" adalah uji kertas.

---

## 1. Gambaran

```
                          WiFi yang sama
 ┌────────────────────────────────┐
 │ LEADER                         │   hasil AI pola garis kuning (HTTP + token)
 │ Pasar → Futures → Top Gainers  │ ──────────────┬─────────────────────┬──── ...
 │ top 5 → chart 15 menit         │               ▼                     ▼
 │ → AI hitung MA7<MA25, 1x/koin  │  ┌────────────────────────┐ ┌────────────────────────┐
 │ hub di port 8765               │  │ FOLLOWER A (RANK=1)    │ │ FOLLOWER B (RANK=2)    │
 └────────────────────────────────┘  │ buka koin #1 → biaya → │ │ buka koin #2 → biaya → │
                                     │ ambil AI dari hub →    │ │ ambil AI dari hub →    │
                                     │ ukuran posisi → isi    │ │ ukuran posisi → isi    │
                                     │ Jumlah → uji kertas    │ │ Jumlah → uji kertas    │
                                     └────────────────────────┘ └────────────────────────┘
```

| | Leader | Follower |
|---|---|---|
| Binance Desktop terbuka, login, Futures aktif | Ya | Ya |
| Kunci AI (`VIKEY_API_KEY`) | Ya | **Tidak** |
| `BOT_HUB_TOKEN` | Ya | Ya, **sama** dengan leader |
| Panggilan AI | Satu per koin (dipakai ulang 15 menit = satu lilin) | **Nol** |
| Mengisi kolom Jumlah / jurnal uji kertas | Tidak | Ya, dengan `MODAL`/`JUMLAH` sendiri |
| Harus tetap menyala | Ya, selama follower bekerja | Hanya saat dijalankan |

## 2. Persiapan (sekali)

Setiap laptop mengikuti bagian **Prasyarat** di [Mode Single](MODE_SINGLE.md#1-prasyarat)
(termasuk `make cek` dan `make uji-isi` untuk follower). Lalu buat **satu** token:

```bash
make token        # contoh keluaran: 3f9c1e...(32 karakter)
```

Salin token yang sama ke `.env` **setiap** laptop sebagai `BOT_HUB_TOKEN=...`. Laptop leader
juga butuh `VIKEY_API_BASE` dan `VIKEY_API_KEY`; follower tidak.

## 3. Menjalankan

### Langkah 1: leader

```bash
make leader                          # top 5, nilai sekali, hub tetap aktif
make leader INTERVAL=15              # nilai ulang tiap 15 menit (satu lilin)
```

Leader memanggil AI untuk setiap koin (atau hanya yang naik ≥ `MIN_NAIK` bila diisi). Ia mencetak alamat
hub; **catat alamat ini** untuk follower:

```
INFO | Hub berjalan. Di laptop lain pakai: --hub http://192.168.1.24:8765
INFO | Top gainers Futures: #1 STRKUSDT +54.45%, #2 LUMIAUSDT +50.33%, #3 CFXUSDT +35.58%, ...
INFO | Analisis AI STRKUSDT selesai dalam 9.8 detik
INFO | #1 STRKUSDT garis kuning AI: 2 kali di bawah MA25 -> OK | Garis kuning kembali turun di bawah magenta.
INFO | Siklus selesai: 5 hasil di hub, 5 panggilan AI
INFO | Hub tetap melayani laptop lain. Tekan Ctrl+C untuk berhenti.
```

(Contoh bentuk log; angka waktu dan hasil berbeda setiap kali.)

Saat pertama kali jalan, izinkan Python menerima koneksi masuk bila macOS bertanya. Selama
leader berjalan, jangan memakai Binance di laptop leader.

### Langkah 2: cek koneksi dari follower

```bash
make hub-health HUB=http://192.168.1.24:8765
# {"status": "ok"}  <- hub bisa dihubungi
```

### Langkah 3: follower

```bash
make follower HUB=http://192.168.1.24:8765 RANK=2 MODAL=100
```

Isi `BOT_HUB_URL=http://192.168.1.24:8765` di `.env` agar cukup `make follower RANK=2 MODAL=100`.
Semua parameter SOP (`SL`, `TARGET`, `JUMLAH`, `MAKS_POSISI`, ...) berlaku sama seperti di
mode single. Follower menjalankan saringan gratis lebih dulu; bila koinnya gugur, ia tidak perlu
menunggu hasil AI.

### Langkah 4: berhenti

Tekan **Ctrl+C** di leader. Hasil di hub hilang; follower sesudahnya akan menunggu lalu
mencatat koin sebagai dilewati.

## 4. Contoh skenario: 4 laptop, 3 koin

| Laptop | Perintah |
|---|---|
| Leader | `make leader INTERVAL=15` |
| Follower A | `make follower RANK=1 MODAL=100` |
| Follower B | `make follower RANK=2 MODAL=100` |
| Follower C | `make follower RANK=3 MODAL=100` |

Rank yang bisa dipilih: **1 sampai 5**, baik `RANKS` di leader (mis. `RANKS=1,2,3,4,5` atau
`RANKS=4`) maupun `RANK` di follower. Rank follower harus termasuk `RANKS` leader.

| Cara | Panggilan AI per siklus |
|---|---|
| Keempat laptop memakai mode single, masing-masing 3 koin | sampai 12 |
| Mode banyak | paling banyak 3 |
| Mode banyak, koin sama dengan 15 menit terakhir | 0 |

Setiap follower punya jurnal sendiri; jalankan `make jurnal` di laptop masing-masing.

## 5. Cara hasil dicocokkan

- Berdasarkan **nama pair** (mis. `STRKUSDT`), bukan nomor rank. Peringkat bisa bergeser
  dalam hitungan detik; pada uji nyata, rank #1 dan #2 sempat membuka pair yang sama.
- Bila pair follower belum ada di hub, follower mengecek ulang tiap 5 detik, paling lama
  `BOT_FOLLOWER_WAIT_S` (180 detik), lalu mencatat koin itu sebagai dilewati.
- Umur hasil dihitung dengan jam leader. Bila lebih dari 15 menit, follower memberi peringatan.

## 6. Pengaturan

| Variable | Default | Laptop | Keterangan |
|---|---|---|---|
| `BOT_HUB_TOKEN` | (kosong) | semua | Wajib, sama di semua laptop |
| `BOT_HUB_URL` | (kosong) | follower | Pengganti `HUB=` |
| `BOT_HUB_PORT` | `8765` | leader | Atau `make leader PORT=9000` |
| `BOT_ANALYSIS_TTL_S` | `900` | leader | Lama hasil AI dipakai ulang |
| `BOT_FOLLOWER_WAIT_S` | `180` | follower | Lama menunggu hasil di hub |

## 7. Keamanan

- Hub hanya bisa dibaca dengan `BOT_HUB_TOKEN` yang benar; data dari hub divalidasi ulang oleh
  follower sebelum dipakai.
- Koneksi hub memakai **HTTP biasa, tidak terenkripsi**: pakai hanya di WiFi yang dipercaya,
  jangan WiFi publik, dan jangan buka port hub ke internet. Ganti token (`make token`) bila
  mungkin bocor.

## 8. API hub (untuk integrasi)

```bash
H="Authorization: Bearer $BOT_HUB_TOKEN"
curl http://192.168.1.24:8765/health                               # {"status": "ok"}
curl -H "$H" http://192.168.1.24:8765/analyses                     # semua hasil
curl -H "$H" "http://192.168.1.24:8765/analyses?symbol=STRKUSDT"   # satu pair (404 bila belum ada)
```

```json
{"now": 1791700420.1,
 "record": {"symbol": "STRKUSDT", "rank": 1, "analyzed_at": 1791700390.5,
            "ma7_below_ma25_count": 2, "ma7_below_ma25_now": true,
            "summary": "Garis kuning kembali turun di bawah magenta dan tetap di bawah."}}
```

`now` adalah jam leader; umur hasil = `now - analyzed_at` (detik).

## 9. Pemecahan masalah

| Pesan | Penyebab | Solusi |
|---|---|---|
| `BOT_HUB_TOKEN wajib diisi di .env ...` | Token belum diisi | `make token`, salin ke semua laptop |
| `Hub menolak token: samakan BOT_HUB_TOKEN dengan leader` | Token berbeda | Samakan |
| `SINYAL=ai butuh hub leader: isi --hub atau BOT_HUB_URL` | Alamat hub kosong | `make follower HUB=http://IP:8765 ...` |
| `Hub http://... tidak bisa dihubungi` | Leader mati, beda WiFi, IP berubah, firewall | Cek leader, WiFi, alamat terbaru, izinkan Python di firewall leader |
| `Hub belum punya analisis untuk X setelah 180 detik` | Peringkat bergeser; koin follower tidak termasuk `RANKS` leader | Perluas `RANKS` leader, atau pakai `INTERVAL` |
| `Analisis X sudah N menit` | Leader tidak memperbarui | Jalankan leader dengan `INTERVAL` |
| `Hub tidak bisa memakai port 8765` | Port dipakai | Hentikan leader lama, atau `PORT=9000` |

Pesan lain (Binance, izin macOS, ukuran jendela, kolom Jumlah, saringan SOP) sama seperti
[Mode Single](MODE_SINGLE.md#5-pemecahan-masalah).

## 10. Uji pertama

Leader dan follower versi SOP baru teruji lewat tes otomatis (termasuk hub sungguhan di
localhost); belum dijalankan di Binance sungguhan. Saat pertama memakai dua laptop:

1. Di kedua laptop: `make cek` tanpa masalah ukuran jendela, token sama di `.env`.
2. Leader: `make leader RANKS=1,2` (izinkan Python bila diminta).
3. Follower: `make hub-health HUB=<alamat>` → `{"status": "ok"}`.
4. Follower: `make follower HUB=<alamat> RANK=1 MODAL=100`. Pastikan pair di log sama dengan
   yang terbuka di Binance follower, dan log leader **tidak** menambah panggilan AI.
