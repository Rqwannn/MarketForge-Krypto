"""Pilih lapisan sistem sesuai OS: macOS atau Windows. Modul platform diimpor saat dibutuhkan."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.macos import AppController, TextReader, WindowController


@dataclass(frozen=True, slots=True)
class System:
    apps: AppController
    window: WindowController
    reader: TextReader


def build_system(settings: Settings, platform: str | None = None) -> System:
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        from binance_bot.macos import MacAppController, MacTextReader, MacWindowController

        return System(MacAppController(), MacWindowController(), MacTextReader())
    if platform == "win32":
        from binance_bot.windows import WinAppController, WinTextReader, WinWindowController
        from binance_bot.windows.win32 import ensure_dpi_aware

        ensure_dpi_aware()
        return System(
            WinAppController(), WinWindowController(settings.app_bundle_id), WinTextReader()
        )
    raise BotError(f"Platform {platform!r} belum didukung (hanya macOS dan Windows)")
