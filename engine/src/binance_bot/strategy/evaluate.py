"""Menilai uji kertas dari candle sungguhan, lalu merangkum hasil terhadap titik impas SOP."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from binance_bot.market import Candle, MarketData, Quote
from binance_bot.strategy.journal import JournalEntry
from binance_bot.strategy.params import PASS_MARGIN, REQUIRED_TEST_TRADES, SopParams

_MINUTE_MS = 60_000


def is_long(entry: JournalEntry) -> bool:
    return entry.side == "long"


def entry_price_of(side: str, quote: Quote) -> float:
    """Harga masuk: short menjual ke bid, long membeli di ask."""
    return quote.ask if side == "long" else quote.bid


def exit_price(entry: JournalEntry, quote: Quote) -> float:
    """Harga tutup posisi: short membeli kembali di ask, long menjual di bid."""
    return quote.bid if is_long(entry) else quote.ask


def gain_pct(entry: JournalEntry, price: float) -> float:
    """Gerak harga yang menguntungkan posisi, dalam persen harga masuk (negatif = melawan)."""
    assert entry.entry_price
    move = (price - entry.entry_price) / entry.entry_price
    return 100 * (move if is_long(entry) else -move)


def liquidation_price(entry: JournalEntry) -> float:
    """Harga likuidasi (Isolated): margin habis saat harga melawan 100%/leverage (2x: 50%).

    Tanpa cutloss, inilah batas rugi terakhir yang dipakai uji kertas.
    """
    assert entry.entry_price
    against = 1 / (entry.leverage or 1)
    return entry.entry_price * (1 - against if is_long(entry) else 1 + against)


def _beyond(entry: JournalEntry, price: float, level: float) -> bool:
    """Harga sudah melewati `level` ke arah yang melawan posisi."""
    return price <= level if is_long(entry) else price >= level


def _reached(entry: JournalEntry, price: float, level: float) -> bool:
    """Harga sudah mencapai `level` ke arah yang menguntungkan posisi (target)."""
    return price >= level if is_long(entry) else price <= level


def _time_exit(entry: JournalEntry, price: float, now_s: float, fee_pct: float) -> bool:
    """Batas waktu V4: sesudah `green_exit_at` jual bila untung bersih (setelah fee), di
    `time_exit_at` jual apa pun kondisinya."""
    if entry.time_exit_at is not None and now_s >= entry.time_exit_at:
        return True
    return (
        entry.green_exit_at is not None
        and now_s >= entry.green_exit_at
        and gain_pct(entry, price) - fee_pct > 0
    )


def evaluate_candles(
    entry: JournalEntry,
    candles: Sequence[Candle],
    funding: Sequence[tuple[int, float]],
    fee_pct: float,
) -> JournalEntry:
    """Jual otomatis uji kertas dari candle 1 menit setelah waktu masuk.

    Begitu harga mencapai target, seluruh posisi ditutup di harga target. Bila cutloss menyala
    (`cutloss_price`), posisi ditutup di harga cutloss begitu harga melewatinya; tanpa cutloss
    posisi baru berakhir rugi di likuidasi. Bila batas rugi dan target tersentuh di candle yang
    sama, dianggap rugi (asumsi terburuk). Batas waktu dinilai di harga tutup candle. Harga
    tertinggi dan terendah setelah masuk dicatat sampai posisi selesai.
    """
    if entry.status != "open":
        return entry
    assert entry.entry_price and entry.target_price
    liquidation = liquidation_price(entry)
    max_price = entry.max_price or entry.entry_price
    min_price = entry.min_price or entry.entry_price
    for candle in candles:
        max_price = max(max_price, candle.high)
        min_price = min(min_price, candle.low)
        closed_at = candle.close_time / 1000
        worst, best = (candle.low, candle.high) if is_long(entry) else (candle.high, candle.low)
        exit_ = None
        if entry.cutloss_price is not None and _beyond(entry, worst, entry.cutloss_price):
            exit_ = ("stop", entry.cutloss_price)
        elif _beyond(entry, worst, liquidation):
            exit_ = ("likuidasi", liquidation)
        elif _reached(entry, best, entry.target_price):
            exit_ = ("target", entry.target_price)
        elif _time_exit(entry, candle.close, closed_at, fee_pct):
            exit_ = ("timeout", candle.close)
        if exit_:
            status, price = exit_
            return _close(entry, status, price, closed_at, max_price, min_price, funding, fee_pct)
    checked = candles[-1].close_time if candles else entry.checked_ms
    return replace(entry, max_price=max_price, min_price=min_price, checked_ms=checked)


def evaluate_by_price(
    entry: JournalEntry, price: float, now_s: float, fee_pct: float
) -> JournalEntry:
    """Jual otomatis dari harga terkini (posisi sungguhan, dan bursa tanpa candle seperti Tebbit).

    `price` = harga tutup posisi (`exit_price`: ask untuk short, bid untuk long). Di antara dua
    pengecekan pergerakan harga tidak terlihat.

    Posisi sungguhan (`real`) dijual di target, dan di cutloss serta batas waktu bila pengguna
    menyalakannya. Batas likuidasi kertas (1/leverage) tidak berlaku untuk posisi sungguhan:
    likuidasi sungguhan diatur bursa, dan menutup posisi di batas kertas akan menjadi stop-loss
    tersembunyi yang tidak dipilih pengguna.
    """
    if entry.status != "open":
        return entry
    assert entry.entry_price and entry.target_price
    max_price = max(entry.max_price or entry.entry_price, price)
    min_price = min(entry.min_price or entry.entry_price, price)
    status = None
    if entry.cutloss_price is not None and _beyond(entry, price, entry.cutloss_price):
        status = "stop"
    elif not entry.real and _beyond(entry, price, liquidation_price(entry)):
        status = "likuidasi"
    elif _reached(entry, price, entry.target_price):
        status = "target"
    elif _time_exit(entry, price, now_s, fee_pct):
        status = "timeout"
    if status:
        return _close(entry, status, price, now_s, max_price, min_price, (), fee_pct)
    return replace(
        entry, max_price=max_price, min_price=min_price, last_price=price, last_price_at=now_s
    )


def close_now(
    entry: JournalEntry,
    price: float,
    now_s: float,
    funding: Sequence[tuple[int, float]],
    fee_pct: float,
) -> JournalEntry:
    """Tutup posisi uji kertas sekarang (menu Sell) di harga tutup saat ini (`exit_price`)."""
    if entry.status != "open":
        return entry
    max_price = max(entry.max_price or entry.entry_price or price, price)
    min_price = min(entry.min_price or entry.entry_price or price, price)
    return _close(entry, "manual", price, now_s, max_price, min_price, funding, fee_pct)


def _close(
    entry: JournalEntry,
    status: str,
    exit_price: float,
    closed_at: float,
    max_price: float,
    min_price: float,
    funding: Sequence[tuple[int, float]],
    fee_pct: float,
) -> JournalEntry:
    assert entry.entry_price and entry.notional is not None
    # Short menerima funding bila rate positif dan membayar bila negatif; long sebaliknya.
    funding_pct = 100 * sum(
        rate for time_ms, rate in funding if entry.created_at * 1000 <= time_ms <= closed_at * 1000
    )
    if is_long(entry):
        funding_pct = -funding_pct
    pnl_pct = gain_pct(entry, exit_price) - fee_pct + funding_pct
    return replace(
        entry,
        status=status,
        exit_price=exit_price,
        closed_at=closed_at,
        max_price=max_price,
        min_price=min_price,
        funding_pct=funding_pct,
        pnl_pct=pnl_pct,
        pnl_usdt=entry.notional * pnl_pct / 100,
    )


def evaluate_open_trades(
    entries: Sequence[JournalEntry], market: MarketData, now_s: float, fee_pct: float
) -> list[JournalEntry]:
    """Nilai semua posisi terbuka dari candle 1 menit sejak pengecekan terakhir.

    Tanpa batas waktu, posisi bisa ditahan berhari-hari: candle diambil per 1000 menit dari titik
    terakhir yang sudah dinilai (`checked_ms`), jadi tidak ada menit yang terlewat.
    """
    updated = []
    end_ms = int(now_s * 1000)
    for entry in entries:
        if entry.status == "open" and entry.entry_price and entry.target_price and not entry.real:
            # Mulai dari menit setelah masuk: pergerakan sebelum masuk tidak dihitung.
            first_ms = (int(entry.created_at * 1000) // _MINUTE_MS + 1) * _MINUTE_MS
            start_ms = max(first_ms, (entry.checked_ms or 0) + 1)
            while entry.status == "open" and end_ms - start_ms >= _MINUTE_MS:
                candles = [
                    c
                    for c in market.klines(
                        entry.symbol, "1m", limit=1000, start_ms=start_ms, end_ms=end_ms
                    )
                    # Lilin yang sudah dinilai dan lilin yang masih berjalan dilewati.
                    if c.open_time >= start_ms and c.close_time <= end_ms
                ]
                if not candles:
                    break
                funding = market.funding_history(entry.symbol, first_ms, end_ms)
                entry = evaluate_candles(entry, candles, funding, fee_pct)
                start_ms = candles[-1].close_time + 1
        updated.append(entry)
    return updated


@dataclass(frozen=True, slots=True)
class Stats:
    closed: int
    wins: int
    targets: int
    liquidations: int
    stops: int  # kena cutloss
    timeouts: int  # dijual karena batas waktu
    manual: int  # ditutup lewat menu Sell
    open: int
    needs_review: int  # posisi terbuka lebih dari batas tinjau (V3: lebih dari satu hari)
    skipped: int
    win_rate: float | None
    breakeven: float
    net_capital_pct: float  # jumlah hasil bersih dalam persen modal
    net_usdt: float
    worst_against_pct: float | None  # gerak harga terbesar melawan posisi setelah masuk
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
    # Catatan lama belum punya below_recent: dinilai seperti dulu (hitungan saja).
    recent = pattern.get("below_recent", True) is not False
    return isinstance(count, int) and count >= min_crosses and recent


def _average_loss(closed: Sequence[JournalEntry], fee_pct: float) -> tuple[float, ...]:
    """Rata-rata kenaikan harga yang ditanggung posisi rugi; kosong = pakai contoh V3."""
    losses = [-(e.pnl_pct or 0) - fee_pct for e in closed if (e.pnl_pct or 0) < 0]
    return (sum(losses) / len(losses),) if losses else ()


def summarize(entries: Sequence[JournalEntry], params: SopParams, now_s: float) -> Stats:
    closed = [e for e in entries if e.is_closed]
    opened = [e for e in entries if e.status == "open"]
    wins = sum(1 for e in closed if (e.pnl_pct or 0) > 0)
    against = [
        -gain_pct(e, worst)
        for e in entries
        if e.entry_price and (worst := e.min_price if is_long(e) else e.max_price) is not None
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
        liquidations=sum(1 for e in closed if e.status == "likuidasi"),
        stops=sum(1 for e in closed if e.status == "stop"),
        timeouts=sum(1 for e in closed if e.status == "timeout"),
        manual=sum(1 for e in closed if e.status == "manual"),
        open=len(opened),
        needs_review=sum(1 for e in opened if now_s - e.created_at >= params.review_after_h * 3600),
        skipped=sum(1 for e in entries if e.status == "skipped"),
        win_rate=wins / len(closed) if closed else None,
        breakeven=params.breakeven_win_rate(*_average_loss(closed, params.fee_pct)),
        net_capital_pct=sum(e.pnl_capital_pct or 0 for e in closed),
        net_usdt=sum(e.pnl_usdt or 0 for e in closed),
        worst_against_pct=max(against) if against else None,
        signal_agreement=(sum(1 for a, d in compared if a == d), len(compared)),
    )
