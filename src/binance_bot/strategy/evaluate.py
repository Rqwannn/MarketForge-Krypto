"""Menilai uji kertas dari candle sungguhan, lalu merangkum hasil terhadap titik impas SOP."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from binance_bot.market import Candle, FuturesMarket
from binance_bot.strategy.journal import JournalEntry
from binance_bot.strategy.params import PASS_MARGIN, REQUIRED_TEST_TRADES, SopParams

_MINUTE_MS = 60_000


def evaluate_short(
    entry: JournalEntry,
    candles: Sequence[Candle],
    funding: Sequence[tuple[int, float]],
    now_s: float,
    fee_pct: float,
) -> JournalEntry:
    """Tentukan nasib satu short uji kertas dari candle 1 menit setelah waktu masuk.

    Bila target dan stop-loss sama-sama tersentuh di candle yang sama, dianggap stop-loss
    (asumsi terburuk), karena urutan di dalam satu menit tidak diketahui.
    """
    if entry.status != "open":
        return entry
    assert entry.entry_price and entry.stop_price and entry.target_price and entry.deadline
    deadline_ms = entry.deadline * 1000
    usable = [c for c in candles if c.open_time < deadline_ms]

    for candle in usable:
        if candle.high >= entry.stop_price:
            return _close(
                entry, "stop", entry.stop_price, candle.close_time / 1000, funding, fee_pct
            )
        if candle.low <= entry.target_price:
            return _close(
                entry, "target", entry.target_price, candle.close_time / 1000, funding, fee_pct
            )

    if now_s >= entry.deadline and usable:
        last = usable[-1]
        return _close(entry, "timeout", last.close, last.close_time / 1000, funding, fee_pct)
    return entry


def _close(
    entry: JournalEntry,
    status: str,
    exit_price: float,
    closed_at: float,
    funding: Sequence[tuple[int, float]],
    fee_pct: float,
) -> JournalEntry:
    assert entry.entry_price and entry.notional is not None
    # Short menerima funding bila rate positif dan membayar bila negatif.
    funding_pct = 100 * sum(
        rate for time_ms, rate in funding if entry.created_at * 1000 <= time_ms <= closed_at * 1000
    )
    pnl_pct = 100 * (entry.entry_price - exit_price) / entry.entry_price - fee_pct + funding_pct
    return replace(
        entry,
        status=status,
        exit_price=exit_price,
        closed_at=closed_at,
        funding_pct=funding_pct,
        pnl_pct=pnl_pct,
        pnl_usdt=entry.notional * pnl_pct / 100,
    )


def evaluate_open_trades(
    entries: Sequence[JournalEntry], market: FuturesMarket, now_s: float, fee_pct: float
) -> list[JournalEntry]:
    updated = []
    for entry in entries:
        if entry.status == "open" and entry.deadline is not None:
            # Mulai dari menit setelah masuk: pergerakan sebelum masuk tidak dihitung.
            start_ms = (int(entry.created_at * 1000) // _MINUTE_MS + 1) * _MINUTE_MS
            end_ms = int(min(now_s, entry.deadline) * 1000)
            if end_ms > start_ms:
                candles = market.klines(
                    entry.symbol, "1m", limit=1000, start_ms=start_ms, end_ms=end_ms
                )
                funding = market.funding_history(entry.symbol, start_ms, end_ms)
                entry = evaluate_short(entry, candles, funding, now_s, fee_pct)
        updated.append(entry)
    return updated


def stop_streak(entries: Sequence[JournalEntry], since_s: float = 0.0) -> int:
    """Jumlah stop-loss berturut-turut paling akhir (sejak `since_s`)."""
    closed = sorted(
        (e for e in entries if e.is_closed and (e.closed_at or 0) >= since_s),
        key=lambda e: e.closed_at or 0,
    )
    streak = 0
    for entry in reversed(closed):
        if entry.status != "stop":
            break
        streak += 1
    return streak


@dataclass(frozen=True, slots=True)
class Stats:
    closed: int
    wins: int
    targets: int
    stops: int
    timeouts: int
    open: int
    skipped: int
    win_rate: float | None
    breakeven: float
    net_pct: float
    net_usdt: float
    stop_streak: int
    signal_agreement: tuple[int, int]  # (AI dan data sepakat, jumlah yang bisa dibandingkan)

    @property
    def verdict(self) -> str:
        if self.closed < REQUIRED_TEST_TRADES:
            return f"Belum cukup data: {self.closed}/{REQUIRED_TEST_TRADES} trade uji selesai"
        assert self.win_rate is not None
        passed = self.net_usdt > 0 and self.win_rate >= self.breakeven + PASS_MARGIN
        return "LULUS fase uji" if passed else "TIDAK LULUS: ubah satu aturan, lalu uji ulang"


def summarize(entries: Sequence[JournalEntry], params: SopParams) -> Stats:
    closed = [e for e in entries if e.is_closed]
    wins = sum(1 for e in closed if (e.pnl_pct or 0) > 0)
    compared = [e for e in entries if e.signs_ai is not None and e.signs_data is not None]
    agree = sum(
        (sum(e.signs_ai.values()) >= params.min_signs)  # type: ignore[union-attr]
        == (sum(e.signs_data.values()) >= params.min_signs)  # type: ignore[union-attr]
        for e in compared
    )
    return Stats(
        closed=len(closed),
        wins=wins,
        targets=sum(1 for e in closed if e.status == "target"),
        stops=sum(1 for e in closed if e.status == "stop"),
        timeouts=sum(1 for e in closed if e.status == "timeout"),
        open=sum(1 for e in entries if e.status == "open"),
        skipped=sum(1 for e in entries if e.status == "skipped"),
        win_rate=wins / len(closed) if closed else None,
        breakeven=params.breakeven_win_rate,
        net_pct=sum(e.pnl_pct or 0 for e in closed),
        net_usdt=sum(e.pnl_usdt or 0 for e in closed),
        stop_streak=stop_streak(entries),
        signal_agreement=(agree, len(compared)),
    )
