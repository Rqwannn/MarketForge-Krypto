"""Menu Posisi di aplikasi: daftar short uji kertas yang terbuka dan penutupannya (Sell).

Tidak menyentuh aplikasi Binance. Penutupan juga uji kertas: posisi dicatat tertutup di harga
ask saat ini (short ditutup dengan membeli kembali), tombol tutup posisi tidak pernah ditekan.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from binance_bot.exceptions import MarketDataError, NoHistoryError
from binance_bot.market import MarketData
from binance_bot.strategy import Journal, JournalEntry, SopParams, close_short_now
from binance_bot.workflows.sop import refresh_journal

logger = logging.getLogger(__name__)

ALL = "semua"


class PositionsWorkflow:
    name = "posisi"

    def __init__(
        self,
        params: SopParams,
        journal: Journal,
        market: MarketData,
        *,
        close: str | None = None,  # None = hanya daftar, "semua", atau nama pair
        output: Callable[[str], None] = print,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._params = params
        self._journal = journal
        self._market = market
        self._close = close
        self._output = output
        self._wall_clock = wall_clock

    def run(self) -> None:
        now = self._wall_clock()
        warning = ""
        try:
            entries = refresh_journal(self._journal, self._market, self._params.fee_pct, now)
        except NoHistoryError:
            entries = self._journal.load()  # tanpa riwayat harga: tutup di harga terkini saja
        except MarketDataError as exc:
            warning = f"Harga Binance tidak bisa diambil: {exc}"
            entries = self._journal.load()
        closed: list[JournalEntry] = []
        if self._close is not None:
            if warning:
                self._output(json.dumps({"error": warning, "closed": [], "positions": []}))
                return
            try:
                entries, closed = self._close_positions(entries, now)
            except MarketDataError as exc:
                error = f"Harga tidak bisa diambil: {exc}"
                self._output(json.dumps({"error": error, "closed": [], "positions": []}))
                return
        result = {
            "warning": warning or None,
            "closed": [self._closed_dict(e) for e in closed],
            "positions": [self._open_dict(e) for e in entries if e.status == "open"],
        }
        self._output(json.dumps(result, default=str))

    def _close_positions(
        self, entries: list[JournalEntry], now: float
    ) -> tuple[list[JournalEntry], list[JournalEntry]]:
        wanted = self._close
        updated, closed = [], []
        for entry in entries:
            if entry.status == "open" and wanted in (ALL, entry.symbol):
                ask = self._market.quote(entry.symbol).ask
                try:
                    funding = self._market.funding_history(
                        entry.symbol, int(entry.created_at * 1000), int(now * 1000)
                    )
                except NoHistoryError:
                    funding = []  # bursa tanpa riwayat funding (Tebbit)
                entry = close_short_now(entry, ask, now, funding, self._params.fee_pct)
                closed.append(entry)
                logger.warning(
                    "[DRY RUN] Tombol tutup posisi TIDAK ditekan. %s ditutup (uji kertas) di %g: "
                    "%+.2f%% posisi (%+.2f%% modal)",
                    entry.symbol,
                    ask,
                    entry.pnl_pct or 0,
                    entry.pnl_capital_pct or 0,
                )
            updated.append(entry)
        if closed:
            self._journal.save(updated)
        elif wanted not in (None, ALL):
            logger.info("Tidak ada posisi terbuka untuk %s", wanted)
        return updated, closed

    def _open_dict(self, entry: JournalEntry) -> dict[str, Any]:
        data: dict[str, Any] = {
            "symbol": entry.symbol,
            "role": entry.role,
            "created_at": entry.created_at,
            "entry_price": entry.entry_price,
            "target_price": entry.target_price,
            "stop_price": entry.stop_price,
            "notional": entry.notional,
            "price": None,
            "pnl_pct": None,
            "pnl_capital_pct": None,
        }
        try:
            ask = self._market.quote(entry.symbol).ask
        except MarketDataError:
            return data
        assert entry.entry_price
        pnl_pct = 100 * (entry.entry_price - ask) / entry.entry_price - self._params.fee_pct
        data["price"] = ask
        data["pnl_pct"] = pnl_pct
        if entry.notional and entry.capital_usdt:
            data["pnl_capital_pct"] = entry.notional * pnl_pct / entry.capital_usdt
        return data

    @staticmethod
    def _closed_dict(entry: JournalEntry) -> dict[str, Any]:
        return {
            "symbol": entry.symbol,
            "exit_price": entry.exit_price,
            "pnl_pct": entry.pnl_pct,
            "pnl_capital_pct": entry.pnl_capital_pct,
        }
