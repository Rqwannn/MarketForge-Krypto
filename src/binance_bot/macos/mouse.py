"""Klik dan gulir mouse sungguhan lewat CoreGraphics. Butuh izin Accessibility.

`click at` dari System Events diabaikan oleh konten web aplikasi Electron (termasuk Binance),
jadi aksi dikirim sebagai event mouse perangkat, sama seperti mouse fisik.

Quartz diimpor saat dipakai (bukan di atas file) agar paket ini tetap bisa diimpor di Windows.
"""

from __future__ import annotations

import time

_HOVER_DELAY_S = 0.15
_PRESS_DELAY_S = 0.06


def _move_to(point: tuple[float, float]) -> None:
    from Quartz import (
        CGEventCreateMouseEvent,
        CGEventPost,
        kCGEventMouseMoved,
        kCGHIDEventTap,
        kCGMouseButtonLeft,
    )

    CGEventPost(
        kCGHIDEventTap,
        CGEventCreateMouseEvent(None, kCGEventMouseMoved, point, kCGMouseButtonLeft),
    )
    time.sleep(_HOVER_DELAY_S)


def click_at(x: int, y: int) -> None:
    """Gerakkan kursor ke (x, y) dalam koordinat layar lalu klik kiri."""
    from Quartz import (
        CGEventCreateMouseEvent,
        CGEventPost,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGHIDEventTap,
        kCGMouseButtonLeft,
    )

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
    from Quartz import (
        CGEventCreateScrollWheelEvent,
        CGEventPost,
        kCGHIDEventTap,
        kCGScrollEventUnitLine,
    )

    _move_to((float(x), float(y)))
    CGEventPost(
        kCGHIDEventTap,
        CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, lines),
    )
