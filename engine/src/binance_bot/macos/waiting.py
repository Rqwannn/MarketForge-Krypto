from __future__ import annotations

import time
from collections.abc import Callable

from binance_bot.exceptions import AppTimeoutError, WindowError
from binance_bot.macos.app_controller import AppController
from binance_bot.macos.window import Rect, WindowController


def wait_until_frontmost(
    controller: AppController,
    bundle_id: str,
    *,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Tunggu sampai aplikasi menjadi jendela aktif, atau lempar `AppTimeoutError`."""
    deadline = clock() + timeout_s
    while clock() < deadline:
        if (controller.frontmost_bundle_id() or "").casefold() == bundle_id.casefold():
            return
        sleep(interval_s)
    raise AppTimeoutError(f"{bundle_id} tidak menjadi jendela aktif dalam {timeout_s:g} detik")


def wait_for_window(
    window: WindowController,
    app_name: str,
    *,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Rect:
    """Tunggu jendela aplikasi muncul (ia belum ada sesaat setelah dibawa ke depan).

    Kalau sampai batas waktu tetap gagal, error terakhir dilempar ulang
    (mis. karena izin Accessibility belum diberikan).
    """
    deadline = clock() + timeout_s
    while True:
        try:
            return window.bounds(app_name)
        except WindowError:
            if clock() >= deadline:
                raise
            sleep(interval_s)
