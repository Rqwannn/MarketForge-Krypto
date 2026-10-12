# SOP V2 di dalam engine

Engine ini menjalankan **SOP V2 "Short Top Gainers (Futures 2x)"** dari PDF Pak Saputra
(12 Oktober 2026). Ketiga mode (single, leader, follower) memakai algoritma yang sama; bedanya
hanya siapa yang memanggil AI. Kode intinya ada di `engine/src/binance_bot/workflows/sop.py` dan
`engine/src/binance_bot/strategy/`.

> **Tahap sekarang: uji kertas.** Tombol Jual/Short tidak pernah ditekan. Setiap keputusan
> "masuk" dicatat di jurnal lalu dinilai dari candle sungguhan, sesuai fase uji 50 trade di PDF.
> Sifat dokumen sumber: materi edukasi, bukan saran investasi.

## Langkah PDF dan pelaksananya

| Langkah PDF | Di engine | Sumber data |
|---|---|---|
| 1. Pantau top 5 Futures | Pasar → Futures → urutkan "Perubahan 24jam" (diverifikasi OCR) → buka rank 1..5 → baca pair di halaman trade | Layar Binance + OCR macOS |
| 2. Baca garis kuning (MA7) | Tab "Grafik" dan tombol "15 mnt" dicari dengan OCR, tunggu grafik termuat, screenshot, **Haiku menghitung berapa kali MA7 di bawah MA25** | AI visual (default) atau data candle (`SINYAL=data`) |
| 3. Cek biaya | Lewati bila funding terlalu negatif atau spread lebar | API publik Binance |
| 4. Cek slot | Maksimal 2 posisi; koin kedua hanya bila posisi pertama tidak sedang rugi | Jurnal + harga terkini |
| 5. Masuk short 2x, margin 50% | Ukuran posisi, isi kolom **Jumlah**, pintu order **dry run** | Layar Binance |
| 6. Monitor | `make jurnal`: target / stop-loss / batas waktu dari candle 1 menit; tandai posisi > 1 jam untuk ditinjau | API publik Binance |
| 7. Catat | `engine/journal/sop.jsonl`: semua isi "Yang dicatat tiap trade" di PDF | File lokal |

Saringan yang gratis (biaya, slot) dijalankan **sebelum** AI. Bila slot sudah penuh, engine
tidak memindai dan tidak memanggil AI sama sekali. Bila kelima koin belum OK, engine tidak masuk.

## Keputusan pola garis kuning

| Hitungan MA7 di bawah MA25 | Keputusan | Arti (PDF) |
|---|---|---|
| 0 kali | **JANGAN** | Selalu di atas: harga naik terus, berbahaya di-short |
| 1 kali | **TUNGGU** | Baru sekali di bawah: masih bisa naik besar |
| ≥ `MIN_TURUN` (usulan 2) | **OK** | Berkali-kali di bawah: harga cenderung turun |

Haiku hanya **mengamati**: berapa periode terpisah garis kuning berada di bawah garis magenta
di seluruh grafik yang terlihat, dan apakah di ujung kanan masih di bawah. Keputusannya
diterapkan engine dari hitungan itu, jadi ambang `MIN_TURUN` bisa diubah tanpa mengubah prompt.
Jawaban Haiku divalidasi ketat (bilangan bulat 0-50, ya/tidak, ringkasan); bila gambar bukan
grafik candlestick, Haiku menolak dan koin dilewati.

Versi data menghitung hal yang sama dari candle 15 menit selama 24 jam terakhir (MA7 dan MA25
dari harga penutupan), dan selalu dicatat sebagai pembanding. **Menghitung adalah kelemahan
model visual** (benchmark kita: 74% untuk soal menghitung), jadi `make jurnal` menampilkan
seberapa sering AI dan data sepakat. Angka itu dasar untuk memilih penentu (`SINYAL`).

## Parameter

| Parameter | Makefile | Default | Asal |
|---|---|---|---|
| Arah | (tetap) | Short | Beliau |
| Leverage | `LEVERAGE` | 2x | Beliau |
| Margin per posisi | `MARGIN` | 50% modal (nilai posisi = 100% modal) | Beliau |
| Posisi bersamaan | `MAKS_POSISI` | 2 | Beliau |
| Rank yang dipantau | `RANKS` | 1,2,3,4,5 | Beliau |
| Timeframe | (tetap) | 15 menit | Beliau |
| Target | `TARGET` | 2% (rentang beliau 1-4%) | Beliau / titik impas PDF |
| Ambang pola OK | `MIN_TURUN` | 2 kali | Usulan |
| Stop-loss | `SL` | 2% di atas harga masuk | Riwayat dan usulan |
| Batas waktu | `BATAS_JAM` | tinjau 1 jam, tutup 4 jam | Usulan |
| Biaya | `--biaya` | 0,1% per putaran | Riwayat |
| Kenaikan minimal 24 jam | `MIN_NAIK` | 0 (tidak disaring; V2 tidak mensyaratkan) | Opsional |
| Spread maksimal / funding minimal | `--maks-spread`, `--min-funding` | 0,1% / -0,05% | Usulan engine |
| Berhenti setelah stop-loss beruntun | (tetap) | 3 dalam sehari | SOP |
| Modal | `MODAL` | wajib (USDT) | Pengguna |
| Ukuran order manual | `JUMLAH` | kosong (pakai margin × leverage), dalam USDT | Pengguna |

Kolom **Jumlah** di Binance diisi dalam **USDT, mode Ukuran Order** (nilai posisi), bukan jumlah
koin. Bot membaca satuan kolom sebelum mengetik; bila masih satuan koin atau Margin Awal, bot
berhenti tanpa mengetik.

Contoh PDF: modal 10.000.000 × margin 50% × 2x = nilai posisi 10.000.000; stop-loss 2% = rugi
sekitar 200.000 (2% modal). Dengan `MODAL=100` (USDT): margin 50 USDT, nilai posisi 100 USDT.
Tahap modal kecil di PDF memakai margin 25%: `MARGIN=25`.

## Menilai uji kertas

- Harga masuk = harga **bid** saat itu (short menjual ke bid).
- Mulai menit berikutnya, candle 1 menit diperiksa: menyentuh stop-loss → `stop`; menyentuh
  target → `target`. Bila keduanya di menit yang sama, dihitung `stop` (asumsi terburuk).
  Tidak tersentuh sampai batas waktu → `timeout` di harga penutupan terakhir.
- **Harga tertinggi setelah masuk** dicatat sampai posisi selesai (seberapa jauh harga melawan).
- Hasil bersih = selisih harga − fee 0,1% + funding (short menerima funding positif dan
  membayar funding negatif), dilaporkan juga dalam **% modal**, bukan ROI aplikasi.
- **Titik impas** = (SL + biaya) ÷ ((target − biaya) + (SL + biaya)). Target 2%, SL 2%, biaya
  0,1% → **52,5%** (PDF: sekitar 53%).
- **Gerbang lulus** (setelah 50 trade selesai): total hasil bersih positif **dan** win rate ≥
  titik impas + 5 poin persen (tafsiran "selisih yang jelas").
- Posisi kedua dibandingkan dengan sisi harga yang sama saat masuk (bid), supaya spread sesaat
  setelah masuk tidak dihitung sebagai rugi.

## Pengaman

- Satu-satunya "pintu order" adalah `DryRunOrderGate`, yang hanya mencatat rencana (short,
  jumlah, nilai, margin, leverage, target, stop-loss). Tidak ada kode yang menekan tombol order.
- Navigator menolak klik ke **zona tombol order** (Beli/Long, Jual/Short, widget order di atas
  grafik). Modul keyboard hanya bisa mengetik angka, **tanpa Enter**; angka di kolom dibaca
  ulang dengan OCR.
- Mode margin dan leverage dibaca dari layar. Bila bukan **2x**, atau bukan Isolated (usulan),
  engine memberi peringatan. Wajib disesuaikan sebelum order sungguhan.

## Temuan dari uji nyata

- **Peringkat bergeser dalam hitungan detik**; setiap pair dinilai sekali per putaran.
- **Koin bernama satu huruf** (S, W) kini terbaca.
- **Banner di halaman koin tertentu** (mis. "project name of S is Sonic") menggeser tata letak;
  tombol 15 mnt kini dicari dengan OCR dan area grafik ikut digeser.
- **Grafik bisa lambat dimuat**; engine menunggu sampai grafik tampil (maksimal 25 detik).
- 12 Okt 2026: jaringan yang dipakai memblokir domain Binance lewat Internet Positif, sehingga
  API publik tidak bisa dijangkau. Engine tidak mengakali pemblokiran; koin dilewati dengan
  alasan yang jelas. Bagian yang butuh API (biaya, aturan jumlah, data candle, penilaian jurnal)
  hanya berjalan di jaringan yang tidak memblokir.

## Perlu disepakati dengan beliau

1. Angka pola "OK" (`MIN_TURUN`, usulan 2), stop-loss 2%, dan batas waktu.
2. Garis pembanding: PDF menyebut "garis lain" (MA25 dan MA99); engine memakai MA25 sesuai
   kolom "Yang dicatat tiap trade". Perlu dicek apakah MA99 juga diperhitungkan.
3. Penentu pola: AI, data, atau keduanya harus sepakat.
4. Target tetap (2%) atau dinamis di rentang 1-4%.

Sebelum order sungguhan: kuis Futures Binance selesai, leverage diubah ke 2x (sekarang 20x),
dan PDF sendiri mencatat bahwa Binance global setahu mereka tidak berizin OJK.
