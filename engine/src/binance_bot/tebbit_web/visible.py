"""Pastikan jendela Chrome Tebbit benar-benar yang tampil di layar sebelum menangkap atau mengklik.

Jendela bisa berada di Desktop (Space) lain, tertutup aplikasi lain, atau diminimalkan. Menangkap
atau mengklik area jendela dalam keadaan itu akan mengenai aplikasi lain (mis. editor kode), dan
gambarnya bisa terkirim ke AI. Daftar jendela macOS (depan ke belakang) dipakai untuk memastikan
jendela yang paling depan di beberapa titik area itu memang jendela Chrome tersebut.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from binance_bot.macos.window import Rect


@dataclass(frozen=True, slots=True)
class OnScreenWindow:
    owner: str
    bounds: Rect


def on_screen_windows() -> list[OnScreenWindow]:
    """Jendela biasa (layer 0) di Desktop yang sedang tampil, dari depan ke belakang."""
    import Quartz

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    found = []
    for info in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
        if info.get("kCGWindowLayer") != 0:
            continue
        box = info.get("kCGWindowBounds") or {}
        found.append(
            OnScreenWindow(
                str(info.get("kCGWindowOwnerName", "")),
                Rect(
                    round(box.get("X", 0)),
                    round(box.get("Y", 0)),
                    round(box.get("Width", 0)),
                    round(box.get("Height", 0)),
                ),
            )
        )
    return found


def front_owner_at(
    point: tuple[int, int],
    windows: Callable[[], Sequence[OnScreenWindow]] = on_screen_windows,
) -> OnScreenWindow | None:
    """Jendela paling depan yang menutupi titik layar ini (None bila tidak ada)."""
    x, y = point
    for window in windows():
        b = window.bounds
        if b.x <= x < b.x + b.width and b.y <= y < b.y + b.height:
            return window
    return None


def tab_window_is_visible(
    rect: Rect,
    owner: str = "Google Chrome",
    windows: Callable[[], Sequence[OnScreenWindow]] = on_screen_windows,
    tolerance: int = 4,
) -> bool:
    """Area `rect` sepenuhnya milik jendela `owner` yang ukurannya sama (bukan jendela lain)."""
    probes = [
        (rect.x + rect.width // 2, rect.y + rect.height // 2),
        (rect.x + rect.width // 4, rect.y + rect.height // 4),
        (rect.x + 3 * rect.width // 4, rect.y + 3 * rect.height // 4),
    ]
    for point in probes:
        front = front_owner_at(point, windows)
        if front is None or front.owner != owner:
            return False
        b = front.bounds
        if (
            abs(b.x - rect.x) > tolerance
            or abs(b.y - rect.y) > tolerance
            or abs(b.width - rect.width) > tolerance
            or abs(b.height - rect.height) > tolerance
        ):
            return False
    return True
