"""Cek izin privasi macOS tanpa memunculkan dialog izin."""

from __future__ import annotations

import ctypes
import ctypes.util

import Quartz


def screen_capture_allowed() -> bool:
    """Izin "Screen & System Audio Recording" (untuk screenshot dan OCR)."""
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def accessibility_allowed() -> bool:
    """Izin "Accessibility" (untuk klik, gulir, dan mengetik)."""
    path = ctypes.util.find_library("ApplicationServices")
    if path is None:
        return False
    services = ctypes.cdll.LoadLibrary(path)
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(services.AXIsProcessTrusted())
