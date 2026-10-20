from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime

from binance_bot.analysis import AnalysisRecord, PatternAnalyzer
from binance_bot.binance_desktop.pattern_rules import BINANCE
from binance_bot.config import Settings
from binance_bot.exceptions import BotError
from binance_bot.hub import AnalysisStore, HubServer
from binance_bot.logging_setup import event
from binance_bot.market import MarketData, is_futures_symbol
from binance_bot.strategy import PatternProfile, SopParams
from binance_bot.workflows.base import TradingNavigator
from binance_bot.workflows.sop import limits_of, log_top_gainers

logger = logging.getLogger(__name__)


class LeaderWorkflow:
    """Mode banyak, laptop leader: AI membaca pola garis kuning tiap rank SEKALI, lalu dibagikan.

    Bila MIN_NAIK diisi, hanya koin yang lolos saringan itu (gratis) yang dianalisis AI. Hasil
    koin yang sama dipakai ulang selama `analysis_ttl_s` (default 15 menit = satu lilin).
    Leader tidak mengisi form; setiap follower memutuskan dengan modal dan jurnalnya sendiri.
    """

    name = "leader"

    def __init__(
        self,
        settings: Settings,
        params: SopParams,
        navigator: TradingNavigator,
        market: MarketData,
        analyzer: PatternAnalyzer,
        store: AnalysisStore,
        hub: HubServer | None,
        ranks: Sequence[int],
        *,
        interval_s: float = 0.0,
        profile: PatternProfile = BINANCE,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._settings = settings
        self._params = params
        self._profile = profile
        self._nav = navigator
        self._market = market
        self._analyzer = analyzer
        self._store = store
        self._charts: dict[str, str] = {}  # pair -> screenshot grafik terakhir yang dibaca AI
        self._hub = hub
        self._ranks = list(ranks)
        self._interval_s = interval_s
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._now = now

    def run(self) -> None:
        if self._hub is not None:
            self._hub.start()
        try:
            while True:
                self.run_cycle()
                if self._interval_s <= 0:
                    break
                logger.info("Siklus berikutnya dalam %.0f menit", self._interval_s / 60)
                self._sleep(self._interval_s)
            if self._hub is not None:
                logger.info("Hub tetap melayani laptop lain. Tekan Ctrl+C untuk berhenti.")
                while True:
                    self._sleep(1)
        finally:
            if self._hub is not None:
                self._hub.stop()

    def run_cycle(self) -> list[AnalysisRecord]:
        # Rencana (Top yang dimainkan) dicatat sebelum sinyal mulai, agar follower tahu Top mana
        # yang perlu ditunggu, dan ditandai selesai walau putaran gagal di tengah jalan.
        self._store.begin_cycle(self._ranks, self._wall_clock())
        try:
            return self._cycle()
        finally:
            self._store.end_cycle()

    def _cycle(self) -> list[AnalysisRecord]:
        logger.info("Siklus analisis dimulai", extra=event("cycle", phase="start"))
        stamp = f"{self._now():%Y%m%d_%H%M%S}"
        with self._nav.screen_turn():
            self._nav.prepare()
            listed = self._nav.open_top_gainers()
        rows = {row.rank: row for row in listed}
        log_top_gainers(listed)
        records: list[AnalysisRecord] = []
        ai_calls = 0
        seen: set[str] = set()

        for rank in self._ranks:
            row = rows.get(rank)
            if row is not None and row.change_pct < self._params.min_gain_pct:
                logger.info(
                    "#%d %s dilewati: naik %.1f%% < %g%%",
                    rank,
                    row.symbol,
                    row.change_pct,
                    self._params.min_gain_pct,
                )
                continue
            try:
                # Satu koin = satu giliran layar (bot lain di laptop ini menunggu).
                with self._nav.screen_turn():
                    # Buka lewat namanya (lihat SingleWorkflow): peringkat bergeser.
                    if row is not None and is_futures_symbol(row.symbol):
                        symbol = self._nav.open_symbol(row.symbol)
                    else:
                        self._nav.open_top_gainers()  # bot lain bisa membuka halaman lain
                        symbol = self._nav.open_gainer(rank)
                    if symbol in seen:
                        # Peringkat bergeser sehingga pair yang sama terbuka lagi.
                        logger.info("#%d sekarang %s: sudah dinilai di siklus ini", rank, symbol)
                        continue
                    seen.add(symbol)
                    record = self._fresh(symbol, rank)
                    if record is None:
                        record = self._analyze(symbol, rank, stamp)
                        if record is None:
                            continue
                        ai_calls += 1
            except BotError as exc:
                # Tetap tampil sebagai baris di aplikasi (bukan hanya log) dengan alasannya.
                logger.warning(
                    "Rank #%d dilewati: %s",
                    rank,
                    exc,
                    extra=event(
                        "coin",
                        rank=rank,
                        symbol=row.symbol if row is not None else f"Top {rank}",
                        status="skipped",
                        verdict=None,
                        reason=str(exc),
                    ),
                )
                continue
            self._store.put(record)
            records.append(record)
            pattern = record.reading.pattern
            verdict = self._profile.verdict(pattern, self._params.min_crosses)
            logger.info(
                "#%d %s garis kuning AI: %d kali di bawah MA%d -> %s | %s",
                rank,
                symbol,
                pattern.below_count,
                self._profile.mid,
                verdict.upper(),
                record.reading.summary,
                extra=event(
                    "coin",
                    rank=rank,
                    symbol=symbol,
                    status="analyzed",
                    verdict=verdict,
                    count_ai=pattern.below_count,
                    ai=pattern.as_dict(),
                    limits=limits_of(self._params),
                    summary=record.reading.summary,
                    chart=self._charts.get(symbol),
                ),
            )

        logger.info(
            "Siklus selesai: %d hasil di hub, %d panggilan AI",
            len(records),
            ai_calls,
            extra=event(
                "cycle",
                phase="done",
                records=len(records),
                ai_calls=ai_calls,
                next_in_s=self._interval_s,
            ),
        )
        return records

    def _fresh(self, symbol: str, rank: int) -> AnalysisRecord | None:
        cached = self._store.fresh(symbol, self._settings.analysis_ttl_s, self._wall_clock())
        if cached is None:
            return None
        logger.info(
            "%s dianalisis %.1f menit lalu: dipakai ulang tanpa panggilan AI",
            symbol,
            cached.age_s(self._wall_clock()) / 60,
        )
        return replace(cached, rank=rank)

    def _analyze(self, symbol: str, rank: int, stamp: str) -> AnalysisRecord | None:
        # Peringkat bisa bergeser: pastikan pair yang terbuka memang lolos saringan naik.
        change = self._market.quote(symbol).change_pct
        if change < self._params.min_gain_pct:
            logger.info(
                "#%d %s dilewati: naik %.1f%% < %g%%",
                rank,
                symbol,
                change,
                self._params.min_gain_pct,
            )
            return None
        self._nav.show_15m_chart()
        chart = self._nav.capture_chart(
            self._settings.screenshot_dir / f"{stamp}_rank{rank}_{symbol}_15m.png"
        )
        self._nav.show_app(
            f"AI membaca grafik {symbol}", symbol=symbol, rank=rank, chart=str(chart), stage="ai"
        )
        started = time.monotonic()
        record = AnalysisRecord(symbol, rank, self._wall_clock(), self._analyzer.analyze(chart))
        self._charts[symbol] = str(chart)
        chart.with_suffix(".json").write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Analisis AI %s selesai dalam %.1f detik", symbol, time.monotonic() - started)
        return record
