from __future__ import annotations

import logging
import time
from collections.abc import Callable

from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.binance_desktop.layout import MAX_RANK
from binance_bot.config import Settings
from binance_bot.exceptions import ConfigError, HubError
from binance_bot.hub import HubClient, SharedAnalysis
from binance_bot.strategy import JournalEntry
from binance_bot.workflows.sop import SopTrader, log_top_gainers

logger = logging.getLogger(__name__)

_HUB_POLL_S = 5.0


class FollowerWorkflow:
    """Mode banyak, laptop follower: ikut entry berdasarkan keputusan Haiku di laptop leader.

    Follower tidak membaca grafik sendiri. Ia menunggu hasil leader untuk Top yang ditugaskan
    di putaran ini, lalu:
    - pola tidak OK (TUNGGU/JANGAN): dicatat sebagai tidak masuk, Binance tidak disentuh;
    - pola OK: membuka koin YANG SAMA dengan leader (dicari dari nama pair di daftar top gainers,
      karena peringkat bisa bergeser), lalu menjalankan sisa SOP: biaya, slot, ukuran posisi,
      kolom Jumlah, dan pintu order dry run.
    Modal, ukuran posisi, dan jurnal milik laptop ini sendiri. Hasil terakhir ada di `self.result`.
    Dengan SINYAL=data, follower membaca pola sendiri dari data candle Top miliknya.
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
        if uses_ai and self._client is None:
            raise ConfigError("SINYAL=ai butuh hub leader: isi --hub atau BOT_HUB_URL")
        if self._trader.halted(self._trader.refresh_journal()):
            return
        blocker = self._trader.slot_blocker()
        if blocker:
            logger.info("Tidak masuk: %s", blocker)
            return
        if not uses_ai:
            self._nav.prepare()
            log_top_gainers(self._nav.open_top_gainers())
            symbol = self._nav.open_gainer(self._rank)
            self.result = self._trader.trade(self._rank, symbol, None)
            return

        try:
            shared = self._wait_for_leader()
        except HubError as exc:
            logger.warning("Tidak masuk: %s", exc)
            return
        record = shared.record
        reading = record.reading
        verdict = reading.pattern.verdict(self._trader.params.min_crosses)
        logger.info(
            "Hasil leader untuk Top %d: %s, garis kuning %d kali di bawah MA25 -> %s "
            "(umur %.1f menit)",
            self._rank,
            record.symbol,
            reading.pattern.below_count,
            verdict.upper(),
            shared.age_s / 60,
        )
        if verdict != "ok":
            # Haiku di leader tidak memberi sinyal masuk: follower tidak perlu membuka Binance.
            self.result = self._trader.skip(
                self._rank,
                record.symbol,
                f"pola garis kuning {verdict.upper()} (dari leader)",
                reading,
            )
            return

        self._nav.prepare()
        rows = self._nav.open_top_gainers()
        log_top_gainers(rows)
        now = next((row.rank for row in rows if row.symbol == record.symbol), None)
        if now is None or now > MAX_RANK:
            self.result = self._trader.skip(
                self._rank,
                record.symbol,
                f"{record.symbol} sudah tidak di top {MAX_RANK} gainers saat follower masuk",
                reading,
            )
            return
        opened = self._nav.open_gainer(now)
        if opened != record.symbol:
            self.result = self._trader.skip(
                now,
                record.symbol,
                f"peringkat bergeser: yang terbuka {opened}, bukan {record.symbol}",
                reading,
            )
            return
        self.result = self._trader.trade(now, opened, lambda _symbol, _chart: reading)

    def _wait_for_leader(self) -> SharedAnalysis:
        """Tunggu leader selesai menilai Top milik follower ini di putaran ini."""
        assert self._client is not None
        deadline = self._clock() + self._settings.follower_wait_s
        while True:
            shared = self._client.by_rank(self._rank)
            if shared is not None and shared.age_s <= self._settings.analysis_ttl_s:
                return shared
            if self._clock() >= deadline:
                raise HubError(
                    f"Leader belum menilai Top {self._rank} setelah "
                    f"{self._settings.follower_wait_s:.0f} detik. Pastikan leader memantau Top ini."
                )
            logger.info("Menunggu leader menganalisis Top %d...", self._rank)
            self._sleep(_HUB_POLL_S)
