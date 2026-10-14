"""Kendali Chrome untuk tab Tebbit lewat AppleScript (tanpa JavaScript dan tanpa port debug).

Yang dilakukan hanya: membuka jendela Chrome baru di alamat Tebbit, mengatur posisi dan ukurannya,
membawanya ke depan, dan menutupnya. Isi halaman tidak dibaca dan jendela lain tidak disentuh.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from binance_bot.exceptions import CommandError, WindowError
from binance_bot.macos.app_controller import Runner, run_command
from binance_bot.macos.window import MacWindowController, Rect

logger = logging.getLogger(__name__)

CHROME_NAME = "Google Chrome"
CHROME_BUNDLE_ID = "com.google.Chrome"
CHROME_EXE = "chrome.exe"  # Windows: nama proses sebagai pengenal aplikasi
SITE = "tebbit.io"
HOME_URL = f"https://{SITE}/"


class Browser(Protocol):
    """Kendali jendela Chrome Tebbit; ada versi macOS (`ChromeController`) dan Windows."""

    def open_window(self, url: str = ...) -> int: ...
    def window_exists(self, window_id: int) -> bool: ...
    def close_window(self, window_id: int) -> None: ...
    def raise_window(self, window_id: int) -> None: ...
    def open_url(self, window_id: int, url: str) -> None: ...
    def current_url(self, window_id: int) -> str: ...
    def tab_title(self, window_id: int) -> str: ...
    def bounds(self, window_id: int) -> Rect: ...
    def content_bounds(self, window_id: int) -> Rect: ...
    def set_bounds(self, window_id: int, rect: Rect) -> None: ...
    def set_zoom(self, steps_down: int, window_id: int | None = None) -> None: ...


class ChromeController:
    """Membuka dan mengatur jendela Chrome khusus untuk Tebbit.

    Bot membuka jendela barunya sendiri (muncul di Desktop yang sedang aktif, dengan sesi login
    Chrome pengguna), sehingga pengguna tidak perlu menyiapkan apa pun dan tidak ada jendela
    atau tab lain yang disentuh.
    """

    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner

    def open_window(self, url: str = HOME_URL) -> int:
        """Buka jendela Chrome baru di alamat Tebbit dan kembalikan id jendelanya."""
        check_url(url)
        script = "\n".join(
            [
                'tell application "Google Chrome"',
                "\tactivate",
                "\tset w to make new window",
                f'\tset URL of active tab of w to "{url}"',
                "\treturn id of w",
                "end tell",
            ]
        )
        out = self._osascript(script, "Tidak bisa membuka jendela Chrome").strip()
        if not out.isdigit():
            raise WindowError(f"Chrome tidak mengembalikan id jendela: {out!r}")
        return int(out)

    def window_exists(self, window_id: int) -> bool:
        try:
            script = f'tell application "Google Chrome" to get id of window id {window_id}'
            return self._run(["osascript", "-e", script]).strip() == str(window_id)
        except CommandError:
            return False

    def close_window(self, window_id: int) -> None:
        if self.window_exists(window_id):
            script = f'tell application "Google Chrome" to close window id {window_id}'
            self._osascript(script, "Tidak bisa menutup jendela Chrome")

    def raise_window(self, window_id: int) -> None:
        script = "\n".join(
            [
                'tell application "Google Chrome"',
                f"\tset index of window id {window_id} to 1",
                "\tactivate",
                "end tell",
            ]
        )
        self._osascript(script, "Tidak bisa membawa jendela Chrome ke depan")

    def open_url(self, window_id: int, url: str) -> None:
        check_url(url)
        script = (
            f'tell application "Google Chrome" to set URL of active tab of window id {window_id} '
            f'to "{url}"'
        )
        self._osascript(script, "Tidak bisa membuka alamat di tab Tebbit")

    def current_url(self, window_id: int) -> str:
        script = (
            f'tell application "Google Chrome" to get URL of active tab of window id {window_id}'
        )
        return self._osascript(script, "Tidak bisa membaca alamat tab").strip()

    def tab_title(self, window_id: int) -> str:
        script = (
            f'tell application "Google Chrome" to get title of active tab of window id {window_id}'
        )
        return self._osascript(script, "Tidak bisa membaca judul tab").strip()

    def bounds(self, window_id: int) -> Rect:
        script = f'tell application "Google Chrome" to get bounds of window id {window_id}'
        out = self._osascript(script, "Tidak bisa membaca jendela Chrome")
        try:
            left, top, right, bottom = (int(p) for p in out.split(","))
        except ValueError as exc:
            raise WindowError(f"Format jendela Chrome tidak dikenal: {out.strip()!r}") from exc
        return Rect(left, top, right - left, bottom - top)

    def content_bounds(self, window_id: int) -> Rect:
        """Area yang dipetakan klik dan baca layar: di macOS seluruh jendela Chrome."""
        return self.bounds(window_id)

    def set_bounds(self, window_id: int, rect: Rect) -> None:
        script = (
            'tell application "Google Chrome" to set bounds of window id '
            f"{window_id} to {{{rect.x}, {rect.y}, {rect.x + rect.width}, {rect.y + rect.height}}}"
        )
        self._osascript(script, "Tidak bisa mengatur ukuran jendela Chrome")

    def set_zoom(self, steps_down: int, window_id: int | None = None) -> None:
        """Zoom halaman: Cmd+0 (100%) lalu `steps_down` kali Cmd+minus. Chrome harus di depan."""
        keys = ["0"] + ["-"] * steps_down
        for key in keys:
            script = f'tell application "System Events" to keystroke "{key}" using command down'
            self._osascript(script, "Tidak bisa mengatur zoom Chrome")

    def _osascript(self, script: str, failure: str) -> str:
        try:
            return self._run(["osascript", "-e", script])
        except CommandError as exc:
            raise WindowError(
                f"{failure}. Izinkan kendali Chrome bila macOS bertanya. ({exc})"
            ) from exc


def check_url(url: str) -> None:
    if not re.fullmatch(rf"https://(www\.)?{re.escape(SITE)}/[A-Za-z0-9_./?=&%-]*", url):
        raise WindowError(f"Alamat bukan halaman {SITE}: {url!r}")


class ChromeWindowController(MacWindowController):
    """Jendela Chrome untuk Tebbit: ukuran dan posisi dari Chrome, klik dan ketik biasa."""

    def __init__(self, chrome: ChromeController, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._chrome = chrome
        self.window_id: int | None = None

    def bounds(self, app_name: str) -> Rect:
        if self.window_id is None:
            raise WindowError("Tab Tebbit belum dipilih")
        return self._chrome.bounds(self.window_id)

    def set_bounds(self, app_name: str, rect: Rect) -> None:
        if self.window_id is None:
            raise WindowError("Tab Tebbit belum dipilih")
        self._chrome.set_bounds(self.window_id, rect)
