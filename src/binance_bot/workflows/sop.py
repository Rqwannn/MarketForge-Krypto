"""Inti SOP "Short Top Gainers (Futures 1x)" untuk satu koin yang halaman trade-nya terbuka.

Dipakai bersama oleh mode single (AI sendiri) dan follower (AI dari hub leader). Urutan:
saringan gratis dulu (naik >= 30%, funding, spread), baru tanda pucuk (AI atau data), lalu
ukuran posisi, isi kolom Jumlah, dan pintu order yang DIMATIKAN. Semua tercatat di jurnal.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from binance_bot.analysis import PeakReading
from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.binance_desktop.screen_text import GainerRow
from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.market import FuturesMarket
from binance_bot.strategy import (
    DryRunOrderGate,
    Journal,
    JournalEntry,
    OrderPlan,
    SopParams,
    data_peak_signs,
    evaluate_open_trades,
    size_position,
    stop_streak,
)

logger = logging.getLogger(__name__)

# Mengambil hasil AI tanda pucuk untuk (pair, screenshot grafik 15 menit).
ReadingSource = Callable[[str, Path], PeakReading]

_CHART_CANDLES = 40


class _Skip(Exception):
    """Koin gugur di salah satu saringan SOP; pesan = alasannya."""


def log_top_gainers(rows: list[GainerRow]) -> None:
    logger.info(
        "Top gainers Futures: %s",
        ", ".join(f"#{r.rank} {r.symbol} {r.change_pct:+.2f}%" for r in rows) or "-",
    )


def refresh_journal(
    journal: Journal, market: FuturesMarket, fee_pct: float, now_s: float
) -> list[JournalEntry]:
    """Langkah 6 SOP: nilai posisi uji yang masih terbuka dari candle sungguhan."""
    entries = journal.load()
    updated = evaluate_open_trades(entries, market, now_s, fee_pct)
    closed_now = [new for old, new in zip(entries, updated, strict=True) if old != new]
    for entry in closed_now:
        logger.info(
            "Uji kertas %s selesai: %s, hasil bersih %+.2f%% (%+.2f USDT)",
            entry.symbol,
            entry.status,
            entry.pnl_pct or 0,
            entry.pnl_usdt or 0,
        )
    if closed_now:
        journal.save(updated)
    return updated


class SopTrader:
    def __init__(
        self,
        settings: Settings,
        params: SopParams,
        navigator: BinanceNavigator,
        market: FuturesMarket,
        journal: Journal,
        gate: DryRunOrderGate,
        *,
        fill_form: bool = True,
        wall_clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        params.validate()
        self.params = params
        self._settings = settings
        self._nav = navigator
        self._market = market
        self._journal = journal
        self._gate = gate
        self._fill_form = fill_form
        self._wall_clock = wall_clock
        self._now = now

    def refresh_journal(self) -> list[JournalEntry]:
        return refresh_journal(self._journal, self._market, self.params.fee_pct, self._wall_clock())

    def halted(self, entries: list[JournalEntry]) -> bool:
        """SOP: setelah 3 stop-loss berturut-turut, berhenti hari itu dan tinjau jurnal."""
        today = self._now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        streak = stop_streak(entries, since_s=today)
        if streak >= self.params.max_stop_streak:
            logger.error(
                "%d stop-loss berturut-turut hari ini. Sesuai SOP: berhenti dan tinjau jurnal.",
                streak,
            )
            return True
        return False

    def trade(self, rank: int, symbol: str, reading_source: ReadingSource | None) -> JournalEntry:
        """Jalankan langkah 1-5 SOP untuk pair yang halaman trade-nya sedang terbuka."""
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_{symbol}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
        )
        try:
            self._run(entry, reading_source)
        except (_Skip, BotError) as exc:
            entry.status = "skipped"
            entry.reason = str(exc)
            logger.info("#%d %s dilewati: %s", rank, symbol, exc)
        self._journal.append(entry)
        return entry

    def _run(self, entry: JournalEntry, reading_source: ReadingSource | None) -> None:
        params, symbol = self.params, entry.symbol
        open_symbols = {e.symbol for e in self._journal.load() if e.status == "open"}
        if symbol in open_symbols:
            raise _Skip("sudah ada posisi uji yang masih terbuka untuk pair ini")
        if not symbol.endswith("USDT"):
            raise _Skip("bukan pair USDT")

        # Saringan 1 dan 3 (gratis, sebelum AI): naik minimal, funding, spread.
        quote = self._market.quote(symbol)
        entry.change_pct = quote.change_pct
        entry.funding_rate = quote.funding_rate
        entry.spread_pct = quote.spread_pct
        if quote.change_pct < params.min_gain_pct:
            raise _Skip(f"naik {quote.change_pct:.1f}% < {params.min_gain_pct:g}% dalam 24 jam")
        if quote.funding_rate * 100 < params.min_funding_pct:
            raise _Skip(f"funding {quote.funding_rate * 100:.4f}% terlalu negatif (short membayar)")
        if quote.spread_pct > params.max_spread_pct:
            raise _Skip(f"spread {quote.spread_pct:.3f}% > {params.max_spread_pct:g}%")

        # Saringan 2: tanda pucuk di chart 15 menit.
        self._nav.show_15m_chart()
        name = f"{entry.id}_rank{entry.rank}"
        shots = self._settings.screenshot_dir
        entry.screenshots.append(str(self._nav.capture_window(shots / f"{name}.png")))
        chart = self._nav.capture_chart(shots / f"{name}_15m.png")
        entry.screenshots.append(str(chart))

        data = data_peak_signs(self._market.klines(symbol, "15m", limit=_CHART_CANDLES))
        entry.signs_data = data.as_dict()
        decisive = data
        if params.signal_source == "ai":
            if reading_source is None:
                raise _Skip("SINYAL=ai tetapi tidak ada sumber analisis AI")
            reading = reading_source(symbol, chart)
            entry.signs_ai = reading.signs.as_dict()
            entry.ai_summary = reading.summary
            decisive = reading.signs
        logger.info(
            "#%d %s tanda pucuk %s: %d/4 (data: %d/4)%s",
            entry.rank,
            symbol,
            params.signal_source.upper(),
            decisive.count,
            data.count,
            f" | {entry.ai_summary}" if entry.ai_summary else "",
        )
        if decisive.count < params.min_signs:
            raise _Skip(f"tanda pucuk {decisive.count}/4, butuh {params.min_signs}")

        # Langkah 4: ukuran posisi.
        rules = self._market.rules(symbol)
        price = quote.bid  # short menjual ke harga bid
        sizing = size_position(params, price, rules, self._settings.decimal_separator)
        if isinstance(sizing, str):
            raise _Skip(sizing)

        margin = self._nav.read_margin_settings()
        entry.margin = margin.describe()
        if not margin.is_sop_compliant:
            logger.warning(
                "Margin %s: SOP mewajibkan Isolated 1x. Wajib diubah sebelum order sungguhan.",
                entry.margin,
            )

        # Langkah 5: isi form lalu pintu order (dimatikan).
        if self._fill_form:
            self._nav.fill_quantity(sizing.quantity_text)
        plan = OrderPlan(
            symbol=symbol,
            quantity_text=sizing.quantity_text,
            notional=sizing.notional,
            entry_price=price,
            target_price=price * (1 - params.target_pct / 100),
            stop_price=price * (1 + params.stop_pct / 100),
        )
        self._gate.submit(plan)

        entry.status = "open"
        entry.entry_price = plan.entry_price
        entry.quantity = sizing.quantity
        entry.notional = sizing.notional
        entry.target_price = plan.target_price
        entry.stop_price = plan.stop_price
        entry.deadline = entry.created_at + params.max_hold_h * 3600
        logger.info(
            "#%d %s MASUK UJI KERTAS: short %s @ %g | target %g | stop-loss %g | tutup paling "
            "lambat %s",
            entry.rank,
            symbol,
            sizing.quantity_text,
            price,
            plan.target_price,
            plan.stop_price,
            datetime.fromtimestamp(entry.deadline).strftime("%H:%M"),
        )
