"""Algoritma SHORT dikunci: win rate 100% (24 Okt 2026), pemilik meminta tidak diubah.

Tes ini gagal bila satu huruf pun di prompt, aturan, atau pembaca SHORT berubah. Fitur baru (LONG,
aturan jual, dll.) ditambahkan di fungsi baru, bukan dengan mengubah bagian di bawah. Perubahan
SHORT didiskusikan dulu dengan pemilik; hanya setelah pemilik setuju, perbarui sidik jari di FROZEN
bersama perubahan itu.
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Any

import pytest

from binance_bot.analysis import pattern as analysis_pattern
from binance_bot.binance_desktop import pattern_rules as binance_rules
from binance_bot.strategy import pattern as strategy_pattern
from binance_bot.strategy.params import SopParams
from binance_bot.strategy.pattern import MaPattern
from binance_bot.tebbit_web import pattern_rules as tebbit_rules
from binance_bot.workflows import sop

SOURCES: dict[str, tuple[Any, str]] = {
    "binance PROMPT": (binance_rules, "PROMPT"),
    "binance verdict": (binance_rules, "verdict"),
    "tebbit PROMPT": (tebbit_rules, "PROMPT"),
    "tebbit verdict": (tebbit_rules, "verdict"),
    "MaPattern": (strategy_pattern, "MaPattern"),
    "data_ma_pattern": (strategy_pattern, "data_ma_pattern"),
    "ma_gap_pct": (strategy_pattern, "ma_gap_pct"),
    "_sma": (strategy_pattern, "_sma"),
    "candles_needed": (strategy_pattern, "candles_needed"),
    "pattern_from_dict": (analysis_pattern, "pattern_from_dict"),
    "VikeyPatternAnalyzer": (analysis_pattern, "VikeyPatternAnalyzer"),
    "ConsensusAnalyzer": (analysis_pattern, "ConsensusAnalyzer"),
    "short_reason": (sop, "short_reason"),
}
# Sidik jari SHA-256 tiap bagian di atas (24 Okt 2026).
FROZEN = {
    "binance PROMPT": "05d859e6b8bff31d5717066c22521de1cf9b2b999b1df7510173cf98cee31000",
    "binance verdict": "492ebc385d17e750a497ec444f646d93e154b6f86d68d6c99cf919e084e0a884",
    "tebbit PROMPT": "f235639e69e40208e2d457e5b81896f8f23110001027fc92369d4c240c142832",
    "tebbit verdict": "a8f04fb8e1c5de9b09e963fba28c0eef8f3331367099473a801dc5396ae78a5f",
    "MaPattern": "eb087f218bfc08da7bc5ad859630bac9167368e37bcee484ba6429a814c802b8",
    "data_ma_pattern": "09a97c9e3f80284b41c464f541bd1eb7c0c624548bf535d8c71dc81c0bd96e1c",
    "ma_gap_pct": "55a1c0cd5f176826ac6ae07d36cfc31b067b381f5857dc76c05417a78a281b9c",
    "_sma": "5a3e5bdf4b3375cf73d51de062fe41c3e4fc851875f8f6abce3f973a9e80a664",
    "candles_needed": "b7d58ec30091df6a6156fd36f0fcf2f8e969a2c9aa893c9526c4c7d91ad29d71",
    "pattern_from_dict": "1beeea97fa5315216cfac23602093809cd811e6470b45523189449f206d83f82",
    "VikeyPatternAnalyzer": "c3211c04545b509cefb75a62a4585d097d28f43d80068fa5c1907d9cde2221e9",
    "ConsensusAnalyzer": "802bc1e858f059053b83a3ad0448095dc0a194bdda8e4512d3953e9247a8edcd",
    "short_reason": "716338621d07bdd6255cbf926273fcd17f9ad0dd06972155cc4b9ee05be93290",
}


def fingerprint(module: Any, name: str) -> str:
    obj = getattr(module, name)
    text = obj if isinstance(obj, str) else inspect.getsource(obj)
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("label", SOURCES)
def test_short_code_is_unchanged(label: str) -> None:
    module, name = SOURCES[label]
    assert fingerprint(module, name) == FROZEN[label], (
        f"{label} berubah. Algoritma SHORT dikunci: tambahkan logika baru di fungsi baru."
    )


def test_short_numbers_are_unchanged() -> None:
    params = SopParams()
    assert (params.target_pct, params.min_crosses, params.margin_pct, params.leverage) == (
        3.0,
        2,
        50.0,
        2,
    )
    assert (strategy_pattern.LOOKBACK_CANDLES, strategy_pattern.RECENT_CANDLES) == (96, 24)
    assert analysis_pattern._MAX_COUNT == 50
    assert inspect.signature(analysis_pattern.ConsensusAnalyzer).parameters["reads"].default == 5


@pytest.mark.parametrize("profile", [binance_rules.BINANCE, tebbit_rules.TEBBIT])
def test_short_only_decision_follows_the_short_rule_alone(profile: Any) -> None:
    """Tanpa LONG, keputusan SHORT persis aturan platform: masuk hanya bila "ok"."""
    params = SopParams()
    for count in range(4):
        for now in (False, True):
            for recent in (False, True):
                for close in (None, False, True):
                    pattern = MaPattern(count, now, recent, close)
                    verdict = profile.verdict(pattern, params.min_crosses)
                    decision = sop.decide(pattern, None, ("short",), params, profile)
                    assert decision.side == ("short" if verdict == "ok" else None)
                    assert decision.verdict == verdict
