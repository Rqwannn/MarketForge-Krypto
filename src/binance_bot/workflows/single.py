from __future__ import annotations

import logging
from collections.abc import Sequence

from binance_bot.analysis import PeakAnalyzer
from binance_bot.binance_desktop import BinanceNavigator
from binance_bot.exceptions import BotError
from binance_bot.workflows.sop import SopTrader, log_top_gainers

logger = logging.getLogger(__name__)


class SingleWorkflow:
    """Mode single: satu laptop menjalankan SOP penuh dan memanggil AI sendiri.

    Rank dicoba berurutan sampai batas posisi baru (MAKS_POSISI) tercapai.
    """

    name = "single"

    def __init__(
        self,
        navigator: BinanceNavigator,
        trader: SopTrader,
        analyzer: PeakAnalyzer | None,
        *,
        ranks: Sequence[int],
    ) -> None:
        self._nav = navigator
        self._trader = trader
        self._analyzer = analyzer
        self._ranks = list(ranks)

    def run(self) -> None:
        params = self._trader.params
        if self._trader.halted(self._trader.refresh_journal()):
            return

        self._nav.prepare()
        rows = {row.rank: row for row in self._nav.open_top_gainers()}
        log_top_gainers(list(rows.values()))
        analyzer = self._analyzer
        source = (lambda _symbol, chart: analyzer.analyze(chart)) if analyzer else None

        opened = 0
        on_list = True
        seen: set[str] = set()
        for rank in self._ranks:
            if opened >= params.max_positions:
                logger.info("Batas %d posisi uji baru tercapai", params.max_positions)
                break
            row = rows.get(rank)
            if row is not None and row.change_pct < params.min_gain_pct:
                logger.info(
                    "#%d %s dilewati: naik %.1f%% < %g%%",
                    rank,
                    row.symbol,
                    row.change_pct,
                    params.min_gain_pct,
                )
                continue
            try:
                if not on_list:
                    self._nav.open_top_gainers()
                on_list = False
                symbol = self._nav.open_gainer(rank)
            except BotError as exc:
                logger.error("Rank #%d dilewati: %s", rank, exc)
                continue
            if symbol in seen:
                # Peringkat bergeser sehingga pair yang sama terbuka lagi: jangan nilai dua kali.
                logger.info("#%d sekarang %s: sudah dinilai di run ini, dilewati", rank, symbol)
                continue
            seen.add(symbol)
            if self._trader.trade(rank, symbol, source).status == "open":
                opened += 1
        logger.info("Selesai: %d posisi uji kertas baru", opened)
