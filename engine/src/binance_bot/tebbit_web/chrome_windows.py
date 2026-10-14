"""Kendali Chrome untuk tab Tebbit di Windows (Win32 dan UI Automation, tanpa port debug).

Padanan `chrome.py` (macOS/AppleScript). Yang dilakukan hanya: membuka jendela Chrome baru di
alamat Tebbit, mengatur posisi dan ukurannya, membawanya ke depan, membaca alamatnya, dan
menutupnya. Isi halaman tidak dibaca dan jendela lain tidak disentuh. Satu-satunya teks yang
diketik ke Chrome adalah alamat tebbit.io yang sudah divalidasi.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from binance_bot.exceptions import WindowError
from binance_bot.macos.window import Rect
from binance_bot.tebbit_web.chrome import CHROME_EXE, HOME_URL, check_url
from binance_bot.windows import win32
from binance_bot.windows.window import WinWindowController

logger = logging.getLogger(__name__)

_OPEN_TIMEOUT_S = 25.0
_FOCUS_TIMEOUT_S = 4.0
_URL_ATTEMPTS = 4

# Membaca kotak alamat lewat UI Automation. Chrome menampilkan alamat tanpa "https://".
_READ_ADDRESS = r"""
$Hwnd = __HWND__
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
$type = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
$kind = [System.Windows.Automation.ControlType]::Edit
$edit = New-Object System.Windows.Automation.PropertyCondition($type, $kind)
foreach ($e in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $edit)) {
  try {
    $v = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
    if ($v -match '^[\w.-]+\.[a-z]{2,}(/|$)|^https?://') { Write-Output $v; break }
  } catch {}
}
"""


def chrome_path(env: Mapping[str, str] | None = None) -> Path:
    """Lokasi chrome.exe: `BOT_CHROME_PATH`, lalu lokasi pemasangan umum."""
    env = os.environ if env is None else env  # os.environ: nama variabel tak peka huruf di Windows
    candidates = [Path(env["BOT_CHROME_PATH"])] if env.get("BOT_CHROME_PATH") else []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if env.get(key):
            candidates.append(Path(env[key]) / "Google" / "Chrome" / "Application" / CHROME_EXE)
    for path in candidates:
        if path.is_file():
            return path
    raise WindowError(
        "Google Chrome tidak ditemukan. Pasang Chrome, atau isi BOT_CHROME_PATH di .env dengan "
        "path lengkap chrome.exe."
    )


def with_scheme(address: str) -> str:
    """Chrome menampilkan alamat tanpa "https://": lengkapi agar bisa diurai."""
    address = address.strip()
    return address if re.match(r"^https?://", address) else f"https://{address}"


class WinChromeController:
    """Membuka dan mengatur jendela Chrome khusus untuk Tebbit. Id jendela = handle jendela.

    Tombol hanya dikirim bila jendela Tebbit milik bot benar-benar yang aktif. Windows tidak punya
    padanan "kirim tombol ke jendela ini" seperti AppleScript, jadi tombol selalu masuk ke jendela
    aktif; karena itu fokus diperiksa sebelum dan selama pengetikan, dan pengetikan dihentikan
    bila fokus berpindah.
    """

    def __init__(
        self,
        launch: Callable[[list[str]], object] = lambda cmd: subprocess.Popen(cmd),
        read_address: Callable[[int], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        win: Any = win32,
    ) -> None:
        self._launch = launch
        self._read_address = read_address or _address_via_uia
        self._sleep = sleep
        self._clock = clock
        self._win = win

    def open_window(self, url: str = HOME_URL) -> int:
        """Buka jendela Chrome baru di alamat Tebbit dan kembalikan id jendelanya."""
        check_url(url)
        before = set(self._win.find_windows(CHROME_EXE))
        self._launch([str(chrome_path()), "--new-window", url])
        deadline = self._clock() + _OPEN_TIMEOUT_S
        while self._clock() < deadline:
            new = [h for h in self._win.find_windows(CHROME_EXE) if h not in before]
            if new:
                return int(new[0])
            self._sleep(0.5)
        raise WindowError("Jendela Chrome baru untuk Tebbit tidak muncul")

    def window_exists(self, window_id: int) -> bool:
        return bool(self._win.window_exists(window_id))

    def close_window(self, window_id: int) -> None:
        if self.window_exists(window_id):
            self._win.close_window(window_id)

    def raise_window(self, window_id: int) -> None:
        """Bawa jendela ke depan; gagal (WindowError) bila Windows tetap menolaknya."""
        deadline = self._clock() + _FOCUS_TIMEOUT_S
        while True:
            self._win.force_to_front(window_id)
            self._sleep(0.2)
            if self._is_front(window_id):
                return
            if self._clock() >= deadline:
                raise WindowError(
                    "Jendela Chrome Tebbit tidak bisa dibawa ke depan. Tombol tidak dikirim "
                    "supaya tidak masuk ke aplikasi lain."
                )

    def open_url(self, window_id: int, url: str) -> None:
        check_url(url)
        self.raise_window(window_id)
        self._type(lambda guard: self._win.browser_go(url, guard), window_id)

    def current_url(self, window_id: int) -> str:
        for _ in range(_URL_ATTEMPTS):
            address = self._read_address(window_id).strip()
            if address:
                return with_scheme(address)
            self._sleep(0.5)  # Chrome menyalakan pohon aksesibilitasnya saat pertama ditanya
        raise WindowError("Alamat tab Chrome tidak terbaca")

    def tab_title(self, window_id: int) -> str:
        return re.sub(r"\s*-\s*Google Chrome$", "", self._win.window_title(window_id))

    def bounds(self, window_id: int) -> Rect:
        box = self._win.window_bounds(window_id)
        return Rect(box.x, box.y, box.width, box.height)

    def content_bounds(self, window_id: int) -> Rect:
        """Isi halaman saja: tinggi tab, bilah alamat, dan bookmark berbeda di tiap laptop."""
        box = self._win.content_bounds(window_id)
        if box is None:
            logger.warning("Area isi halaman Chrome tidak ditemukan; memakai seluruh jendela")
            return self.bounds(window_id)
        return Rect(box.x, box.y, box.width, box.height)

    def set_bounds(self, window_id: int, rect: Rect) -> None:
        try:
            self._win.place_window(window_id, rect.x, rect.y, rect.width, rect.height)
        except OSError as exc:
            raise WindowError(f"Tidak bisa mengatur ukuran jendela Chrome: {exc}") from exc

    def set_zoom(self, steps_down: int, window_id: int | None = None) -> None:
        """Zoom halaman: Ctrl+0 (100%) lalu `steps_down` kali Ctrl+minus."""
        if window_id is None:
            raise WindowError("Jendela Tebbit belum dibuka: zoom tidak diatur")
        self.raise_window(window_id)
        self._type(lambda guard: self._win.browser_zoom(steps_down, guard), window_id)

    def _is_front(self, window_id: int) -> bool:
        return bool(self._win.foreground_window() == window_id)

    def _type(self, action: Callable[[Callable[[], bool]], None], window_id: int) -> None:
        try:
            action(lambda: self._is_front(window_id))
        except OSError as exc:
            raise WindowError(f"Tombol tidak dikirim ke Chrome Tebbit: {exc}") from exc


def _address_via_uia(window_id: int) -> str:
    script = _READ_ADDRESS.replace("__HWND__", str(int(window_id)))
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout.strip()


class WinChromeWindowController(WinWindowController):
    """Jendela Chrome untuk Tebbit: ukuran dan posisi dari Chrome, klik dan ketik biasa."""

    def __init__(self, chrome: WinChromeController) -> None:
        super().__init__(CHROME_EXE)
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
