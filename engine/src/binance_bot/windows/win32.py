"""Pembungkus tipis Win32 lewat ctypes (tanpa pustaka tambahan): jendela, mouse, keyboard.

Semua koordinat dalam piksel fisik. `ensure_dpi_aware()` wajib dipanggil sekali di awal supaya
posisi jendela, klik, dan tangkapan layar memakai satuan yang sama pada layar dengan scaling.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

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

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
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


def type_char(char: str) -> None:
    code = ord(char)
    _send([_key(scan=code, flags=_KEYEVENTF_UNICODE)])
    _send([_key(scan=code, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP)])
    time.sleep(_KEY_DELAY_S)
