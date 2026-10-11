from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime

from binance_bot.market import FuturesMarket
from binance_bot.strategy import Journal, JournalEntry, SopParams, summarize
from binance_bot.workflows.sop import refresh_journal

logger = logging.getLogger(__name__)

_RECENT_TRADES = 20


def _fmt(value: float | None, spec: str) -> str:
    return "-" if value is None else format(value, spec)


class JournalWorkflow:
    """Langkah 6-7 SOP: nilai uji kertas yang terbuka, lalu rekap terhadap titik impas.

    Tidak menyentuh aplikasi Binance; hanya membaca candle publik.
    """

    name = "jurnal"

    def __init__(
        self,
        params: SopParams,
        journal: Journal,
        market: FuturesMarket,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._params = params
        self._journal = journal
        self._market = market
        self._wall_clock = wall_clock

    def run(self) -> None:
        entries = refresh_journal(
            self._journal, self._market, self._params.fee_pct, self._wall_clock()
        )
        trades = [e for e in entries if e.status != "skipped"]
        logger.info("Jurnal SOP: %s", self._journal.path)
        logger.info(
            "%-11s %-14s %-8s %-11s %-11s %-9s %s",
            "Waktu",
            "Pair",
            "Status",
            "Masuk",
            "Keluar",
            "Hasil",
            "Tanda AI/data",
        )
        for entry in trades[-_RECENT_TRADES:]:
            logger.info(
                "%-11s %-14s %-8s %-11s %-11s %-9s %s",
                datetime.fromtimestamp(entry.created_at).strftime("%d/%m %H:%M"),
                entry.symbol,
                entry.status,
                _fmt(entry.entry_price, ".6g"),
                _fmt(entry.exit_price, ".6g"),
                _fmt(entry.pnl_pct, "+.2f") + ("%" if entry.pnl_pct is not None else ""),
                _signs(entry),
            )
        self._report(entries)

    def _report(self, entries: list[JournalEntry]) -> None:
        stats = summarize(entries, self._params)
        logger.info(
            "Selesai %d (target %d, stop-loss %d, batas waktu %d) | terbuka %d | dilewati %d",
            stats.closed,
            stats.targets,
            stats.stops,
            stats.timeouts,
            stats.open,
            stats.skipped,
        )
        win_rate = "-" if stats.win_rate is None else f"{stats.win_rate:.1%}"
        logger.info(
            "Win rate %s vs titik impas %.1f%% | hasil bersih %+.2f%% (%+.2f USDT)",
            win_rate,
            stats.breakeven * 100,
            stats.net_pct,
            stats.net_usdt,
        )
        agree, compared = stats.signal_agreement
        logger.info(
            "Stop-loss berturut-turut: %d | AI dan data sepakat: %d dari %d koin",
            stats.stop_streak,
            agree,
            compared,
        )
        logger.info("%s", stats.verdict)


def _signs(entry: JournalEntry) -> str:
    ai = sum(entry.signs_ai.values()) if entry.signs_ai else None
    data = sum(entry.signs_data.values()) if entry.signs_data else None
    return f"{'-' if ai is None else ai}/{'-' if data is None else data}"
