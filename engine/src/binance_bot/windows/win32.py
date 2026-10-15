"""Pembungkus tipis Win32 lewat ctypes (tanpa pustaka tambahan): jendela, mouse, keyboard.

Semua koordinat dalam piksel fisik. `ensure_dpi_aware()` wajib dipanggil sekali di awal supaya
posisi jendela, klik, dan tangkapan layar memakai satuan yang sama pada layar dengan scaling.
"""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

# WinDLL/WINFUNCTYPE hanya ada di ctypes Windows; lewat Any supaya mypy juga lulus di macOS.
win_ctypes: Any = ctypes

user32 = win_ctypes.WinDLL("user32", use_last_error=True)
kernel32 = win_ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = win_ctypes.WinDLL("dwmapi", use_last_error=True)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_SW_RESTORE = 9
_SW_MAXIMIZE = 3
_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP, _MOUSEEVENTF_WHEEL = 0x0002, 0x0004, 0x0800
_KEYEVENTF_KEYUP, _KEYEVENTF_UNICODE = 0x0002, 0x0004
_VK_BACK, _VK_CONTROL, _VK_MENU, _VK_A = 0x08, 0x11, 0x12, 0x41
_WHEEL_DELTA = 120
_KEY_DELAY_S = 0.03


@dataclass(frozen=True, slots=True)
class Bounds:
    x: int
    y: int
    width: int
    height: int


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KeybdInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput), ("ki", _KeybdInput))


class _Input(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _InputUnion))


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
dwmapi.DwmGetWindowAttribute.argtypes = (
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)


def ensure_dpi_aware() -> None:
    """Pakai piksel fisik di semua API. Aman dipanggil berulang."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def _send(inputs: list[_Input]) -> None:
    array = (_Input * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(_Input))
    if sent != len(inputs):
        raise OSError(f"SendInput hanya mengirim {sent} dari {len(inputs)} event")


def _mouse(flags: int, data: int = 0) -> _Input:
    return _Input(type=_INPUT_MOUSE, mi=_MouseInput(0, 0, data & 0xFFFFFFFF, flags, 0, 0))


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _Input:
    return _Input(type=_INPUT_KEYBOARD, ki=_KeybdInput(vk, scan, flags, 0, 0))


def process_image_name(hwnd: int) -> str | None:
    """Nama file exe pemilik jendela, mis. "Binance.exe"."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return os.path.basename(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def window_bounds(hwnd: int) -> Bounds:
    """Persegi jendela yang tampak (tanpa bayangan), dalam piksel layar."""
    rect = wintypes.RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    )
    if hr != 0 and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError("GetWindowRect gagal")
    return Bounds(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def find_windows(exe_name: str) -> list[int]:
    """Jendela tingkat atas yang terlihat milik `exe_name`, terbesar lebih dulu."""
    found: list[tuple[int, int]] = []
    wanted = exe_name.casefold()

    def visit(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            name = process_image_name(hwnd)
            if name and name.casefold() == wanted:
                box = window_bounds(hwnd)
                found.append((box.width * box.height, hwnd))
        return True

    callback = win_ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)
    return [hwnd for _, hwnd in sorted(found, reverse=True)]


def foreground_image_name() -> str | None:
    hwnd = user32.GetForegroundWindow()
    return process_image_name(hwnd) if hwnd else None


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def bring_to_front(hwnd: int) -> None:
    """Pulihkan jendela dan jadikan aktif. Tombol Alt dibunyikan agar Windows mengizinkan."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    _send([_key(_VK_MENU), _key(_VK_MENU, flags=_KEYEVENTF_KEYUP)])
    user32.SetForegroundWindow(hwnd)


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def force_to_front(hwnd: int) -> None:
    """Seperti `bring_to_front`, tetapi lebih gigih untuk jendela yang baru dibuat proses lain.

    Windows menolak SetForegroundWindow dari proses yang bukan pemilik fokus. Utas ini
    disambungkan sementara ke utas jendela yang sedang aktif agar permintaannya diterima.
    """
    bring_to_front(hwnd)
    if foreground_window() == hwnd:
        return
    current = user32.GetForegroundWindow()
    mine = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(current, None) if current else 0
    attached = bool(theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True))
    try:
        user32.ShowWindow(hwnd, _SW_RESTORE if user32.IsIconic(hwnd) else 5)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, theirs, False)


def place_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """Pindahkan dan ubah ukuran jendela yang tampak ke (x, y, width, height)."""
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    visible = window_bounds(hwnd)
    outer = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    # Bingkai tak terlihat (bayangan) antara GetWindowRect dan batas yang tampak.
    left = x - (visible.x - outer.left)
    top = y - (visible.y - outer.top)
    extra_w = (outer.right - outer.left) - visible.width
    extra_h = (outer.bottom - outer.top) - visible.height
    if not user32.SetWindowPos(hwnd, 0, left, top, width + extra_w, height + extra_h, 0x0004):
        raise OSError("SetWindowPos gagal")


def maximize_window(hwnd: int) -> None:
    user32.ShowWindow(hwnd, _SW_MAXIMIZE)
    time.sleep(0.5)


def resize_window(hwnd: int, width: int, height: int) -> None:
    """Ubah ukuran jendela yang tampak menjadi width x height (tanpa menggeser pojok kirinya)."""
    if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    before = window_bounds(hwnd)
    outer = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    # Selisih bingkai tak terlihat (bayangan) antara GetWindowRect dan batas yang tampak.
    extra_w = (outer.right - outer.left) - before.width
    extra_h = (outer.bottom - outer.top) - before.height
    if not user32.SetWindowPos(
        hwnd, 0, outer.left, outer.top, width + extra_w, height + extra_h, 0x0004
    ):
        raise OSError("SetWindowPos gagal")


def click_at(x: int, y: int, *, hover_s: float = 0.15, press_s: float = 0.06) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(hover_s)
    _send([_mouse(_MOUSEEVENTF_LEFTDOWN)])
    time.sleep(press_s)
    _send([_mouse(_MOUSEEVENTF_LEFTUP)])


def scroll_at(x: int, y: int, notches: int) -> None:
    """Gulir roda mouse di (x, y): `notches` positif = ke atas, negatif = ke bawah."""
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    delta = _WHEEL_DELTA if notches > 0 else -_WHEEL_DELTA
    for _ in range(abs(notches)):
        _send([_mouse(_MOUSEEVENTF_WHEEL, delta)])
        time.sleep(0.02)


def scroll_up_at(x: int, y: int, notches: int) -> None:
    scroll_at(x, y, abs(notches))


def select_all_and_delete() -> None:
    """Ctrl+A lalu Backspace untuk mengosongkan kolom yang sedang fokus."""
    _send([_key(_VK_CONTROL), _key(_VK_A), _key(_VK_A, flags=_KEYEVENTF_KEYUP)])
    _send([_key(_VK_CONTROL, flags=_KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)
    _send([_key(_VK_BACK), _key(_VK_BACK, flags=_KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)


def select_all() -> None:
    """Ctrl+A: pilih seluruh isi kolom yang sedang fokus (tanpa menghapus)."""
    _send([_key(_VK_CONTROL), _key(_VK_A), _key(_VK_A, flags=_KEYEVENTF_KEYUP)])
    _send([_key(_VK_CONTROL, flags=_KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)


def type_char(char: str) -> None:
    code = ord(char)
    _send([_key(scan=code, flags=_KEYEVENTF_UNICODE)])
    _send([_key(scan=code, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)


# --------------------------------------------------------------------------- Chrome (Tebbit)

_VK_RETURN, _VK_DELETE, _VK_L, _VK_0, _VK_OEM_MINUS = 0x0D, 0x2E, 0x4C, 0x30, 0xBD
_WM_CLOSE = 0x0010
_DWMWA_CLOAKED = 14
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


def window_exists(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd))


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def content_bounds(hwnd: int) -> Bounds | None:
    """Area isi halaman peramban (tanpa tab, bilah alamat, dan bilah bookmark), atau None."""
    found: list[Bounds] = []

    def visit(child: int, _lparam: int) -> bool:
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(child, name, 64)
        if name.value == "Chrome_RenderWidgetHostHWND" and user32.IsWindowVisible(child):
            box = wintypes.RECT()
            user32.GetWindowRect(child, ctypes.byref(box))
            found.append(Bounds(box.left, box.top, box.right - box.left, box.bottom - box.top))
        return True

    callback = win_ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumChildWindows(hwnd, callback, 0)
    return max(found, key=lambda b: b.width * b.height, default=None)


def close_window(hwnd: int) -> None:
    """Minta jendela menutup diri (seperti menekan tombol X)."""
    user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)


def is_cloaked(hwnd: int) -> bool:
    """Jendela disembunyikan Windows (mis. berada di desktop virtual lain)."""
    state = wintypes.DWORD()
    hr = dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_CLOAKED, ctypes.byref(state), ctypes.sizeof(state)
    )
    return hr == 0 and state.value != 0


def on_screen_windows() -> list[tuple[str, Bounds]]:
    """Jendela biasa yang tampil di desktop aktif, dari depan ke belakang: (nama exe, persegi)."""
    found: list[tuple[str, Bounds]] = []

    def visit(hwnd: int, _lparam: int) -> bool:
        if (
            user32.IsWindowVisible(hwnd)
            and not user32.IsIconic(hwnd)
            and user32.GetWindowTextLengthW(hwnd) > 0
            and not is_cloaked(hwnd)
        ):
            name = process_image_name(hwnd)
            box = window_bounds(hwnd)
            if name and box.width > 0 and box.height > 0:
                found.append((name, box))
        return True

    callback = win_ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)  # EnumWindows berjalan dari depan ke belakang (urutan Z)
    return found


def _combo(*keys: int) -> None:
    """Tekan beberapa tombol bersamaan (tombol terakhir diketuk), lalu lepaskan semuanya."""
    *held, tap = keys
    _send([_key(vk) for vk in held] + [_key(tap), _key(tap, flags=_KEYEVENTF_KEYUP)])
    _send([_key(vk, flags=_KEYEVENTF_KEYUP) for vk in reversed(held)])
    time.sleep(_KEY_DELAY_S)


def _check(guard: Callable[[], bool] | None) -> None:
    if guard is not None and not guard():
        raise OSError("fokus berpindah ke jendela lain; pengetikan dihentikan")


def browser_zoom(steps_down: int, guard: Callable[[], bool] | None = None) -> None:
    """Zoom halaman: Ctrl+0 (100%) lalu `steps_down` kali Ctrl+minus. Peramban harus di depan.

    `guard` diperiksa sebelum tiap tombol: tombol tidak boleh jatuh ke aplikasi lain.
    """
    _check(guard)
    _combo(_VK_CONTROL, _VK_0)
    for _ in range(steps_down):
        _check(guard)
        _combo(_VK_CONTROL, _VK_OEM_MINUS)
        time.sleep(0.15)


def browser_type_address(url: str, guard: Callable[[], bool] | None = None) -> None:
    """Pilih bilah alamat (Ctrl+L) lalu ketik `url`, TANPA Enter. Alamat sudah divalidasi pemanggil.

    `guard` diperiksa sebelum Ctrl+L dan tiap beberapa karakter. Bilah alamat butuh sesaat untuk
    menerima fokus; karakter pertama yang datang terlalu cepat bisa hilang, jadi pemanggil wajib
    membaca isinya sebelum `browser_commit_address`.
    """
    _check(guard)
    _combo(_VK_CONTROL, _VK_L)
    time.sleep(0.5)
    for index, char in enumerate(url):
        if index % 6 == 0:
            _check(guard)
        type_char(char)


def browser_commit_address(guard: Callable[[], bool] | None = None) -> None:
    """Enter di bilah alamat. Delete dulu membuang saran pelengkapan otomatis Chrome."""
    _check(guard)
    _send([_key(_VK_DELETE), _key(_VK_DELETE, flags=_KEYEVENTF_KEYUP)])
    time.sleep(0.1)
    _check(guard)
    _send([_key(_VK_RETURN), _key(_VK_RETURN, flags=_KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)
