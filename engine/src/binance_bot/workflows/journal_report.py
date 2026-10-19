from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from binance_bot.exceptions import BotError, MarketDataError
from binance_bot.market import MarketData
from binance_bot.strategy import Journal, JournalEntry, SopParams, summarize
from binance_bot.strategy.params import REQUIRED_TEST_TRADES
from binance_bot.workflows.sop import chart_of, decision_fields, refresh_journal

logger = logging.getLogger(__name__)

_RECENT_TRADES = 20
_RECENT_ANALYSES = 30
_RANGE_TRADES = 500  # dengan filter tanggal, semua trade dalam rentang tampil (dibatasi wajar)
_RANGE_ANALYSES = 500
_ROW = "%-11s %-13s %-8s %-10s %-10s %-10s %-9s %-9s %s"


def day_bounds(dari: str | None, sampai: str | None) -> tuple[float | None, float | None]:
    """Rentang tanggal (YYYY-MM-DD, zona waktu laptop, kedua ujung termasuk) -> detik epoch.

    Nilai pertama = awal hari `dari`; nilai kedua = awal hari setelah `sampai` (batas eksklusif).
    """

    def parse(text: str, label: str) -> datetime:
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise BotError(f"Tanggal {label} harus berbentuk YYYY-MM-DD, bukan {text!r}") from None

    start = parse(dari, "awal").timestamp() if dari else None
    end = (parse(sampai, "akhir") + timedelta(days=1)).timestamp() if sampai else None
    if start is not None and end is not None and start >= end:
        raise BotError("Tanggal awal tidak boleh setelah tanggal akhir")
    return start, end


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
        market: MarketData,
        *,
        as_json: bool = False,
        since: float | None = None,  # filter waktu masuk posisi: dari (termasuk)
        until: float | None = None,  # sampai (tidak termasuk)
        output: Callable[[str], None] = print,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._since = since
        self._until = until
        self._params = params
        self._journal = journal
        self._market = market
        self._as_json = as_json
        self._output = output
        self._wall_clock = wall_clock

    def run(self) -> None:
        now = self._wall_clock()
        warning = ""
        try:
            entries = refresh_journal(self._journal, self._market, self._params.fee_pct, now)
        except MarketDataError as exc:
            # Rekap tetap bisa dibuat dari jurnal; posisi terbuka saja yang belum dinilai ulang.
            warning = f"Posisi terbuka belum dinilai ulang: {exc}"
            logger.warning("%s", warning)
            entries = self._journal.load()
        entries = self._in_range(entries)
        trades = [e for e in entries if e.status not in ("skipped", "contoh")]
        if self._as_json:
            self._output(json.dumps(self._as_dict(entries, trades, now, warning), default=str))
            return
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

    def _in_range(self, entries: list[JournalEntry]) -> list[JournalEntry]:
        """Saring semua rekap (angka, grafik, tabel, analisis) menurut waktu masuk posisi."""
        return [
            e
            for e in entries
            if (self._since is None or e.created_at >= self._since)
            and (self._until is None or e.created_at < self._until)
        ]

    @property
    def _filtered(self) -> bool:
        return self._since is not None or self._until is not None

    def _as_dict(
        self, entries: list[JournalEntry], trades: list[JournalEntry], now: float, warning: str
    ) -> dict[str, Any]:
        stats = summarize(entries, self._params, now)
        trade_limit = _RANGE_TRADES if self._filtered else _RECENT_TRADES
        analysis_limit = _RANGE_ANALYSES if self._filtered else _RECENT_ANALYSES
        return {
            "range": {"since": self._since, "until": self._until},
            "path": str(self._journal.path),
            "warning": warning or None,
            "stats": {
                **asdict(stats),
                "verdict": stats.verdict,
                "required_trades": REQUIRED_TEST_TRADES,
            },
            "trades": [
                {**e.to_dict(), "pnl_capital_pct": e.pnl_capital_pct} for e in trades[-trade_limit:]
            ],
            # Riwayat setiap koin yang dinilai (termasuk yang dilewati) untuk aplikasi.
            "analyses": [
                _analysis(e, self._params) for e in entries[-analysis_limit:] if e.verdict
            ],
        }

    def _report(self, entries: list[JournalEntry], now: float) -> None:
        stats = summarize(entries, self._params, now)
        logger.info(
            "Selesai %d (target %d, likuidasi %d, tutup manual %d) | terbuka %d | dilewati %d",
            stats.closed,
            stats.targets,
            stats.liquidations,
            stats.manual,
            stats.open,
            stats.skipped,
        )
        if stats.needs_review:
            logger.warning(
                "%d posisi terbuka sudah lewat %g jam: tinjau bersama beliau (tanpa batas waktu)",
                stats.needs_review,
                self._params.review_after_h,
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
            "Harga paling jauh melawan posisi: %s | AI dan data sepakat soal pola OK: %d dari %d",
            worst,
            agree,
            compared,
        )
        logger.info("%s", stats.verdict)


def _crosses(entry: JournalEntry) -> str:
    ai = entry.pattern_ai.get("below_count") if entry.pattern_ai else None
    data = entry.pattern_data.get("below_count") if entry.pattern_data else None
    return f"{'-' if ai is None else ai}/{'-' if data is None else data}"


def _analysis(entry: JournalEntry, params: SopParams) -> dict[str, Any]:
    ai = entry.pattern_ai or {}
    return {
        **decision_fields(entry, params),
        "real": entry.real,
        "entry_price": entry.entry_price,
        "target_price": entry.target_price,
        "id": entry.id,
        "created_at": entry.created_at,
        "symbol": entry.symbol,
        "rank": entry.rank,
        "role": entry.role,
        "status": entry.status,
        "verdict": entry.verdict,
        "count_ai": ai.get("below_count"),
        "summary": entry.ai_summary,
        "reason": entry.reason,
        "chart": chart_of(entry),
        # Dinilai sebelum ada syarat "6 jam terakhir": statusnya bisa beda dengan aturan sekarang.
        "old_rule": bool(ai) and "below_recent" not in ai,
    }
