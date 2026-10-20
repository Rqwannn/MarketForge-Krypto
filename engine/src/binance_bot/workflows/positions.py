"""Menu Posisi di aplikasi: daftar short uji kertas yang terbuka dan penutupannya (Sell).

Tidak menyentuh aplikasi Binance. Penutupan juga uji kertas: posisi dicatat tertutup di harga
ask saat ini (short ditutup dengan membeli kembali), tombol tutup posisi tidak pernah ditekan.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from binance_bot.exceptions import BotError, MarketDataError, NoHistoryError
from binance_bot.filelock import exclusive
from binance_bot.market import MarketData
from binance_bot.strategy import (
    Journal,
    JournalEntry,
    PositionCloser,
    SopParams,
    close_short_now,
    live_orders_enabled,
)
from binance_bot.workflows.sop import refresh_by_price, refresh_journal

logger = logging.getLogger(__name__)

ALL = "semua"


@dataclass(frozen=True, slots=True)
class ManualClose:
    """Posisi yang sudah ditutup sendiri di bursa: harga tutup dan (opsional) hasil USDT bursa."""

    symbol: str
    exit_price: float
    pnl_usdt: float | None = None


class PositionsWorkflow:
    name = "posisi"

    def __init__(
        self,
        params: SopParams,
        journal: Journal,
        market: MarketData,
        *,
        close: str | None = None,  # None = hanya daftar, "semua", atau nama pair
        check: bool = False,  # Tebbit: baca harga dari layar sekarang (jual otomatis bila target)
        closer: PositionCloser | None = None,  # Real Fund Trading: tutup posisi di bursa
        watch_s: float = 0.0,  # >0: pantau terus (jual otomatis) sampai tidak ada posisi terbuka
        read_only: bool = False,  # hanya baca jurnal + harga (aplikasi, tiap menit): tanpa menulis
        manual: ManualClose | None = None,  # catat posisi yang sudah ditutup sendiri di bursa
        sleep: Callable[[float], None] = time.sleep,
        output: Callable[[str], None] = print,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._params = params
        self._journal = journal
        self._market = market
        self._close = close
        self._check = check
        self._closer = closer
        self._watch_s = watch_s
        self._read_only = read_only
        self._manual = manual
        self._sleep = sleep
        self._output = output
        self._wall_clock = wall_clock

    def run(self) -> None:
        if self._watch_s > 0:
            self._watch()
            return
        if self._manual is not None:
            self._record_manual(self._manual)
            return
        if self._read_only:
            entries = self._journal.load()
            self._output(
                json.dumps(
                    {
                        "warning": None,
                        "closed": [],
                        "positions": [self._open_dict(e) for e in entries if e.status == "open"],
                    },
                    default=str,
                )
            )
            return
        self._run_once()

    def _record_manual(self, manual: ManualClose) -> None:
        """Posisi sudah ditutup sendiri di bursa: catat harga tutup (dan hasil dari bursa bila ada).

        Tidak menyentuh bursa. Memakai kunci penjualan yang sama dengan bot, jadi tidak bentrok
        dengan jual otomatis yang sedang berjalan.
        """
        now = self._wall_clock()
        with exclusive(self._journal.path.with_suffix(".sell.lock")):
            entries = self._journal.load()
            index = next(
                (
                    i
                    for i, e in enumerate(entries)
                    if e.status == "open" and e.symbol == manual.symbol
                ),
                None,
            )
            if index is None:
                error = f"Tidak ada posisi terbuka untuk {manual.symbol}"
                self._output(json.dumps({"error": error, "closed": [], "positions": []}))
                return
            closed = close_short_now(
                entries[index], manual.exit_price, now, [], self._params.fee_pct
            )
            if manual.pnl_usdt is not None and closed.notional:
                # Hasil dari Riwayat Posisi bursa lebih tepat (harga masuk asli, fee, funding).
                closed = replace(
                    closed,
                    pnl_usdt=manual.pnl_usdt,
                    pnl_pct=100 * manual.pnl_usdt / closed.notional,
                )
            closed.reason = (
                f"{closed.reason}. " if closed.reason else ""
            ) + "Ditutup manual di bursa, dicatat lewat aplikasi"
            entries[index] = closed
            self._journal.save(entries)
        logger.warning(
            "Posisi %s dicatat ditutup manual di %g: %+.2f USDT (%+.2f%% modal)",
            closed.symbol,
            manual.exit_price,
            closed.pnl_usdt or 0,
            closed.pnl_capital_pct or 0,
        )
        result = {
            "warning": None,
            "closed": [self._closed_dict(closed)],
            "positions": [self._open_dict(e) for e in entries if e.status == "open"],
        }
        self._output(json.dumps(result, default=str))

    def _watch(self) -> None:
        """Pantau posisi terbuka saja (tanpa membuka posisi baru): jual otomatis saat target."""
        live = live_orders_enabled() and self._closer is not None
        while True:
            entries = (
                refresh_by_price(
                    self._journal,
                    self._market,
                    self._params.fee_pct,
                    self._wall_clock(),
                    self._closer,
                )
                if live
                else refresh_journal(
                    self._journal, self._market, self._params.fee_pct, self._wall_clock()
                )
            )
            opened = [e for e in entries if e.status == "open"]
            if not opened:
                logger.info("Tidak ada posisi terbuka lagi: pemantauan selesai")
                return
            for entry in opened:
                logger.info(
                    "Pantau %s%s: masuk %g, jual otomatis di %g",
                    entry.symbol,
                    " (uang sungguhan)" if entry.real else "",
                    entry.entry_price or 0,
                    entry.target_price or 0,
                )
            self._sleep(self._watch_s)

    def _run_once(self) -> None:
        now = self._wall_clock()
        warning = ""
        try:
            entries = refresh_journal(self._journal, self._market, self._params.fee_pct, now)
        except (
            NoHistoryError
        ):  # tanpa riwayat harga (Tebbit): harga terkini dari layar bila diminta
            if self._check:
                entries = refresh_by_price(self._journal, self._market, self._params.fee_pct, now)
            else:
                entries = self._journal.load()
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
            except BotError as exc:  # Real Fund Trading: tutup posisi di bursa gagal
                error = f"Posisi belum ditutup di bursa: {exc}"
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
                live = live_orders_enabled() and self._closer is not None
                if entry.real and not live:
                    raise BotError(
                        f"{entry.symbol} posisi sungguhan: tutup lewat Real Fund Trading"
                    )
                if live and entry.real and self._closer is not None:
                    # Posisi sungguhan: tutup dulu di bursa; gagal = posisi tetap tercatat terbuka.
                    self._closer.close_position(entry.symbol)
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
                    (
                        "Posisi ditutup di bursa (Market). "
                        if live and entry.real
                        else "[DRY RUN] Tombol tutup posisi TIDAK ditekan. "
                    )
                    + "%s ditutup di %g: %+.2f%% posisi (%+.2f%% modal)",
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
            "real": entry.real,
            "notional": entry.notional,
            "price": None,
            "price_at": None,  # kapan harga itu terbaca (detik epoch)
            "price_stale": False,  # True = harga terakhir yang tersimpan, bukan bacaan sekarang
            "pnl_pct": None,
            "pnl_capital_pct": None,
            "pnl_usdt": None,
            "to_target_pct": None,  # harga masih harus turun sekian persen sampai jual otomatis
            # Rugi terdalam sejak masuk: dari harga tertinggi yang tercatat (melawan short).
            "worst_pnl_pct": (
                self._pnl_pct(entry, entry.max_price)
                if entry.max_price and entry.entry_price
                else None
            ),
        }
        read_at: float | None = self._wall_clock()
        try:
            ask = self._market.quote(entry.symbol).ask
        except MarketDataError:
            # Tebbit: harga hanya terbaca dari layar. Pakai yang terakhir tersimpan (dibaca bot saat
            # berjalan atau tombol Cek harga) dan tandai usianya.
            if entry.last_price is None:
                return data
            ask, read_at = entry.last_price, entry.last_price_at
            data["price_stale"] = True
        pnl_pct = self._pnl_pct(entry, ask)
        data["price"] = ask
        data["price_at"] = read_at
        data["pnl_pct"] = pnl_pct
        if entry.notional:
            data["pnl_usdt"] = entry.notional * pnl_pct / 100
        if entry.notional and entry.capital_usdt:
            data["pnl_capital_pct"] = entry.notional * pnl_pct / entry.capital_usdt
        if entry.target_price and ask > 0:
            data["to_target_pct"] = max(0.0, 100 * (ask - entry.target_price) / ask)
        worst = data["worst_pnl_pct"]  # harga sekarang bisa lebih buruk dari yang sudah tercatat
        data["worst_pnl_pct"] = pnl_pct if worst is None else min(worst, pnl_pct)
        return data

    def _pnl_pct(self, entry: JournalEntry, price: float) -> float:
        """Hasil short dalam persen nilai posisi bila ditutup di `price` (setelah fee)."""
        assert entry.entry_price
        return 100 * (entry.entry_price - price) / entry.entry_price - self._params.fee_pct

    @staticmethod
    def _closed_dict(entry: JournalEntry) -> dict[str, Any]:
        return {
            "symbol": entry.symbol,
            "exit_price": entry.exit_price,
            "pnl_pct": entry.pnl_pct,
            "pnl_capital_pct": entry.pnl_capital_pct,
        }
