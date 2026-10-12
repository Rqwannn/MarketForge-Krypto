"""Area kerja tiap monitor Windows (tanpa taskbar), dalam koordinat yang sama dengan jendela."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from binance_bot.macos.window import Rect
from binance_bot.windows import win32

_MONITORINFOF_PRIMARY = 1


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    )


def visible_areas() -> list[Rect]:
    """Area kerja tiap monitor; monitor utama didahulukan."""
    win32.ensure_dpi_aware()
    found: list[tuple[bool, Rect]] = []

    def visit(monitor: int, _dc: int, _rect: object, _data: int) -> bool:
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if win32.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            found.append(
                (
                    bool(info.dwFlags & _MONITORINFOF_PRIMARY),
                    Rect(work.left, work.top, work.right - work.left, work.bottom - work.top),
                )
            )
        return True

    callback_type = win32.win_ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )
    callback = callback_type(visit)
    win32.user32.EnumDisplayMonitors(None, None, callback, 0)
    return [rect for _, rect in sorted(found, key=lambda item: not item[0])]
