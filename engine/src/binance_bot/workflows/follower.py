from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from binance_bot.binance_desktop.layout import MAX_RANK
from binance_bot.config import Settings
from binance_bot.exceptions import ConfigError, HubError
from binance_bot.hub import HubClient, SharedAnalysis
from binance_bot.strategy import JournalEntry
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.sop import SopTrader, log_top_gainers

logger = logging.getLogger(__name__)

_HUB_POLL_S = 5.0
_PLAN_WAIT_S = 60.0  # menunggu leader mencatat rencana putaran
_PLAN_FRESH_S = 600.0  # rencana lebih tua dari ini dianggap putaran lama


class FollowerWorkflow:
    """Mode banyak, laptop follower: ikut entry berdasarkan keputusan AI di laptop leader.

    Follower tidak membaca grafik sendiri. Untuk tiap Top yang ia ikuti, ia menunggu hasil leader
    untuk Top itu di putaran ini, lalu:
    - pola tidak OK (TUNGGU/JANGAN): dicatat sebagai tidak masuk, Binance tidak disentuh;
    - pola OK: membuka koin YANG SAMA dengan leader (dicari dari nama pair di daftar top gainers,
      karena peringkat bisa bergeser), lalu menjalankan sisa SOP: biaya, slot, ukuran posisi,
      kolom Jumlah, dan pintu order dry run.
    `ranks` = Top yang ditugaskan leader ke follower ini (satu atau beberapa); `ranks=None` =
    semua Top yang dimainkan leader di putaran ini (rencana putaran dari hub). Tugas dicocokkan
    dengan Top yang benar-benar dimainkan leader di putaran itu, lalu diproses berurutan sampai
    slot posisi penuh.
    Modal, ukuran posisi, dan jurnal milik laptop ini sendiri. Hasil terakhir ada di `self.result`.
    Dengan SINYAL=data, follower membaca pola sendiri dari data candle Top miliknya.
    """

    name = "follower"

    def __init__(
        self,
        settings: Settings,
        navigator: TradingNavigator,
        trader: SopTrader,
        client: HubClient | None,
        *,
        ranks: Sequence[int] | None = (1,),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._nav = navigator
        self._trader = trader
        self._client = client
        self._ranks = None if ranks is None else sorted(set(ranks))
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
        try:
            ranks = self._ranks_to_follow(uses_ai)
        except HubError as exc:
            logger.warning("Tidak masuk: %s", exc)
            return
        if not ranks:
            logger.info("Tidak ada Top yang perlu diikuti: leader tidak memainkan Top tugas ini")
            return

        handled: set[str] = set()
        for rank in ranks:
            blocker = self._trader.slot_blocker()
            if blocker:
                logger.info("Berhenti mengikuti: %s", blocker)
                break
            outcome = self._follow(rank, uses_ai, handled)
            if outcome is not None:
                self.result = outcome

    def _ranks_to_follow(self, uses_ai: bool) -> list[int]:
        if not uses_ai:
            return list(self._ranks) if self._ranks is not None else list(range(1, MAX_RANK + 1))
        planned = self._leader_ranks()
        if self._ranks is None:
            return planned
        # Tugas yang tidak dimainkan leader di putaran ini dilewati, tanpa menunggu.
        skipped = [r for r in self._ranks if r not in planned]
        if skipped:
            logger.info(
                "Top %s tidak dimainkan leader putaran ini, dilewati",
                ", ".join(str(r) for r in skipped),
            )
        return [r for r in self._ranks if r in planned]

    def _leader_ranks(self) -> list[int]:
        """Top yang dimainkan leader di putaran ini (menunggu rencana putaran yang masih baru)."""
        assert self._client is not None
        deadline = self._clock() + _PLAN_WAIT_S
        while True:
            plan = self._client.plan()
            if plan.ranks and plan.age_s <= _PLAN_FRESH_S:
                logger.info("Leader memainkan Top %s", ", ".join(str(r) for r in plan.ranks))
                return [r for r in plan.ranks if 1 <= r <= MAX_RANK]
            if self._clock() >= deadline:
                raise HubError("Leader belum memulai putaran baru; tidak ada Top untuk diikuti.")
            logger.info("Menunggu rencana putaran leader...")
            self._sleep(_HUB_POLL_S)

    def _follow(self, rank: int, uses_ai: bool, handled: set[str]) -> JournalEntry | None:
        if not uses_ai:
            self._nav.prepare()
            log_top_gainers(self._nav.open_top_gainers())
            symbol = self._nav.open_gainer(rank)
            return self._trader.trade(rank, symbol, None)

        try:
            shared = self._wait_for_leader(rank)
        except HubError as exc:
            logger.warning("Tidak masuk Top %d: %s", rank, exc)
            return None
        if shared is None:
            logger.info("Leader tidak menilai Top %d di putaran ini", rank)
            return None
        record = shared.record
        reading = record.reading
        verdict = self._trader.profile.verdict(reading.pattern, self._trader.params.min_crosses)
        logger.info(
            "Hasil leader untuk Top %d: %s, garis kuning %d kali di bawah MA%d -> %s "
            "(umur %.1f menit)",
            rank,
            record.symbol,
            reading.pattern.below_count,
            self._trader.profile.mid,
            verdict.upper(),
            shared.age_s / 60,
        )
        if record.symbol in handled:
            logger.info("%s sudah diikuti di putaran ini, dilewati", record.symbol)
            return None
        handled.add(record.symbol)
        if verdict != "ok":
            # AI di leader tidak memberi sinyal masuk: follower tidak perlu membuka Binance.
            return self._trader.skip(
                rank, record.symbol, f"pola garis kuning {verdict.upper()} (dari leader)", reading
            )

        self._nav.prepare()
        rows = self._nav.open_top_gainers()
        log_top_gainers(rows)
        now = next((row.rank for row in rows if row.symbol == record.symbol), None)
        if now is None or now > MAX_RANK:
            return self._trader.skip(
                rank,
                record.symbol,
                f"{record.symbol} sudah tidak di top {MAX_RANK} gainers saat follower masuk",
                reading,
            )
        opened = self._nav.open_gainer(now)
        if opened != record.symbol:
            return self._trader.skip(
                now,
                record.symbol,
                f"peringkat bergeser: yang terbuka {opened}, bukan {record.symbol}",
                reading,
            )
        return self._trader.trade(now, opened, lambda _symbol, _chart: reading)

    def _wait_for_leader(self, rank: int) -> SharedAnalysis | None:
        """Tunggu leader menilai Top ini; None bila leader selesai putaran tanpa menilainya."""
        assert self._client is not None
        deadline = self._clock() + self._settings.follower_wait_s
        shown = False
        while True:
            shared = self._client.by_rank(rank)
            if shared is not None and shared.age_s <= self._settings.analysis_ttl_s:
                return shared
            if not shown:  # menunggu AI pemimpin: tampilkan MarketForge selama menunggu
                self._nav.show_app(
                    f"Menunggu AI pemimpin menilai Top {rank}", rank=rank, stage="ai"
                )
                shown = True
            plan = self._client.plan()
            if plan.done and plan.age_s <= _PLAN_FRESH_S:
                return None  # leader sudah selesai putaran ini dan tidak menilai Top ini
            if self._clock() >= deadline:
                raise HubError(
                    f"Leader belum menilai Top {rank} setelah "
                    f"{self._settings.follower_wait_s:.0f} detik. Pastikan leader memantau Top ini."
                )
            logger.info("Menunggu leader menganalisis Top %d...", rank)
            self._sleep(_HUB_POLL_S)
