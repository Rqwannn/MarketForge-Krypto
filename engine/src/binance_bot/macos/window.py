"""Posisi jendela, klik, dan tangkapan layar.

Butuh izin Accessibility (posisi dan klik) serta Screen Recording (tangkapan layar)
untuk aplikasi yang menjalankan bot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binance_bot.exceptions import CommandError, WindowError
from binance_bot.macos.app_controller import Runner, run_command
from binance_bot.macos.keyboard import clear_field, type_number
from binance_bot.macos.mouse import click_at, scroll_down_at, scroll_up_at

logger = logging.getLogger(__name__)

_PERMISSION_HINT = (
    "Pastikan aplikasi yang menjalankan bot (VS Code/Terminal) punya izin Accessibility "
    "dan Screen & System Audio Recording di System Settings > Privacy & Security."
)


@dataclass(frozen=True, slots=True)
class Rect:
    """Persegi dalam koordinat layar (point, bukan piksel)."""

    x: int
    y: int
    width: int
    height: int

    def point_at(self, fx: float, fy: float) -> tuple[int, int]:
        """Titik pada posisi relatif (0..1) di dalam persegi ini."""
        return round(self.x + self.width * fx), round(self.y + self.height * fy)

    def contains(self, other: Rect) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.x + other.width <= self.x + self.width
            and other.y + other.height <= self.y + self.height
        )

    def sub(self, x0: float, y0: float, x1: float, y1: float) -> Rect:
        """Sub-persegi dari dua sudut relatif (0..1), mis. untuk memotong area grafik."""
        left, top = self.point_at(x0, y0)
        right, bottom = self.point_at(x1, y1)
        return Rect(left, top, right - left, bottom - top)


class WindowController(Protocol):
    def bounds(self, app_name: str) -> Rect: ...

    def set_bounds(self, app_name: str, rect: Rect) -> None: ...

    def click(self, x: int, y: int) -> None: ...

    def scroll_up(self, x: int, y: int) -> None: ...

    def scroll_down(self, x: int, y: int, notches: int) -> None: ...

    def clear_field(self) -> None: ...

    def type_number(self, text: str) -> None: ...

    def capture(self, rect: Rect, path: Path) -> None: ...


class MacWindowController:
    def __init__(
        self,
        runner: Runner = run_command,
        mouse_click: Callable[[int, int], None] = click_at,
        mouse_scroll_up: Callable[[int, int], None] = scroll_up_at,
        mouse_scroll_down: Callable[[int, int, int], None] = scroll_down_at,
        keyboard_clear: Callable[[], None] = clear_field,
        keyboard_type: Callable[[str], None] = type_number,
    ) -> None:
        self._run = runner
        self._mouse_click = mouse_click
        self._mouse_scroll_up = mouse_scroll_up
        self._mouse_scroll_down = mouse_scroll_down
        self._keyboard_clear = keyboard_clear
        self._keyboard_type = keyboard_type

    def bounds(self, app_name: str) -> Rect:
        script = (
            f'tell application "System Events" to tell process "{app_name}" '
            "to get {position, size} of window 1"
        )
        out = self._osascript(script, f"Tidak bisa membaca jendela {app_name}")
        try:
            x, y, width, height = (int(part) for part in out.split(","))
        except ValueError as exc:
            raise WindowError(f"Format posisi jendela tidak dikenal: {out.strip()!r}") from exc
        return Rect(x, y, width, height)

    def set_bounds(self, app_name: str, rect: Rect) -> None:
        """Pindahkan dan ubah ukuran jendela pertama aplikasi (lewat Accessibility)."""
        script = "\n".join(
            [
                f'tell application "System Events" to tell process "{app_name}" to tell window 1',
                f"set position to {{{rect.x}, {rect.y}}}",
                f"set size to {{{rect.width}, {rect.height}}}",
                "end tell",
            ]
        )
        self._osascript(script, f"Tidak bisa mengatur ukuran jendela {app_name}")

    def click(self, x: int, y: int) -> None:
        logger.info("Klik di (%d, %d)", x, y)
        self._mouse_click(x, y)

    def scroll_up(self, x: int, y: int) -> None:
        logger.info("Gulir ke atas di (%d, %d)", x, y)
        self._mouse_scroll_up(x, y)

    def scroll_down(self, x: int, y: int, notches: int) -> None:
        logger.info("Gulir ke bawah %d langkah di (%d, %d)", notches, x, y)
        self._mouse_scroll_down(x, y, notches)

    def clear_field(self) -> None:
        self._keyboard_clear()

    def type_number(self, text: str) -> None:
        logger.info("Ketik %s", text)
        self._keyboard_type(text)

    def capture(self, rect: Rect, path: Path) -> None:
        region = f"{rect.x},{rect.y},{rect.width},{rect.height}"
        try:
            self._run(["screencapture", "-x", "-R", region, str(path)])
        except CommandError as exc:
            raise WindowError(f"Tangkapan layar gagal. {_PERMISSION_HINT} ({exc})") from exc
        if not path.exists():
            raise WindowError(f"Tangkapan layar tidak menghasilkan file. {_PERMISSION_HINT}")

    def _osascript(self, script: str, failure: str) -> str:
        try:
            return self._run(["osascript", "-e", script])
        except CommandError as exc:
            raise WindowError(f"{failure}. {_PERMISSION_HINT} ({exc})") from exc
