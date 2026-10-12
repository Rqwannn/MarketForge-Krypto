"""Klik dan gulir mouse sungguhan lewat CoreGraphics. Butuh izin Accessibility.

`click at` dari System Events diabaikan oleh konten web aplikasi Electron (termasuk Binance),
jadi aksi dikirim sebagai event mouse perangkat, sama seperti mouse fisik.
"""

from __future__ import annotations

import time

from Quartz import (
    CGEventCreateMouseEvent,
    CGEventCreateScrollWheelEvent,
    CGEventPost,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
    kCGScrollEventUnitLine,
)

_HOVER_DELAY_S = 0.15
_PRESS_DELAY_S = 0.06


def _move_to(point: tuple[float, float]) -> None:
    CGEventPost(
        kCGHIDEventTap,
        CGEventCreateMouseEvent(None, kCGEventMouseMoved, point, kCGMouseButtonLeft),
    )
    time.sleep(_HOVER_DELAY_S)


def click_at(x: int, y: int) -> None:
    """Gerakkan kursor ke (x, y) dalam koordinat layar lalu klik kiri."""
    point = (float(x), float(y))
    _move_to(point)
    for event_type, delay in ((kCGEventLeftMouseDown, _PRESS_DELAY_S), (kCGEventLeftMouseUp, 0.0)):
        CGEventPost(
            kCGHIDEventTap,
            CGEventCreateMouseEvent(None, event_type, point, kCGMouseButtonLeft),
        )
        time.sleep(delay)


def scroll_up_at(x: int, y: int, lines: int = 20) -> None:
    """Gulir ke atas di (x, y). Arahkan ke area yang bukan grafik, karena grafik akan ter-zoom."""
    _move_to((float(x), float(y)))
    CGEventPost(
        kCGHIDEventTap,
        CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, lines),
    )
