"""Menilai uji kertas dari candle sungguhan, lalu merangkum hasil terhadap titik impas SOP."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from binance_bot.market import Candle, MarketData
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
    (asumsi terburuk), karena urutan di dalam satu menit tidak diketahui. Harga tertinggi
    setelah masuk (seberapa jauh harga melawan posisi) dicatat sampai posisi selesai.
    """
    if entry.status != "open":
        return entry
    assert entry.entry_price and entry.stop_price and entry.target_price and entry.deadline
    deadline_ms = entry.deadline * 1000
    usable = [c for c in candles if c.open_time < deadline_ms]

    max_price = entry.max_price or entry.entry_price
    for candle in usable:
        max_price = max(max_price, candle.high)
        closed_at = candle.close_time / 1000
        if candle.high >= entry.stop_price:
            return _close(entry, "stop", entry.stop_price, closed_at, max_price, funding, fee_pct)
        if candle.low <= entry.target_price:
            return _close(
                entry, "target", entry.target_price, closed_at, max_price, funding, fee_pct
            )

    if now_s >= entry.deadline and usable:
        last = usable[-1]
        return _close(
            entry, "timeout", last.close, last.close_time / 1000, max_price, funding, fee_pct
        )
    return replace(entry, max_price=max_price)


def close_short_now(
    entry: JournalEntry,
    ask: float,
    now_s: float,
    funding: Sequence[tuple[int, float]],
    fee_pct: float,
) -> JournalEntry:
    """Tutup short uji kertas sekarang (menu Sell): beli kembali di harga ask saat ini."""
    if entry.status != "open":
        return entry
    max_price = max(entry.max_price or entry.entry_price or ask, ask)
    return _close(entry, "manual", ask, now_s, max_price, funding, fee_pct)


def _close(
    entry: JournalEntry,
    status: str,
    exit_price: float,
    closed_at: float,
    max_price: float,
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
        max_price=max_price,
        funding_pct=funding_pct,
        pnl_pct=pnl_pct,
        pnl_usdt=entry.notional * pnl_pct / 100,
    )


def evaluate_open_trades(
    entries: Sequence[JournalEntry], market: MarketData, now_s: float, fee_pct: float
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
    manual: int  # ditutup lewat menu Sell
    open: int
    needs_review: int  # posisi terbuka melewati batas tinjau (usulan 1 jam)
    skipped: int
    win_rate: float | None
    breakeven: float
    net_capital_pct: float  # jumlah hasil bersih dalam persen modal
    net_usdt: float
    worst_against_pct: float | None  # kenaikan terbesar melawan posisi setelah masuk
    stop_streak: int
    signal_agreement: tuple[int, int]  # (AI dan data sepakat, jumlah yang bisa dibandingkan)

    @property
    def verdict(self) -> str:
        if self.closed < REQUIRED_TEST_TRADES:
            return f"Belum cukup data: {self.closed}/{REQUIRED_TEST_TRADES} trade uji selesai"
        assert self.win_rate is not None
        passed = self.net_usdt > 0 and self.win_rate >= self.breakeven + PASS_MARGIN
        return "LULUS fase uji" if passed else "TIDAK LULUS: ubah satu aturan, lalu uji ulang"


def _is_ok(pattern: dict[str, object] | None, min_crosses: int) -> bool | None:
    if pattern is None:
        return None
    count = pattern.get("below_count")
    return isinstance(count, int) and count >= min_crosses


def summarize(entries: Sequence[JournalEntry], params: SopParams, now_s: float) -> Stats:
    closed = [e for e in entries if e.is_closed]
    opened = [e for e in entries if e.status == "open"]
    wins = sum(1 for e in closed if (e.pnl_pct or 0) > 0)
    against = [
        100 * (e.max_price - e.entry_price) / e.entry_price
        for e in entries
        if e.max_price is not None and e.entry_price
    ]
    verdicts = [
        (_is_ok(e.pattern_ai, params.min_crosses), _is_ok(e.pattern_data, params.min_crosses))
        for e in entries
    ]
    compared = [(a, d) for a, d in verdicts if a is not None and d is not None]
    return Stats(
        closed=len(closed),
        wins=wins,
        targets=sum(1 for e in closed if e.status == "target"),
        stops=sum(1 for e in closed if e.status == "stop"),
        timeouts=sum(1 for e in closed if e.status == "timeout"),
        manual=sum(1 for e in closed if e.status == "manual"),
        open=len(opened),
        needs_review=sum(1 for e in opened if now_s - e.created_at >= params.review_after_h * 3600),
        skipped=sum(1 for e in entries if e.status == "skipped"),
        win_rate=wins / len(closed) if closed else None,
        breakeven=params.breakeven_win_rate,
        net_capital_pct=sum(e.pnl_capital_pct or 0 for e in closed),
        net_usdt=sum(e.pnl_usdt or 0 for e in closed),
        worst_against_pct=max(against) if against else None,
        stop_streak=stop_streak(entries),
        signal_agreement=(sum(1 for a, d in compared if a == d), len(compared)),
    )
