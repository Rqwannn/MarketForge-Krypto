"""Profil dialog leverage dan mode margin: posisi, judul, dan tombol, satu per platform.

Binance Desktop dan Tebbit sama-sama punya dialog "ubah leverage" (kolom nilai, slider, konfirmasi)
dan dialog mode margin (Cross/Isolated), tetapi teks dan letaknya berbeda. Alur pengaturnya
(`BinanceNavigator.apply_margin`) sama dan memakai profil ini.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Area = tuple[float, float, float, float]
Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class MarginDialogs:
    bar_area: Area  # tombol mode margin dan leverage di atas form order
    dialog_area: Area  # tempat kedua dialog muncul (modal di tengah halaman)
    field_band: tuple[float, float]  # kolom nilai leverage: sekian di bawah baris judul dialog
    leverage_close_x: float  # tombol X dialog leverage (di baris judulnya)
    mode_close_x: float  # tombol X dialog mode margin
    leverage_title: re.Pattern[str]
    leverage_name: str
    mode_title: re.Pattern[str]
    mode_name: str
    confirm: re.Pattern[str]
    isolated_option: re.Pattern[str]
    mode_button: re.Pattern[str]
    # Posisi tetap tombol di atas form, bila membacanya dengan OCR tidak andal (None = pakai OCR).
    leverage_click: Point | None = None
    mode_click: Point | None = None
