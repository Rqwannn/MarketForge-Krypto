"""Lapisan sistem macOS: aplikasi, jendela, mouse, keyboard, tangkapan layar, dan OCR."""

from binance_bot.macos.app_controller import AppController, MacAppController
from binance_bot.macos.ocr import MacTextReader, TextLine, TextReader
from binance_bot.macos.waiting import wait_for_window, wait_until_frontmost
from binance_bot.macos.window import MacWindowController, Rect, WindowController

__all__ = [
    "AppController",
    "MacAppController",
    "MacTextReader",
    "MacWindowController",
    "Rect",
    "TextLine",
    "TextReader",
    "WindowController",
    "wait_for_window",
    "wait_until_frontmost",
]
