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
_ROW = "%-11s %-13s %-8s %-10s %-10s %-10s %-9s %-9s %s"


def _fmt(value: float | None, spec: str, suffix: str = "") -> str:
    return "-" if value is None else format(value, spec) + suffix


class JournalWorkflow:
    """Langkah 6-7 SOP: nilai uji kertas yang terbuka, lalu rekap terhadap titik impas.

    Tidak menyentuh aplikasi Binance; hanya membaca candle publik. Hasil dilaporkan dalam
    persen modal, bukan ROI aplikasi (SOP V2).
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
        now = self._wall_clock()
        entries = refresh_journal(self._journal, self._market, self._params.fee_pct, now)
        trades = [e for e in entries if e.status != "skipped"]
        logger.info("Jurnal SOP: %s", self._journal.path)
        logger.info(
            _ROW,
            "Waktu",
            "Pair",
            "Status",
            "Masuk",
            "Keluar",
            "Tertinggi",
            "Hasil",
            "% modal",
            "MA7<MA25 AI/data",
        )
        for entry in trades[-_RECENT_TRADES:]:
            logger.info(
                _ROW,
                datetime.fromtimestamp(entry.created_at).strftime("%d/%m %H:%M"),
                entry.symbol,
                entry.status,
                _fmt(entry.entry_price, ".6g"),
                _fmt(entry.exit_price, ".6g"),
                _fmt(entry.max_price, ".6g"),
                _fmt(entry.pnl_pct, "+.2f", "%"),
                _fmt(entry.pnl_capital_pct, "+.2f", "%"),
                _crosses(entry),
            )
        self._report(entries, now)

    def _report(self, entries: list[JournalEntry], now: float) -> None:
        stats = summarize(entries, self._params, now)
        logger.info(
            "Selesai %d (target %d, stop-loss %d, batas waktu %d) | terbuka %d | dilewati %d",
            stats.closed,
            stats.targets,
            stats.stops,
            stats.timeouts,
            stats.open,
            stats.skipped,
        )
        if stats.needs_review:
            logger.warning(
                "%d posisi terbuka sudah lewat %g jam: tinjau (SOP: tutup paling lambat %g jam)",
                stats.needs_review,
                self._params.review_after_h,
                self._params.max_hold_h,
            )
        win_rate = "-" if stats.win_rate is None else f"{stats.win_rate:.1%}"
        logger.info(
            "Win rate %s vs titik impas %.1f%% | hasil bersih %+.2f%% modal (%+.2f USDT)",
            win_rate,
            stats.breakeven * 100,
            stats.net_capital_pct,
            stats.net_usdt,
        )
        worst = "-" if stats.worst_against_pct is None else f"{stats.worst_against_pct:+.2f}%"
        agree, compared = stats.signal_agreement
        logger.info(
            "Harga paling jauh melawan posisi: %s | stop-loss berturut-turut: %d | "
            "AI dan data sepakat soal pola OK: %d dari %d koin",
            worst,
            stats.stop_streak,
            agree,
            compared,
        )
        logger.info("%s", stats.verdict)


def _crosses(entry: JournalEntry) -> str:
    ai = entry.pattern_ai.get("below_count") if entry.pattern_ai else None
    data = entry.pattern_data.get("below_count") if entry.pattern_data else None
    return f"{'-' if ai is None else ai}/{'-' if data is None else data}"
