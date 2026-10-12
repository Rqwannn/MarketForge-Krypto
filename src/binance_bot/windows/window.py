"""Posisi jendela, klik, ketik angka, dan tangkapan layar di Windows."""

from __future__ import annotations

import logging
from pathlib import Path

from binance_bot.exceptions import WindowError
from binance_bot.macos.keyboard import NUMBER_PATTERN
from binance_bot.macos.window import Rect
from binance_bot.windows import win32

logger = logging.getLogger(__name__)

_SCROLL_NOTCHES = 7


class WinWindowController:
    """Mengimplementasikan `WindowController`. Hanya angka yang bisa diketik, tanpa Enter."""

    def __init__(self, exe_name: str) -> None:
        self._exe = exe_name

    def bounds(self, app_name: str) -> Rect:
        windows = win32.find_windows(self._exe)
        if not windows:
            raise WindowError(f"Jendela {self._exe} ({app_name}) tidak ditemukan")
        if win32.is_minimized(windows[0]):
            raise WindowError(f"Jendela {app_name} sedang di-minimize")
        box = win32.window_bounds(windows[0])
        return Rect(box.x, box.y, box.width, box.height)

    def resize(self, app_name: str, width: int, height: int) -> None:
        windows = win32.find_windows(self._exe)
        if not windows:
            raise WindowError(f"Jendela {self._exe} ({app_name}) tidak ditemukan")
        try:
            win32.resize_window(windows[0], width, height)
        except OSError as exc:
            raise WindowError(f"Gagal mengatur ukuran jendela: {exc}") from exc

    def click(self, x: int, y: int) -> None:
        logger.info("Klik di (%d, %d)", x, y)
        win32.click_at(x, y)

    def scroll_up(self, x: int, y: int) -> None:
        logger.info("Gulir ke atas di (%d, %d)", x, y)
        win32.scroll_up_at(x, y, _SCROLL_NOTCHES)

    def scroll_down(self, x: int, y: int, notches: int) -> None:
        logger.info("Gulir ke bawah %d langkah di (%d, %d)", notches, x, y)
        win32.scroll_at(x, y, -notches)

    def maximize(self, app_name: str) -> None:
        windows = win32.find_windows(self._exe)
        if not windows:
            raise WindowError(f"Jendela {self._exe} ({app_name}) tidak ditemukan")
        win32.maximize_window(windows[0])

    def clear_field(self) -> None:
        win32.select_all_and_delete()

    def type_number(self, text: str) -> None:
        if not NUMBER_PATTERN.fullmatch(text):
            raise ValueError(f"Hanya angka yang boleh diketik, bukan {text!r}")
        logger.info("Ketik %s", text)
        for char in text:
            win32.type_char(char)

    def capture(self, rect: Rect, path: Path) -> None:
        from PIL import ImageGrab

        try:
            image = ImageGrab.grab(
                bbox=(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height),
                all_screens=True,
            )
            image.save(path)
        except (OSError, ValueError) as exc:
            raise WindowError(f"Tangkapan layar gagal: {exc}") from exc
