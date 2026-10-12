"""Pengganti cek izin macOS. Windows tidak punya izin Accessibility/rekam layar per aplikasi."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from binance_bot.windows import win32


def accessibility_allowed() -> bool:
    """Windows tidak meminta izin untuk klik dan mengetik."""
    return True


def screen_capture_allowed(exe_name: str = "Binance.exe") -> bool:
    """False bila jendela Binance menolak ditangkap layar (display affinity bukan nol).

    Binance Desktop memblokir screenshot bila "perlindungan layar" aktif. Tanpa jendela Binance
    yang terbuka, tidak ada yang diblokir.
    """
    for hwnd in win32.find_windows(exe_name):
        affinity = wintypes.DWORD()
        if win32.user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)) and affinity.value:
            return False
    return True
