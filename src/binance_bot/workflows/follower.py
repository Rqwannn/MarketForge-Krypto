from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from binance_bot.analysis import PeakReading
from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.config import Settings
from binance_bot.exceptions import ConfigError, HubError
from binance_bot.hub import HubClient, SharedAnalysis
from binance_bot.strategy import JournalEntry
from binance_bot.workflows.sop import SopTrader, log_top_gainers

logger = logging.getLogger(__name__)

_HUB_POLL_S = 5.0


class FollowerWorkflow:
    """Mode banyak, laptop follower: SOP penuh dengan hasil AI dari hub (tanpa biaya AI).

    Hasil dicocokkan berdasarkan pair, karena peringkat bisa bergeser antara saat leader
    menganalisis dan saat follower membuka koin. Modal, ukuran posisi, dan jurnal milik
    laptop ini sendiri. Hasil terakhir ada di `self.result`.
    """

    name = "follower"

    def __init__(
        self,
        settings: Settings,
        navigator: BinanceNavigator,
        trader: SopTrader,
        client: HubClient | None,
        *,
        rank: int = 1,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._nav = navigator
        self._trader = trader
        self._client = client
        self._rank = rank
        self._sleep = sleep
        self._clock = clock
        self.result: JournalEntry | None = None

    def run(self) -> None:
        uses_ai = self._trader.params.signal_source == "ai"
        if uses_ai:
            if self._client is None:
                raise ConfigError("SINYAL=ai butuh hub leader: isi --hub atau BOT_HUB_URL")
            # Cek hub dulu: jika tidak bisa dihubungi, jangan buang waktu menavigasi Binance.
            available = self._client.list()
            logger.info(
                "Hub punya %d hasil: %s",
                len(available),
                ", ".join(f"#{s.record.rank} {s.record.symbol}" for s in available) or "-",
            )
        if self._trader.halted(self._trader.refresh_journal()):
            return

        self._nav.prepare()
        log_top_gainers(self._nav.open_top_gainers())
        symbol = self._nav.open_gainer(self._rank)
        self.result = self._trader.trade(self._rank, symbol, self._from_hub if uses_ai else None)

    def _from_hub(self, symbol: str, _chart: Path) -> PeakReading:
        shared = self._wait_for(symbol)
        if shared.age_s > self._settings.analysis_ttl_s:
            logger.warning(
                "Analisis %s sudah %.0f menit; leader mungkin berhenti memperbarui",
                symbol,
                shared.age_s / 60,
            )
        logger.info("Hasil AI dari hub untuk %s (umur %.1f menit)", symbol, shared.age_s / 60)
        return shared.record.reading

    def _wait_for(self, symbol: str) -> SharedAnalysis:
        assert self._client is not None
        deadline = self._clock() + self._settings.follower_wait_s
        while True:
            shared = self._client.get(symbol)
            if shared is not None:
                return shared
            if self._clock() >= deadline:
                raise HubError(
                    f"Hub belum punya analisis untuk {symbol} setelah "
                    f"{self._settings.follower_wait_s:.0f} detik. Peringkat mungkin berubah: "
                    "pastikan leader menganalisis rank ini."
                )
            logger.info("Menunggu leader menganalisis %s...", symbol)
            self._sleep(_HUB_POLL_S)
