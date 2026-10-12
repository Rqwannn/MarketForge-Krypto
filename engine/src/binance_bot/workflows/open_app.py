from __future__ import annotations

import logging
import time
from collections.abc import Callable

from binance_bot.config import Settings
from binance_bot.macos import AppController, wait_until_frontmost

logger = logging.getLogger(__name__)


class OpenBinanceWorkflow:
    """Membuka aplikasi Binance hanya jika belum berjalan, supaya sesi login tidak terganggu."""

    name = "open"

    def __init__(
        self,
        settings: Settings,
        controller: AppController,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._controller = controller
        self._sleep = sleep
        self._clock = clock

    def run(self) -> None:
        bundle_id = self._settings.app_bundle_id
        app = self._settings.app_name

        if self._controller.is_running(bundle_id):
            logger.info("%s sudah berjalan, tidak dibuka ulang (sesi login dibiarkan)", app)
            return

        logger.info("%s belum berjalan, diluncurkan", app)
        self._controller.launch(bundle_id)
        wait_until_frontmost(
            self._controller,
            bundle_id,
            timeout_s=self._settings.launch_timeout_s,
            interval_s=self._settings.poll_interval_s,
            sleep=self._sleep,
            clock=self._clock,
        )
        logger.warning(
            "%s baru dibuka. Aplikasi tidak menyimpan sesi, login manual diperlukan", app
        )
