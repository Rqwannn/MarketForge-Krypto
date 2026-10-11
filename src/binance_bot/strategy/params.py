"""Parameter SOP "Short Top Gainers (Futures 1x)".

Default = angka di PDF. Arah short, leverage 1x, chart 15 menit, dan target 3-5% berasal dari
beliau; nilai lain di PDF ditandai "usulan" dan perlu disepakati sebelum dipakai.
"""

from __future__ import annotations

from dataclasses import dataclass

from binance_bot.exceptions import ConfigError

SIGNAL_SOURCES = ("ai", "data")
REQUIRED_TEST_TRADES = 50  # fase uji di PDF
PASS_MARGIN = 0.05  # "selisih yang jelas" di atas titik impas: usulan 5 poin persen
MAX_HOLD_LIMIT_H = 16  # evaluasi memakai maksimal 1000 candle 1 menit


@dataclass(frozen=True, slots=True)
class SopParams:
    capital_usdt: float | None = None  # modal untuk rumus ukuran posisi
    quantity: float | None = None  # jumlah koin manual; menimpa rumus
    risk_pct: float = 1.0  # usulan: 1-2% modal
    stop_pct: float = 5.0  # usulan: 5% di atas harga masuk
    target_pct: float = 4.0  # beliau: 3-5% di bawah harga masuk
    min_gain_pct: float = 30.0  # usulan: naik >= 30% dalam 24 jam
    min_signs: int = 2  # usulan: minimal 2 dari 4 tanda pucuk
    max_hold_h: float = 4.0  # usulan: 2-4 jam, lalu tutup
    fee_pct: float = 0.5  # whiteboard: biaya masuk + keluar + slippage
    max_spread_pct: float = 0.1  # usulan: lewati bila spread lebih lebar
    min_funding_pct: float = -0.05  # usulan: lewati bila funding lebih negatif (short membayar)
    max_positions: int = 1  # posisi uji baru per sekali jalan
    max_stop_streak: int = 3  # SOP: berhenti hari itu setelah 3 stop-loss berturut-turut
    signal_source: str = "ai"  # siapa yang memutuskan tanda pucuk: "ai" atau "data"

    def validate(self) -> None:
        errors = []
        if self.capital_usdt is None and self.quantity is None:
            errors.append("isi MODAL (USDT) atau JUMLAH (koin)")
        if self.capital_usdt is not None and self.capital_usdt <= 0:
            errors.append("MODAL harus lebih dari 0")
        if self.quantity is not None and self.quantity <= 0:
            errors.append("JUMLAH harus lebih dari 0")
        if not 0 < self.risk_pct <= 5:
            errors.append("RISIKO harus di antara 0 dan 5 persen")
        if not 0 < self.stop_pct < 100 or not 0 < self.target_pct < 100:
            errors.append("SL dan TARGET harus di antara 0 dan 100 persen")
        if not 1 <= self.min_signs <= 4:
            errors.append("MIN_TANDA harus 1..4")
        if not 0 < self.max_hold_h <= MAX_HOLD_LIMIT_H:
            errors.append(f"BATAS_JAM harus di antara 0 dan {MAX_HOLD_LIMIT_H}")
        if self.fee_pct < 0 or self.max_positions < 1 or self.max_stop_streak < 1:
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
