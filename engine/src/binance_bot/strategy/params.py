"""Parameter SOP V2 "Short Top Gainers (Futures 2x)" (PDF 12 Okt 2026).

Default = angka di PDF. Short, leverage 2x, margin 50% per posisi, maksimal 2 posisi, chart
15 menit, pantau top 5, filter garis kuning (MA7), dan target 1-4% berasal dari beliau. Angka
pola "minimal 2 kali di bawah", stop-loss 2%, dan batas waktu ditandai usulan di PDF.
"""

from __future__ import annotations

from dataclasses import dataclass

from binance_bot.exceptions import ConfigError

SIGNAL_SOURCES = ("ai", "data")
REQUIRED_TEST_TRADES = 50  # fase uji di PDF
PASS_MARGIN = 0.05  # "selisih yang jelas" di atas titik impas: tafsiran 5 poin persen
MAX_HOLD_LIMIT_H = 16  # evaluasi memakai maksimal 1000 candle 1 menit


@dataclass(frozen=True, slots=True)
class SopParams:
    capital_usdt: float | None = None  # modal (USDT)
    quantity: float | None = None  # jumlah koin manual; menimpa rumus margin x leverage
    margin_pct: float = 50.0  # beliau: margin 50% modal per posisi
    leverage: int = 2  # beliau: 2x (nilai posisi per koin = 100% modal)
    target_pct: float = 2.0  # beliau: turun 1-4%; titik impas di PDF memakai 2%
    stop_pct: float = 2.0  # riwayat dan usulan: sekitar 2% di atas harga masuk
    min_crosses: int = 2  # usulan: MA7 minimal 2 kali di bawah MA25 = pola OK
    min_gain_pct: float = 0.0  # V2 tidak mensyaratkan kenaikan minimal; isi untuk menyaring
    max_hold_h: float = 4.0  # usulan: tinjau di 1 jam, tutup di 4 jam
    review_after_h: float = 1.0  # usulan: posisi lebih lama dari ini ditandai untuk ditinjau
    fee_pct: float = 0.1  # riwayat: fee masuk + keluar per putaran
    max_spread_pct: float = 0.1  # usulan engine: lewati bila spread lebih lebar
    min_funding_pct: float = -0.05  # usulan engine: lewati bila funding lebih negatif
    max_open_positions: int = 2  # beliau: maksimal 2 koin pada saat yang sama
    max_stop_streak: int = 3  # SOP: berhenti hari itu setelah 3 stop-loss berturut-turut
    signal_source: str = "ai"  # siapa yang membaca pola garis kuning: "ai" atau "data"

    def validate(self) -> None:
        errors = []
        if self.capital_usdt is None and self.quantity is None:
            errors.append("isi MODAL (USDT) atau JUMLAH (koin)")
        if self.capital_usdt is not None and self.capital_usdt <= 0:
            errors.append("MODAL harus lebih dari 0")
        if self.quantity is not None and self.quantity <= 0:
            errors.append("JUMLAH harus lebih dari 0")
        if not 0 < self.margin_pct <= 100:
            errors.append("MARGIN harus di antara 0 dan 100 persen")
        if not 1 <= self.leverage <= 10:
            errors.append("LEVERAGE harus 1..10")
        if not 0 < self.stop_pct < 100 or not 0 < self.target_pct < 100:
            errors.append("SL dan TARGET harus di antara 0 dan 100 persen")
        if self.min_crosses < 1:
            errors.append("MIN_TURUN minimal 1")
        if not 0 < self.max_hold_h <= MAX_HOLD_LIMIT_H:
            errors.append(f"BATAS_JAM harus di antara 0 dan {MAX_HOLD_LIMIT_H}")
        if self.fee_pct < 0 or self.max_open_positions < 1 or self.max_stop_streak < 1:
            errors.append("BIAYA tidak boleh negatif; MAKS_POSISI dan batas stop minimal 1")
        if self.signal_source not in SIGNAL_SOURCES:
            errors.append(f"SINYAL harus salah satu dari {SIGNAL_SOURCES}")
        if errors:
            raise ConfigError("Parameter SOP tidak valid: " + "; ".join(errors))

    @property
    def breakeven_win_rate(self) -> float:
        """Win rate minimal agar impas: rugi bersih / (untung bersih + rugi bersih)."""
        win = self.target_pct - self.fee_pct
        loss = self.stop_pct + self.fee_pct
        return loss / (win + loss)
