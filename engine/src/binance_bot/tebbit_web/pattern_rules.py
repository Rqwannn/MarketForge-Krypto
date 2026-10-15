"""Aturan pola untuk Tebbit: baseline bawaan grafik Tebbit MA 5 / 10 / 30.

Pemahamannya sama dengan Binance (MA 7/25/99): garis cepat (MA 5) dibandingkan dengan garis
pembanding (MA 10), garis lambat (MA 30) hanya terlihat. Terpisah dari Binance
(binance_desktop/pattern_rules.py): ubah di sini hanya memengaruhi Tebbit. Bot tidak mengubah
indikator di grafik Tebbit.
"""

from __future__ import annotations

from binance_bot.strategy.pattern import RECENT_CANDLES, MaPattern
from binance_bot.strategy.profile import PatternProfile

PROMPT = """Ini screenshot grafik candlestick 15 MENIT dari Tebbit Futures (latar terang).
Di kiri atas ada legenda "MA 5", "MA 10", "MA 30"; tiap label berwarna sama dengan garisnya.
Cocokkan garis di grafik dengan warna di legenda.
- GARIS CEPAT = garis berlabel MA 5.
- GARIS PEMBANDING = garis berlabel MA 10.
- Garis MA 30 hanya pelengkap: abaikan.
Abaikan juga lilin, panel volume di bawah, dan tombol atau tulisan yang melayang.

Tugas: nilai KENAIKAN TERAKHIR saja, yaitu dari titik terendah tepat sebelum harga naik
besar sampai ujung kanan grafik (bagian yang biasa dilingkari trader). Naik-turun garis SEBELUM
kenaikan itu dimulai TIDAK dihitung, karena belum termasuk kenaikan yang mau di-short.
Di bagian kenaikan itu, ikuti garis cepat terhadap garis pembanding dari kiri ke kanan.
Hitung berapa kali garis cepat berada DI BAWAH garis pembanding sebagai periode terpisah:
- setiap kali garis cepat turun menembus ke bawah garis pembanding dihitung 1;
- bila garis cepat selalu di atas garis pembanding selama kenaikan, jawabannya 0.
Penurunan SINGKAT tetap dihitung: walau hanya beberapa lilin dan garis cepat hanya sedikit
menembus ke bawah garis pembanding (garis berpotongan lalu kembali ke atas), itu 1 kali.
Perhatikan khususnya bagian kanan grafik setelah harga naik: saat harga mendatar di puncak,
garis cepat sering berpotongan dengan garis pembanding berkali-kali.
Telusuri satu per satu dengan teliti sebelum menjawab.

Jawab HANYA dengan JSON valid, tanpa teks lain (nama kolom tetap "ma7_below_ma25", artinya
garis cepat MA 5 di bawah garis pembanding MA 10):
{
 "ma7_below_ma25_count": <bilangan bulat>,
 "ma7_below_ma25_now": true jika di ujung kanan garis cepat berada di bawah garis pembanding,
 "ma7_below_ma25_recent": true jika dalam 6 JAM TERAKHIR, yaitu sekitar 24 LILIN TERAKHIR di ujung
   kanan grafik (1 lilin = 15 menit), garis cepat pernah berada di bawah garis pembanding; false
   bila di 24 lilin terakhir itu garis cepat terus di atas garis pembanding. Hitung lilinnya,
   jangan menebak dari label sumbu waktu: angka tanpa titik dua di sumbu (mis. "13", "14",
   "10/14") adalah TANGGAL (pergantian hari), bukan jam,
 "summary": satu kalimat pendek, maksimal 20 kata, dalam Bahasa Indonesia
}"""


def verdict(pattern: MaPattern, min_crosses: int) -> str:
    # Pemahaman yang sama dengan Binance untuk saat ini; diubah sendiri bila SOP V3 membedakan.
    if pattern.below_count == 0:
        return "jangan"  # selalu di atas: harga naik terus
    if pattern.below_count < min_crosses:
        return "tunggu"  # baru sekali di bawah: masih bisa naik besar
    if not pattern.below_recent:
        return "tunggu"  # turunnya sebelum lonjakan; sekarang masih naik terus
    return "ok"  # berkali-kali di bawah dan baru saja turun lagi: cenderung turun


TEBBIT = PatternProfile(
    platform="tebbit",
    fast=5,
    mid=10,
    slow=30,
    recent_candles=RECENT_CANDLES,
    prompt=PROMPT,
    verdict=verdict,
)
