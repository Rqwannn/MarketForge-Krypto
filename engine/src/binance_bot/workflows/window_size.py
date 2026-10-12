import logging

from binance_bot.binance_desktop import layout
from binance_bot.config import Settings
from binance_bot.macos import WindowController, wait_for_window

logger = logging.getLogger(__name__)


class WindowSizeWorkflow:
    """Cek (dan di Windows, atur) ukuran jendela Binance terhadap ukuran kalibrasi layout."""

    name = "window-size"

    def __init__(self, settings: Settings, window: WindowController, *, resize: bool) -> None:
        self._settings = settings
        self._window = window
        self._resize = resize

    def run(self) -> None:
        want_w, want_h = layout.EXPECTED_WINDOW
        if self._resize:
            maximizer = getattr(self._window, "maximize", None)
            resizer = getattr(self._window, "resize", None)
            if layout.WINDOW_MAXIMIZED and maximizer is not None:
                maximizer(self._settings.app_name)
            elif resizer is not None:
                resizer(self._settings.app_name, want_w, want_h)
            else:
                logger.warning("Pengaturan ukuran otomatis hanya tersedia di Windows")
        rect = wait_for_window(
            self._window,
            self._settings.app_name,
            timeout_s=self._settings.launch_timeout_s,
            interval_s=self._settings.poll_interval_s,
        )
        tol = layout.WINDOW_TOLERANCE
        ok = abs(rect.width - want_w) <= want_w * tol and abs(rect.height - want_h) <= want_h * tol
        logger.info(
            "Jendela Binance: %dx%d (harus %dx%d): %s",
            rect.width,
            rect.height,
            want_w,
            want_h,
            "OK" if ok else "BERBEDA, sesuaikan ukuran jendela (atau jalankan dengan --atur)",
        )
