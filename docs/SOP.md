# SOP di dalam engine

Engine ini menjalankan **SOP "Short Top Gainers (Futures 1x)"** dari PDF Pak Saputra. Ketiga
mode (single, leader, follower) memakai algoritma yang sama; bedanya hanya siapa yang memanggil
AI. Kode intinya ada di `src/binance_bot/workflows/sop.py` dan `src/binance_bot/strategy/`.

> **Tahap sekarang: uji kertas.** Tombol Jual/Short tidak pernah ditekan. Setiap keputusan
> "masuk" dicatat di jurnal lalu dinilai dari candle sungguhan, sesuai fase uji 50 trade di PDF.
> Sifat dokumen sumber: materi edukasi, bukan saran investasi.

## Langkah PDF dan pelaksananya

| Langkah PDF | Di engine | Sumber data |
|---|---|---|
| 1. Scan top gainers Futures, naik ≥ 30% | Pasar → tab Futures → urutkan "Perubahan 24jam" (diverifikasi OCR) → buka rank → baca pair di halaman trade | Layar Binance + OCR macOS; % naik diverifikasi API publik |
| 2. Cek tanda pucuk (chart 15 menit, ≥ 2 dari 4) | Klik "15 mnt", screenshot grafik, AI menilai 4 tanda | AI visual (default) atau data candle (`SINYAL=data`) |
| 3. Cek biaya: funding dan spread | Lewati bila funding terlalu negatif atau spread lebar | API publik Binance |
| 4. Ukuran posisi | modal × %risiko ÷ jarak stop-loss, dibulatkan ke kelipatan jumlah koin | Rumus PDF + aturan koin dari API publik |
| 5. Masuk short 1x isolated + target + stop-loss | Isi kolom **Jumlah** (market order), lalu pintu order **dry run** | Layar Binance |
| 6. Monitor: target / stop-loss / batas waktu | `make jurnal` menilai dari candle 1 menit | API publik Binance |
| 7. Jurnal: hasil, fee, funding | `journal/sop.jsonl`, satu baris per koin yang dinilai | File lokal |

Saringan gratis (langkah 1 dan 3) dijalankan **sebelum** AI, jadi koin yang sudah pasti gugur
tidak memakan biaya AI. API publik Binance tidak butuh API key, akun, atau langganan.

## Parameter

| Parameter | Makefile | Default | Asal |
|---|---|---|---|
| Arah dan leverage | (tetap) | Short, 1x, isolated | Beliau |
| Timeframe | (tetap) | 15 menit | Beliau |
| Target untung | `TARGET` | 4% | Beliau (3-5%) |
| Kenaikan minimal 24 jam | `MIN_NAIK` | 30% | Usulan |
| Tanda pucuk minimal | `MIN_TANDA` | 2 dari 4 | Usulan |
| Stop-loss | `SL` | 5% di atas harga masuk | Usulan |
| Risiko per trade | `RISIKO` | 1% modal | Usulan (1-2%) |
| Batas waktu posisi | `BATAS_JAM` | 4 jam | Usulan (2-4 jam) |
| Biaya total per trade | `--biaya` | 0,5% | Whiteboard (tafsiran) |
| Spread maksimal | `--maks-spread` | 0,1% | Usulan engine |
| Funding minimal | `--min-funding` | -0,05% per periode | Usulan engine |
| Posisi baru per jalan | `MAKS_POSISI` | 1 | Usulan engine |
| Berhenti setelah stop-loss beruntun | (tetap) | 3 dalam sehari | Beliau / SOP |
| Modal | `MODAL` | wajib (USDT) | Pengguna |
| Jumlah manual | `JUMLAH` | kosong (pakai rumus) | Pengguna |

Contoh rumus dari PDF: modal 10.000.000 × 1% ÷ 5% = posisi 2.000.000. Dengan `MODAL=100`
(USDT): 100 × 1% ÷ 5% = posisi 20 USDT. Pada leverage 1x, posisi tidak boleh melebihi modal.

## Empat tanda pucuk

AI menerima screenshot grafik 15 menit dan menjawab ya/tidak untuk tiap tanda. Versi data
(dari candle API) selalu dihitung dan dicatat sebagai pembanding, atau menjadi penentu bila
`SINYAL=data`. Definisi angka versi data adalah usulan, karena PDF hanya menyebut nama tandanya:

| Tanda | Versi data (lilin 15 menit terakhir yang sudah tutup) |
|---|---|
| Sumbu atas panjang | sumbu atas ≥ 50% dari panjang lilin |
| Gagal bikin high baru | puncak 8 lilin terakhir terjadi ≥ 2 lilin sebelum lilin terakhir |
| Volume menurun | volume 3 lilin terakhir turun berturut-turut |
| Lilin merah besar setelah hijau | lilin terakhir merah, badan ≥ 1,5× rata-rata 5 lilin sebelumnya, dan ≥ 3 dari 4 lilin sebelumnya hijau |

## Menilai uji kertas

- Harga masuk = harga **bid** saat itu (short menjual ke bid).
- Mulai menit berikutnya, candle 1 menit diperiksa: harga menyentuh stop-loss → `stop`;
  menyentuh target → `target`. Bila keduanya tersentuh di menit yang sama, dihitung `stop`
  (asumsi terburuk). Tidak tersentuh sampai batas waktu → `timeout` di harga penutupan terakhir.
- Hasil bersih = selisih harga − biaya 0,5% + funding (short menerima funding positif dan
  membayar funding negatif).
- **Titik impas** = (SL + biaya) ÷ ((target − biaya) + (SL + biaya)). Dengan target 4% dan
  SL 5% hasilnya 61,1%, sama dengan grafik di PDF.
- **Gerbang lulus** (setelah 50 trade selesai): total hasil bersih positif **dan** win rate ≥
  titik impas + 5 poin persen. Angka 5 poin adalah tafsiran dari "selisih yang jelas" di PDF.
- Setelah **3 stop-loss berturut-turut** dalam sehari, engine menolak masuk lagi hari itu.

## Pengaman

- Satu-satunya "pintu order" adalah `DryRunOrderGate`, yang hanya mencatat rencana. Tidak ada
  kode yang menekan tombol order.
- Navigator menolak klik ke **zona tombol order** di halaman trade (Beli/Long, Jual/Short,
  dan widget order yang melayang di atas grafik).
- Modul keyboard hanya bisa mengetik angka dan tanda desimal, **tanpa Enter**. Setelah
  mengetik, angka di kolom dibaca ulang dengan OCR; bila berbeda, koin dilewati.
- Mode margin dan leverage dibaca dari layar. Bila bukan **Isolated 1x**, engine memberi
  peringatan (uji kertas tetap jalan). Ini wajib diubah sebelum order sungguhan.
- Nama pair dari layar divalidasi sebelum dipakai untuk memanggil API.

## Temuan dari uji nyata (11 Okt 2026)

- **Peringkat bergeser dalam hitungan detik.** Rank #1 dan #2 sempat sama-sama membuka STRKUSDT.
  Engine kini menilai setiap pair sekali per run.
- **AI tidak selalu konsisten.** Pada grafik STRK yang hampir sama (selang 24 detik), AI
  menilai 1/4 lalu 2/4, sehingga keputusannya berbalik tepat di ambang. Versi data konsisten.
  Jurnal mencatat keduanya; rekap `make jurnal` menampilkan seberapa sering keduanya sepakat.
- **Puncak bisa sudah lama lewat.** Puncak STRK terjadi sekitar 7 jam sebelumnya, tetapi 2
  tanda tetap terpenuhi. PDF tidak mengatur seberapa baru puncak harus terjadi.

## Perlu disepakati dengan beliau

1. Semua angka bertanda **usulan** di tabel parameter.
2. Seberapa baru puncak harus terjadi agar masih dianggap "pucuk" (lihat temuan di atas).
3. Penentu tanda pucuk: AI, data, atau keduanya harus sepakat.
4. Batas "selisih yang jelas" di atas titik impas untuk gerbang lulus (sekarang 5 poin).

Sebelum order sungguhan: akun Futures harus menyelesaikan kuis Binance, margin diubah ke
Isolated 1x, dan PDF sendiri mencatat bahwa Binance global setahu mereka tidak berizin OJK.
