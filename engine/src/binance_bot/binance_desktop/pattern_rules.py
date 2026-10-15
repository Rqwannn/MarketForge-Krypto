"""Aturan pola garis kuning untuk Binance Desktop: baseline MA 7 / 25 / 99 (SOP V3).

Terpisah dari Tebbit (tebbit_web/pattern_rules.py): ubah di sini hanya memengaruhi Binance.
"""

from __future__ import annotations

from binance_bot.strategy.pattern import RECENT_CANDLES, MaPattern
from binance_bot.strategy.profile import PatternProfile

PROMPT = """Ini screenshot grafik candlestick 15 MENIT dari Binance Futures.
Garis KUNING = MA7. Garis MAGENTA (merah muda) = MA25. Garis UNGU = MA99. Panel bawah = volume.
Abaikan kotak tombol Beli/Long dan Jual/Short yang melayang di atas grafik, dan abaikan lilin.

Tugas: nilai KENAIKAN TERAKHIR saja, yaitu dari titik terendah tepat sebelum harga naik
besar sampai ujung kanan grafik (bagian yang biasa dilingkari trader). Naik-turun garis SEBELUM
kenaikan itu dimulai TIDAK dihitung, karena belum termasuk kenaikan yang mau di-short.
Di bagian kenaikan itu, ikuti garis KUNING terhadap garis MAGENTA dari kiri ke kanan.
Hitung berapa kali garis kuning berada DI BAWAH garis magenta sebagai periode terpisah:
- setiap kali garis kuning turun menembus ke bawah garis magenta dihitung 1;
- bila garis kuning selalu di atas garis magenta selama kenaikan, jawabannya 0.
Penurunan SINGKAT tetap dihitung: walau hanya beberapa lilin dan garis kuning hanya sedikit
menembus ke bawah garis magenta (garis berpotongan lalu kembali ke atas), itu 1 kali.
Perhatikan khususnya bagian kanan grafik setelah harga naik: saat harga mendatar di puncak,
garis kuning sering berpotongan dengan garis magenta berkali-kali.
Telusuri satu per satu dengan teliti sebelum menjawab.

Lalu lihat UJUNG KANAN grafik: apakah garis kuning dan garis magenta BERDEKATAN (menempel, saling
melilit, atau celahnya sangat tipis dibanding tinggi grafik) atau BERJAUHAN (ada celah yang jelas
di antara keduanya, ke atas maupun ke bawah).

Jawab HANYA dengan JSON valid, tanpa teks lain:
{
 "ma7_below_ma25_count": <bilangan bulat>,
 "ma7_below_ma25_now": true jika di ujung kanan garis kuning berada di bawah garis magenta,
 "ma7_below_ma25_recent": true jika dalam 6 JAM TERAKHIR, yaitu sekitar 24 LILIN TERAKHIR di ujung
   kanan grafik (1 lilin = 15 menit), garis kuning pernah berada di bawah garis magenta; false bila
   di 24 lilin terakhir itu garis kuning terus di atas garis magenta. Hitung lilinnya, jangan
   menebak dari label sumbu waktu: angka tanpa titik dua di sumbu (mis. "13", "14", "10/14")
   adalah TANGGAL (pergantian hari), bukan jam,
 "ma7_ma25_close": true jika di ujung kanan garis kuning dan garis magenta BERDEKATAN, false jika
   BERJAUHAN,
 "summary": satu kalimat pendek, maksimal 20 kata, dalam Bahasa Indonesia (sebut juga apakah garis
   berdekatan atau berjauhan)
}"""


def verdict(pattern: MaPattern, min_crosses: int) -> str:
    if pattern.below_count == 0:
        return "jangan"  # selalu di atas: harga naik terus
    if pattern.below_count < min_crosses:
        return "tunggu"  # baru sekali di bawah: masih bisa naik besar
    if not pattern.below_recent:
        return "tunggu"  # turunnya sebelum lonjakan; sekarang masih naik terus
    if pattern.lines_close:
        return "tunggu"  # V3: garis berdekatan, terbukti harga tidak turun; masuk bila berjauhan
    return "ok"  # berkali-kali di bawah dan baru saja turun lagi: cenderung turun


BINANCE = PatternProfile(
    platform="binance",
    fast=7,
    mid=25,
    slow=99,
    recent_candles=RECENT_CANDLES,
    prompt=PROMPT,
    verdict=verdict,
)
