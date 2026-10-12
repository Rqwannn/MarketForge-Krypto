"""Pilih lapisan sistem sesuai OS: macOS atau Windows. Modul platform diimpor saat dibutuhkan."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.macos import AppController, Rect, TextReader, WindowController


@dataclass(frozen=True, slots=True)
class System:
    apps: AppController
    window: WindowController
    reader: TextReader
    screens: Callable[[], Sequence[Rect]]
    accessibility_allowed: Callable[[], bool]
    screen_capture_allowed: Callable[[], bool]


def build_system(settings: Settings, platform: str | None = None) -> System:
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        from binance_bot.macos import MacAppController, MacTextReader, MacWindowController
        from binance_bot.macos.permissions import accessibility_allowed, screen_capture_allowed
        from binance_bot.macos.screens import visible_areas

        return System(
            MacAppController(),
            MacWindowController(),
            MacTextReader(),
            visible_areas,
            accessibility_allowed,
            screen_capture_allowed,
        )
    if platform == "win32":
        from binance_bot.windows import WinAppController, WinTextReader, WinWindowController
        from binance_bot.windows.permissions import accessibility_allowed as win_accessibility
        from binance_bot.windows.permissions import screen_capture_allowed as win_screen_capture
        from binance_bot.windows.screens import visible_areas as win_visible_areas
        from binance_bot.windows.win32 import ensure_dpi_aware

        ensure_dpi_aware()
        return System(
            WinAppController(),
            WinWindowController(settings.app_bundle_id),
            WinTextReader(),
            win_visible_areas,
            win_accessibility,
            partial(win_screen_capture, settings.app_bundle_id),
        )
    raise BotError(f"Platform {platform!r} belum didukung (hanya macOS dan Windows)")
