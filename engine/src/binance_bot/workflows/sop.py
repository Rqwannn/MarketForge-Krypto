"""Inti SOP V2 "Short Top Gainers (Futures 2x)" untuk satu koin yang halaman trade-nya terbuka.

Dipakai bersama oleh mode single (AI sendiri) dan follower (AI dari hub leader). Urutan:
cek slot (maks 2 posisi; koin kedua hanya bila koin pertama tidak rugi), saringan gratis
(funding, spread, kenaikan minimal bila diisi), pola garis kuning MA7 (AI atau data), ukuran
posisi (margin 50% x 2x), isi kolom Jumlah, lalu pintu order yang DIMATIKAN. Semua dicatat.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from binance_bot.analysis import PatternReading
from binance_bot.binance_desktop.screen_text import GainerRow
from binance_bot.config import Settings
from binance_bot.exceptions import BotError, MarketDataError
from binance_bot.logging_setup import event
from binance_bot.market import MarketData
from binance_bot.strategy import (
    DryRunOrderGate,
    Journal,
    JournalEntry,
    MaPattern,
    OrderPlan,
    SopParams,
    candles_needed,
    data_ma_pattern,
    evaluate_open_trades,
    size_position,
    stop_streak,
)
from binance_bot.workflows.base import TradingNavigator

logger = logging.getLogger(__name__)

# Mengambil hasil AI pola garis kuning untuk (pair, screenshot grafik 15 menit).
ReadingSource = Callable[[str, Path], PatternReading]

_VERDICT_TEXT = {
    "jangan": "JANGAN (garis kuning selalu di atas)",
    "tunggu": "TUNGGU (baru sekali di bawah)",
    "ok": "OK (berkali-kali di bawah)",
}


def coin_event(entry: JournalEntry) -> dict[str, dict[str, Any]]:
    """Hasil penilaian satu koin untuk aplikasi desktop (lihat logging_setup.event)."""
    ai = entry.pattern_ai or {}
    data = entry.pattern_data or {}
    return event(
        "coin",
        rank=entry.rank,
        symbol=entry.symbol,
        status=entry.status,
        verdict=entry.verdict,
        count_ai=ai.get("below_count"),
        count_data=data.get("below_count"),
        summary=entry.ai_summary,
        reason=entry.reason,
        entry_price=entry.entry_price,
        target_price=entry.target_price,
        stop_price=entry.stop_price,
        chart=chart_of(entry),
    )


def chart_of(entry: JournalEntry) -> str | None:
    """Screenshot grafik 15 menit yang dibaca AI (yang terakhir diambil), bila ada."""
    return next((s for s in reversed(entry.screenshots) if s.endswith("_15m.png")), None)


class _Skip(Exception):
    """Koin gugur di salah satu saringan SOP; pesan = alasannya."""


def log_top_gainers(rows: Sequence[GainerRow]) -> None:
    logger.info(
        "Top gainers Futures: %s",
        ", ".join(f"#{r.rank} {r.symbol} {r.change_pct:+.2f}%" for r in rows) or "-",
    )


def refresh_journal(
    journal: Journal, market: MarketData, fee_pct: float, now_s: float
) -> list[JournalEntry]:
    """Langkah 6 SOP: nilai posisi uji yang masih terbuka dari candle sungguhan."""
    entries = journal.load()
    updated = evaluate_open_trades(entries, market, now_s, fee_pct)
    changed = [new for old, new in zip(entries, updated, strict=True) if old != new]
    for entry in changed:
        if entry.is_closed:
            logger.info(
                "Uji kertas %s selesai: %s, hasil %+.2f%% posisi (%+.2f USDT = %+.2f%% modal)",
                entry.symbol,
                entry.status,
                entry.pnl_pct or 0,
                entry.pnl_usdt or 0,
                entry.pnl_capital_pct or 0,
            )
    if changed:
        journal.save(updated)
    return updated


class SopTrader:
    def __init__(
        self,
        settings: Settings,
        params: SopParams,
        navigator: TradingNavigator,
        market: MarketData,
        journal: Journal,
        gate: DryRunOrderGate,
        *,
        fill_form: bool = True,
        role: str = "single",
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
        self._role = role
        self._wall_clock = wall_clock
        self._now = now

    def refresh_journal(self) -> list[JournalEntry]:
        try:
            return refresh_journal(
                self._journal, self._market, self.params.fee_pct, self._wall_clock()
            )
        except MarketDataError as exc:  # bursa tanpa sumber candle (Tebbit): posisi tetap terbuka
            logger.warning("Posisi uji belum bisa dinilai: %s", exc)
            return self._journal.load()

    def halted(self, entries: list[JournalEntry]) -> bool:
        """SOP: setelah 3 stop-loss berturut-turut, berhenti hari itu dan tinjau catatan."""
        today = self._now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        streak = stop_streak(entries, since_s=today)
        if streak >= self.params.max_stop_streak:
            logger.error(
                "%d stop-loss berturut-turut hari ini. Sesuai SOP: berhenti dan tinjau catatan.",
                streak,
            )
            return True
        return False

    def slot_blocker(self) -> str | None:
        """Langkah 4 SOP: posisi terbuka < maks; koin kedua hanya bila yang pertama tidak rugi."""
        opened = [e for e in self._journal.load() if e.status == "open"]
        if len(opened) >= self.params.max_open_positions:
            return f"sudah {len(opened)} posisi terbuka (maksimal {self.params.max_open_positions})"
        for entry in opened:
            assert entry.entry_price is not None
            # Short rugi bila harga naik di atas harga masuk. Dibandingkan dengan sisi harga yang
            # sama saat masuk (bid), supaya spread sesaat setelah masuk tidak dihitung sebagai rugi.
            try:
                price = self._market.quote(entry.symbol).bid
            except MarketDataError as exc:
                return f"harga {entry.symbol} tidak terbaca ({exc}); koin berikutnya ditahan"
            if price > entry.entry_price:
                return (
                    f"posisi {entry.symbol} sedang rugi ({price:g} > masuk {entry.entry_price:g}); "
                    "koin berikutnya belum boleh dibuka"
                )
        return None

    def trade(self, rank: int, symbol: str, reading_source: ReadingSource | None) -> JournalEntry:
        """Jalankan langkah 2-5 SOP untuk pair yang halaman trade-nya sedang terbuka."""
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_{symbol}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
            capital_usdt=self.params.capital_usdt,
            leverage=self.params.leverage,
            role=self._role,
        )
        try:
            self._run(entry, reading_source)
        except (_Skip, BotError) as exc:
            entry.status = "skipped"
            entry.reason = str(exc)
        return self._finish(entry)

    def skip(
        self, rank: int, symbol: str, reason: str, reading: PatternReading | None = None
    ) -> JournalEntry:
        """Catat koin yang tidak dimasuki tanpa membuka aplikasi (mis. pola leader tidak OK)."""
        entry = JournalEntry(
            id=f"{self._now():%Y%m%d_%H%M%S}_{symbol}",
            created_at=self._wall_clock(),
            symbol=symbol,
            rank=rank,
            status="skipped",
            reason=reason,
            capital_usdt=self.params.capital_usdt,
            leverage=self.params.leverage,
            role=self._role,
        )
        if reading is not None:
            entry.pattern_ai = reading.pattern.as_dict()
            entry.ai_summary = reading.summary
            entry.verdict = reading.pattern.verdict(self.params.min_crosses)
        return self._finish(entry)

    def _finish(self, entry: JournalEntry) -> JournalEntry:
        rank, symbol = entry.rank, entry.symbol
        self._journal.append(entry)
        if entry.status == "open":
            logger.info(
                "#%d %s dicatat di jurnal: posisi uji terbuka",
                rank,
                symbol,
                extra=coin_event(entry),
            )
        else:
            logger.info(
                "#%d %s tidak masuk: %s", rank, symbol, entry.reason, extra=coin_event(entry)
            )
        return entry

    def _run(self, entry: JournalEntry, reading_source: ReadingSource | None) -> None:
        params, symbol = self.params, entry.symbol
        if any(e.symbol == symbol and e.status == "open" for e in self._journal.load()):
            raise _Skip("sudah ada posisi uji yang masih terbuka untuk pair ini")
        if not symbol.endswith("USDT"):
            raise _Skip("bukan pair USDT")

        # Saringan biaya (gratis, sebelum AI): funding, spread, dan kenaikan minimal bila diisi.
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

        # Saringan pola: garis kuning (MA7) terhadap MA25 di chart 15 menit.
        self._nav.show_15m_chart()
        name = f"{entry.id}_rank{entry.rank}"
        shots = self._settings.screenshot_dir
        entry.screenshots.append(str(self._nav.capture_window(shots / f"{name}.png")))
        chart = self._nav.capture_chart(shots / f"{name}_15m.png")
        entry.screenshots.append(str(chart))

        try:
            data: MaPattern | None = data_ma_pattern(
                self._market.klines(symbol, "15m", limit=candles_needed())
            )
        except MarketDataError as exc:  # bursa tanpa sumber candle: hanya AI yang menilai
            logger.info("Pembanding data tidak ada: %s", exc)
            data = None
        entry.pattern_data = data.as_dict() if data else None
        decisive = data
        if params.signal_source == "ai":
            if reading_source is None:
                raise _Skip("SINYAL=ai tetapi tidak ada sumber analisis AI")
            reading = reading_source(symbol, chart)
            entry.pattern_ai = reading.pattern.as_dict()
            entry.ai_summary = reading.summary
            decisive = reading.pattern
        if decisive is None:
            raise _Skip("bursa ini tidak punya data candle; pakai SINYAL=ai")
        entry.verdict = decisive.verdict(params.min_crosses)
        logger.info(
            "#%d %s garis kuning %s: %d kali di bawah MA25 -> %s (data: %d kali)%s",
            entry.rank,
            symbol,
            params.signal_source.upper(),
            decisive.below_count,
            _VERDICT_TEXT[entry.verdict],
            data.below_count if data else -1,
            f" | {entry.ai_summary}" if entry.ai_summary else "",
        )
        if entry.verdict != "ok":
            if entry.verdict == "tunggu" and decisive.below_count >= params.min_crosses:
                raise _Skip(
                    f"pola garis kuning TUNGGU (sudah {decisive.below_count} kali di bawah, "
                    "tapi 6 jam terakhir naik terus)"
                )
            raise _Skip(f"pola garis kuning {_VERDICT_TEXT[entry.verdict]}")

        # Langkah 4 SOP (setelah pola dan biaya): slot posisi.
        blocker = self.slot_blocker()
        if blocker:
            raise _Skip(blocker)

        # Ukuran posisi: margin % modal x leverage.
        rules = self._market.rules(symbol)
        price = quote.bid  # short menjual ke harga bid
        sizing = size_position(params, price, rules, self._settings.decimal_separator)
        if isinstance(sizing, str):
            raise _Skip(sizing)

        margin = self._nav.read_margin_settings()
        entry.margin = margin.describe()
        for issue in margin.problems(params.leverage):
            logger.warning("Margin di aplikasi: %s. Wajib diubah sebelum order sungguhan.", issue)

        # Langkah 5: isi form lalu pintu order (dimatikan).
        if self._fill_form:
            self._nav.fill_quantity(sizing.order_text)
        plan = OrderPlan(
            symbol=symbol,
            order_text=sizing.order_text,
            quantity_text=sizing.quantity_text,
            notional=sizing.notional,
            margin_usdt=sizing.margin_usdt,
            entry_price=price,
            target_price=price * (1 - params.target_pct / 100),
            stop_price=price * (1 + params.stop_pct / 100),
            leverage=params.leverage,
        )
        self._gate.submit(plan)

        entry.status = "open"
        entry.entry_price = plan.entry_price
        entry.max_price = plan.entry_price
        entry.quantity = sizing.quantity
        entry.notional = sizing.notional
        entry.margin_usdt = sizing.margin_usdt
        entry.target_price = plan.target_price
        entry.stop_price = plan.stop_price
        entry.deadline = entry.created_at + params.max_hold_h * 3600
        logger.info(
            "#%d %s MASUK UJI KERTAS: short %s USDT @ %g (%dx, margin %.2f USDT) | target %g | "
            "stop-loss %g | tinjau %s, tutup paling lambat %s",
            entry.rank,
            symbol,
            sizing.order_text,
            price,
            params.leverage,
            sizing.margin_usdt,
            plan.target_price,
            plan.stop_price,
            datetime.fromtimestamp(entry.created_at + params.review_after_h * 3600).strftime(
                "%H:%M"
            ),
            datetime.fromtimestamp(entry.deadline).strftime("%H:%M"),
        )
