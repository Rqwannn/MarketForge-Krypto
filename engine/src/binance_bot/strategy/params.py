"""Parameter SOP V3 "Short Top Gainers (Futures 2x)" (PDF 15 Okt 2026, revisi Sell).

Short, leverage 2x, margin 50% per posisi, chart 15 menit, pantau top 5, filter pola garis per
platform, dan jual di 3-5% profit TANPA stop-loss dan tanpa batas waktu (atas permintaan beliau).
Target memakai dasar harga dan dimulai di 3% (usulan V3). Angka pola "minimal 2 kali di bawah"
masih usulan. Batas jumlah posisi (V3: maksimal 2) tidak dipakai atas keputusan 15 Okt.
"""

from __future__ import annotations

from dataclasses import dataclass

from binance_bot.exceptions import ConfigError

SIGNAL_SOURCES = ("ai", "data")
REQUIRED_TEST_TRADES = 50  # fase uji di PDF
PASS_MARGIN = 0.05  # "selisih yang jelas" di atas titik impas: tafsiran 5 poin persen
# Contoh rugi V3 untuk titik impas sebelum ada rugi sungguhan: STRK, harga naik 21,8%.
REFERENCE_LOSS_PCT = 21.8


@dataclass(frozen=True, slots=True)
class SopParams:
    capital_usdt: float | None = None  # modal (USDT)
    # Modal Max: modal = saldo USDT tersedia di form order, dibaca ulang setiap akan masuk posisi.
    capital_max: bool = False
    order_usdt: float | None = None  # JUMLAH manual: ukuran order USDT (menimpa margin x leverage)
    margin_pct: float = 50.0  # beliau: margin 50% modal per posisi
    leverage: int = 2  # beliau: 2x (nilai posisi per koin = 100% modal)
    target_pct: float = 3.0  # V3: jual saat untung 3-5%; dasar harga, mulai di 3% (usulan)
    min_crosses: int = 2  # usulan: MA7 minimal 2 kali di bawah MA25 = pola OK
    min_gain_pct: float = 0.0  # V2 tidak mensyaratkan kenaikan minimal; isi untuk menyaring
    review_after_h: float = 24.0  # V3: pantau posisi yang ditahan lebih dari satu hari
    fee_pct: float = 0.1  # riwayat: fee masuk + keluar per putaran
    # SOP V2 hanya menyebut "spread lebar", tanpa angka. Longgar dulu sampai Pak Saputra
    # menentukan batasnya: koin ETF (UVXY, SQQQ) spread-nya 0,1-0,25%.
    # Funding rate sengaja TIDAK menyaring koin (keputusan tim 20 Okt 2026): posisi scalping
    # singkat, jadi biaya funding per periode tidak relevan untuk memilih koin.
    max_spread_pct: float = 0.3
    signal_source: str = "ai"  # siapa yang membaca pola garis kuning: "ai" atau "data"

    def validate(self) -> None:
        errors = []
        if self.capital_usdt is None and self.order_usdt is None and not self.capital_max:
            errors.append("isi MODAL (USDT atau max) atau JUMLAH (USDT)")
        if self.capital_usdt is not None and self.capital_usdt <= 0:
            errors.append("MODAL harus lebih dari 0")
        if self.order_usdt is not None and self.order_usdt <= 0:
            errors.append("JUMLAH harus lebih dari 0")
        if not 0 < self.margin_pct <= 100:
            errors.append("MARGIN harus di antara 0 dan 100 persen")
        if not 1 <= self.leverage <= 10:
            errors.append("LEVERAGE harus 1..10")
        if not 0 < self.target_pct < 100:
            errors.append("TARGET harus di antara 0 dan 100 persen")
        if self.min_crosses < 1:
            errors.append("MIN_TURUN minimal 1")
        if self.fee_pct < 0:
            errors.append("BIAYA tidak boleh negatif")
        if self.signal_source not in SIGNAL_SOURCES:
            errors.append(f"SINYAL harus salah satu dari {SIGNAL_SOURCES}")
        if errors:
            raise ConfigError("Pengaturan tidak valid: " + "; ".join(errors))

    def breakeven_win_rate(self, loss_pct: float = REFERENCE_LOSS_PCT) -> float:
        """Win rate minimal agar impas (bagian Titik impas V3).

        Tanpa stop-loss, rugi satu posisi tidak tetap: `loss_pct` = kenaikan harga yang
        ditanggung posisi yang gagal (rata-rata rugi sungguhan, atau contoh STRK 21,8%).
        """
        win = self.target_pct - self.fee_pct
        loss = loss_pct + self.fee_pct
        return loss / (win + loss)
