"""Profil aturan pola garis cepat terhadap garis pembanding, satu per platform.

Binance dan Tebbit punya indikator bawaan yang berbeda (MA 7/25/99 dan MA 5/10/30), jadi aturan
membaca polanya dipisah: tiap platform punya instruksi AI, periode MA acuan, dan aturan
keputusan sendiri (binance_desktop/pattern_rules.py dan tebbit_web/pattern_rules.py). Mengubah
satu platform tidak mengubah yang lain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from binance_bot.strategy.pattern import MaPattern

Verdict = Callable[[MaPattern, int], str]  # (pola, minimal turun) -> jangan | tunggu | ok


@dataclass(frozen=True, slots=True)
class PatternProfile:
    platform: str  # "binance" | "tebbit"
    fast: int  # periode garis cepat ("garis kuning")
    mid: int  # periode garis pembanding
    slow: int  # periode garis acuan lambat (terlihat di grafik, tidak dihitung)
    recent_candles: int  # lilin 15 menit yang disebut "baru-baru ini" (24 = 6 jam)
    prompt: str  # instruksi untuk AI pembaca grafik (short)
    verdict: Verdict
    long_prompt: str  # instruksi AI untuk tanda masuk LONG (SOP 23 Okt)

    def legend_ready(self, periods: set[int]) -> bool:
        """Legenda grafik memuat garis cepat dan garis pembanding platform ini."""
        return {self.fast, self.mid} <= periods

    @property
    def baseline(self) -> str:
        return f"MA {self.fast}/{self.mid}/{self.slow}"
