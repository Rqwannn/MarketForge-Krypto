"""Ketik angka ke kolom yang sedang fokus lewat System Events. Butuh izin Accessibility.

Sengaja terbatas: hanya angka dan tanda desimal, plus "pilih semua" dan hapus untuk
mengosongkan kolom. Tidak ada Enter/Return, jadi modul ini tidak bisa mengirim order.

Ketikan CoreGraphics (CGEvent) ditolak kolom angka aplikasi berbasis Chromium (Binance Desktop
dan Chrome), sedangkan `keystroke` System Events diterima seperti ketikan keyboard biasa.
Ketikan masuk ke aplikasi yang paling depan: pemanggil wajib memastikannya dulu.
"""

from __future__ import annotations

import re

from binance_bot.macos.app_controller import Runner, run_command

NUMBER_PATTERN = re.compile(r"[0-9]+([.,][0-9]+)?")
_DELETE = 51  # key code tombol Delete (backspace)


def _system_events(lines: list[str], run: Runner) -> None:
    script = "\n".join(['tell application "System Events"', *lines, "end tell"])
    run(["osascript", "-e", script])


def clear_field(run: Runner = run_command) -> None:
    """Kosongkan kolom yang sedang fokus (Cmd+A lalu hapus)."""
    _system_events(['\tkeystroke "a" using command down', f"\tkey code {_DELETE}"], run)


def type_number(text: str, run: Runner = run_command) -> None:
    """Ketik angka seperti "184,6". Menolak apa pun selain angka dan satu tanda desimal."""
    if not NUMBER_PATTERN.fullmatch(text):
        raise ValueError(f"Hanya angka yang boleh diketik, bukan {text!r}")
    _system_events([f'\tkeystroke "{char}"' for char in text], run)
