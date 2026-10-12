"""Ketik angka ke kolom yang sedang fokus lewat CoreGraphics. Butuh izin Accessibility.

Sengaja terbatas: hanya angka dan tanda desimal, plus "pilih semua" dan hapus untuk
mengosongkan kolom. Tidak ada Enter/Return, jadi modul ini tidak bisa mengirim order.
"""

from __future__ import annotations

import re
import time

_KEY_A = 0
_KEY_DELETE = 51
_KEY_DELAY_S = 0.03
NUMBER_PATTERN = re.compile(r"[0-9]+([.,][0-9]+)?")


def _key(keycode: int, *, command: bool = False, text: str | None = None) -> None:
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
        kCGHIDEventTap,
    )

    for down in (True, False):
        event = CGEventCreateKeyboardEvent(None, keycode, down)
        if command:
            CGEventSetFlags(event, kCGEventFlagMaskCommand)
        if text is not None:
            CGEventKeyboardSetUnicodeString(event, len(text), text)
        CGEventPost(kCGHIDEventTap, event)
    time.sleep(_KEY_DELAY_S)


def clear_field() -> None:
    """Kosongkan kolom yang sedang fokus (Cmd+A lalu hapus)."""
    _key(_KEY_A, command=True)
    _key(_KEY_DELETE)


def type_number(text: str) -> None:
    """Ketik angka seperti "184,6". Menolak apa pun selain angka dan satu tanda desimal."""
    if not NUMBER_PATTERN.fullmatch(text):
        raise ValueError(f"Hanya angka yang boleh diketik, bukan {text!r}")
    for char in text:
        _key(_KEY_A, text=char)
