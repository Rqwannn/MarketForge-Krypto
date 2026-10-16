# SOP V3 di dalam engine

Engine ini menjalankan **SOP V3 "Short Top Gainers (Futures 2x)"** dari PDF Pak Saputra
(15 Oktober 2026, revisi Sell). Perubahan utama dari V2: jual otomatis di 3-5% profit (engine:
harga turun 3%), **tanpa stop-loss dan tanpa batas waktu**, dan aturan pola dipisah per platform
(Binance: garis MA7 dan MA25 yang berdekatan = jangan masuk; Tebbit: berdekatan boleh). Ketiga mode (single, leader, follower) memakai algoritma yang sama; bedanya
hanya siapa yang memanggil AI. Kode intinya ada di `engine/src/binance_bot/workflows/sop.py` dan
`engine/src/binance_bot/strategy/`.

> **Tahap sekarang: uji kertas.** Tombol Jual/Short tidak pernah ditekan. Setiap keputusan
> "masuk" dicatat di jurnal lalu dinilai dari candle sungguhan, sesuai fase uji 50 trade di PDF.
> Sifat dokumen sumber: materi edukasi, bukan saran investasi.

## Langkah PDF dan pelaksananya

| Langkah PDF | Di engine | Sumber data |
|---|---|---|
| 1. Pantau top 5 Futures | Pasar → Futures → urutkan "Perubahan 24jam" (diverifikasi OCR) → buka rank 1..5 → baca pair di halaman trade | Layar Binance + OCR macOS |
| 2. Baca garis kuning (MA7) | Tab "Grafik" dan tombol "15 mnt" dicari dengan OCR, tunggu grafik termuat, screenshot, **Haiku menghitung berapa kali MA7 di bawah MA25 dan menilai apakah kedua garis berdekatan** (Binance); jarak garis (%) dihitung dari candle | AI visual (default) atau data candle (`SINYAL=data`) |
| 3. Cek biaya | Lewati bila funding terlalu negatif atau spread lebar | API publik Binance |
| 4. Cek slot | Jumlah posisi tidak dibatasi (keputusan 15 Okt); koin berikutnya hanya bila posisi terbuka tidak sedang rugi | Jurnal + harga terkini |
| 5. Masuk short 2x, margin 50% | Ukuran posisi, isi kolom **Jumlah**, pintu order **dry run** | Layar Binance |
| 6. Monitor dan jual otomatis | Posisi ditutup (uji kertas) begitu harga turun 3% dari harga masuk; tanpa stop-loss, tanpa batas waktu, batas rugi terakhir = likuidasi (+50% pada 2x). Binance: candle 1 menit, dicek tiap menit selama bot menunggu putaran. Tebbit: harga dibaca dari layar (OCR, tanpa AI) tiap 5 menit. Tombol tutup posisi di bursa **tidak ditekan**. Posisi > 1 hari ditandai untuk ditinjau | API publik Binance / layar Tebbit |
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
| Posisi bersamaan | (tetap) | tidak dibatasi (V3 menulis 2; keputusan 15 Okt) | Pengguna |
| Rank yang dipantau | `RANKS` | 1,2,3,4,5 | Beliau |
| Timeframe | (tetap) | 15 menit | Beliau |
| Target jual otomatis | `TARGET` | harga turun 3% (V3: 3-5%; dasar harga, mulai 3%) | Beliau / usulan V3 |
| Ambang pola OK | `MIN_TURUN` | 2 kali | Usulan |
| Stop-loss | (tidak ada) | tidak dipakai, batas rugi terakhir likuidasi | Beliau (V3) |
| Batas waktu | (tidak ada) | tidak dipakai; posisi > 1 hari ditandai untuk ditinjau | Beliau (V3) |
| Biaya | `--biaya` | 0,1% per putaran | Riwayat |
| Kenaikan minimal 24 jam | `MIN_NAIK` | 0 (tidak disaring; V2 tidak mensyaratkan) | Opsional |
| Spread maksimal / funding minimal | `--maks-spread`, `--min-funding` | 0,3% / -0,1% | Usulan engine, sengaja longgar: SOP V2 hanya menyebut "spread lebar" dan "funding sangat negatif" tanpa angka (menunggu Pak Saputra) |
| Modal | `MODAL` | wajib (USDT) | Pengguna |
| Ukuran order manual | `JUMLAH` | kosong (pakai margin × leverage), dalam USDT | Pengguna |

Kolom **Jumlah** di Binance diisi dalam **USDT, mode Ukuran Order** (nilai posisi), bukan jumlah
koin. Bot membaca satuan kolom sebelum mengetik; bila masih satuan koin atau Margin Awal, bot
berhenti tanpa mengetik.

Contoh PDF: modal 10.000.000 × margin 50% × 2x = nilai posisi 10.000.000; untung bila target 3%
tercapai sekitar 300.000 sebelum fee; rugi tidak dibatasi stop-loss (harga naik 10% = rugi 10%
modal, likuidasi Isolated sekitar +50% = 50% modal). Dengan `MODAL=100` (USDT): margin 50 USDT, nilai posisi 100 USDT.
Tahap modal kecil di PDF memakai margin 25%: `MARGIN=25`.

## Menilai uji kertas

- Harga masuk = harga **bid** saat itu (short menjual ke bid).
- Mulai menit berikutnya, candle 1 menit diperiksa: menyentuh target (harga turun 3%) →
  `target`, dijual seluruhnya di harga target. Tanpa stop-loss dan tanpa batas waktu; posisi baru
  berakhir rugi bila harga mencapai likuidasi (+50% pada 2x) → `likuidasi`. Bila keduanya di menit
  yang sama, dihitung `likuidasi` (asumsi terburuk). Posisi yang ditahan berhari-hari dinilai
  per 1000 menit dari titik terakhir, jadi tidak ada menit yang terlewat.
- Tebbit tidak punya candle: harga ask dibaca dari layar tiap 5 menit (OCR, tanpa AI); begitu
  ask di target atau lebih rendah, posisi dijual di ask itu.
- **Harga tertinggi dan terendah setelah masuk** dicatat sampai posisi selesai.
- Hasil bersih = selisih harga − fee 0,1% + funding (short menerima funding positif dan
  membayar funding negatif), dilaporkan juga dalam **% modal**, bukan ROI aplikasi.
- **Titik impas** = (rugi + biaya) ÷ ((target − biaya) + (rugi + biaya)), dengan rugi = rata-rata
  kenaikan harga yang ditanggung posisi rugi. Sebelum ada rugi, dipakai contoh V3 (STRK +21,8%):
  target 3% → **88%** (grafik Titik impas V3).
- **Gerbang lulus** (setelah 50 trade selesai): total hasil bersih positif **dan** win rate ≥
  titik impas + 5 poin persen (tafsiran "selisih yang jelas").
- Posisi kedua dibandingkan dengan sisi harga yang sama saat masuk (bid), supaya spread sesaat
  setelah masuk tidak dihitung sebagai rugi.

## Pengaman

- Satu-satunya "pintu order" adalah `DryRunOrderGate`, yang hanya mencatat rencana (short,
  jumlah, nilai, margin, leverage, target jual). Tidak ada kode yang menekan tombol order. Jual
  otomatis juga hanya mencatat: tombol tutup posisi di bursa tidak ditekan.
- Navigator menolak klik ke **zona tombol order** (Beli/Long, Jual/Short, widget order di atas
  grafik). Modul keyboard hanya bisa mengetik angka, **tanpa Enter**; angka di kolom dibaca
  ulang dengan OCR.
- Leverage dibaca dari layar. Bila bukan **2x**, engine memberi peringatan; wajib disesuaikan
  sebelum order sungguhan. Mode margin (Cross/Isolated) memakai bawaan bursa (keputusan 15 Okt).

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

## Dua platform, aturan terpisah

Binance (MA 7/25/99) dan Tebbit (bawaan grafiknya MA 5/10/30) punya aturan pola sendiri:
`engine/src/binance_bot/binance_desktop/pattern_rules.py` dan `tebbit_web/pattern_rules.py`
(instruksi AI, periode MA, aturan keputusan). Pemahamannya sama untuk saat ini: garis cepat
(MA7 / MA5) dibanding garis pembanding (MA25 / MA10). Bot tidak mengubah indikator di grafik.
Teori SOP V3 yang membedakan platform diubah di file masing-masing tanpa mengganggu yang lain.

Cara AI menilai (kedua platform): hanya bagian **kenaikan terakhir** (area yang dilingkari
Pak Saputra) yang dihitung; setiap grafik dibaca AI 5 kali dan diambil nilai tengahnya.

## Angka yang BUKAN dari SOP V2 (tebakan engine, menunggu beliau)

| Angka | Nilai sekarang | Catatan |
|---|---|---|
| Spread maksimal | 0,3% | SOP hanya "spread lebar". Koin ETF (UVXY, SQQQ) spread normalnya 0,1-0,25% |
| Funding minimal | -0,1% | SOP hanya "funding sangat negatif" |
| "Berkali-kali" turun | minimal 2 kali | Usulan di SOP sendiri |
| "Baru-baru ini" turun | 24 lilin (6 jam) | Contoh MAGIC 12 Okt memenuhi; contoh MAGIC 10 Okt (boleh menurut beliau) **tidak** |
| "Koin pertama tidak rugi" | harga bid lebih tinggi dari harga masuk = rugi | Selisih spread saja (0,1%) sudah dihitung rugi, sehingga koin kedua sering batal |

Pertanyaan untuk Pak Saputra:

1. Contoh MAGIC 10 Okt 12:45 (boleh masuk): MA7 masih di atas MA25 dan belum turun lagi. Apa yang
   membuatnya boleh? Harga berhenti di puncak, atau tanda lain?
2. Yang dihitung hanya di bagian kenaikan yang dilingkari (turun sebelum harga mulai naik
   tidak ikut)?
3. "Berkali-kali di bawah": minimal berapa kali, dan harus baru-baru ini (berapa jam)?
4. Garis kuning dibandingkan dengan MA25 saja, atau juga MA99 dan harga?
5. Batas spread dan funding: berapa yang dianggap "lebar" dan "sangat negatif"?
6. "Koin pertama tidak sedang rugi": apakah ada toleransi kecil (mis. 0,2%)?

## Perlu disepakati dengan beliau

1. Angka pola "OK" (`MIN_TURUN`, usulan 2), stop-loss 2%, dan batas waktu.
2. Garis pembanding: PDF menyebut "garis lain" (MA25 dan MA99); engine memakai MA25 sesuai
   kolom "Yang dicatat tiap trade". Perlu dicek apakah MA99 juga diperhitungkan.
3. Penentu pola: AI, data, atau keduanya harus sepakat.
4. Target tetap (2%) atau dinamis di rentang 1-4%.

Sebelum order sungguhan: kuis Futures Binance selesai, leverage diubah ke 2x (sekarang 20x),
dan PDF sendiri mencatat bahwa Binance global setahu mereka tidak berizin OJK.
