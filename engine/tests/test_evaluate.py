from dataclasses import replace

import pytest

from binance_bot.market import Candle
from binance_bot.strategy import JournalEntry, SopParams, summarize
from binance_bot.strategy.evaluate import evaluate_by_price, evaluate_open_trades, evaluate_short
from fakes import candle

# Short V3: modal 100, margin 50% x 2x -> nilai posisi 100; jual otomatis di -3%, tanpa stop-loss.
ENTRY = JournalEntry(
    id="t1",
    created_at=0.0,
    symbol="STRKUSDT",
    rank=1,
    status="open",
    capital_usdt=100.0,
    leverage=2,
    entry_price=100.0,
    notional=100.0,
    target_price=97.0,
)
FEE = 0.1
DAY_MINUTES = 24 * 60


def minute(i: int, high: float, low: float, close: float = 100.0) -> Candle:
    return candle(close, high, low, close, 1, i)


def test_target_hit_first_is_a_win_after_fees() -> None:
    out = evaluate_short(ENTRY, [minute(1, 100.5, 99), minute(2, 100, 96.9)], [], FEE)
    assert out.status == "target"
    assert out.pnl_pct == pytest.approx(2.9)  # 3% - 0,1% fee
    assert out.pnl_capital_pct == pytest.approx(2.9)  # nilai posisi = 100% modal
    assert (out.max_price, out.min_price) == (100.5, 96.9)


def test_without_stop_loss_a_rising_price_keeps_the_position_open() -> None:
    out = evaluate_short(ENTRY, [minute(1, 110, 99), minute(2, 125, 105)], [], FEE)
    assert (out.status, out.max_price, out.min_price) == ("open", 125, 99)


def test_liquidation_is_the_last_loss_limit() -> None:
    # Isolated 2x: margin habis saat harga naik 50%.
    out = evaluate_short(ENTRY, [minute(1, 120, 99), minute(2, 151, 140)], [], FEE)
    assert (out.status, out.exit_price) == ("likuidasi", 150.0)
    assert out.pnl_pct == pytest.approx(-50.1)


def test_target_and_liquidation_in_the_same_candle_counts_as_liquidation() -> None:
    assert evaluate_short(ENTRY, [minute(1, 151, 96)], [], FEE).status == "likuidasi"


def test_there_is_no_time_limit() -> None:
    three_days = [minute(i, 101, 98.5) for i in (1, DAY_MINUTES, 3 * DAY_MINUTES)]
    out = evaluate_short(ENTRY, three_days, [], FEE)
    assert out.status == "open" and out.checked_ms == three_days[-1].close_time


def test_short_receives_positive_funding_and_pays_negative() -> None:
    funding = [(30 * 60_000, 0.001), (90 * 60_000, -0.0005)]
    out = evaluate_short(ENTRY, [minute(120, 100, 96.9)], funding, FEE)
    assert out.funding_pct == pytest.approx(0.05)
    assert out.pnl_pct == pytest.approx(2.95)


def test_tebbit_auto_sell_uses_the_price_read_from_the_screen() -> None:
    held = evaluate_by_price(ENTRY, ask=101.2, now_s=300, fee_pct=FEE)
    assert (held.status, held.max_price) == ("open", 101.2)
    sold = evaluate_by_price(held, ask=96.8, now_s=600, fee_pct=FEE)
    assert (sold.status, sold.exit_price, sold.closed_at) == ("target", 96.8, 600)
    assert sold.pnl_pct == pytest.approx(3.1)  # beli kembali di ask 96,8
    assert evaluate_by_price(ENTRY, ask=150.5, now_s=900, fee_pct=FEE).status == "likuidasi"


class PagedMarket:
    """Candle 1 menit seperti API: maksimal 1000 per permintaan, mulai dari `start_ms`."""

    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.requests = 0

    def klines(self, symbol: str, interval: str, **kw: int) -> list[Candle]:
        self.requests += 1
        start, end, limit = kw["start_ms"], kw["end_ms"], kw["limit"]
        return [c for c in self.candles if start <= c.open_time <= end][:limit]

    def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
        return []


def test_a_position_held_for_days_is_checked_minute_by_minute_in_pages() -> None:
    candles = [minute(i, 101, 98) for i in range(1, 2 * DAY_MINUTES)]
    candles.append(minute(2 * DAY_MINUTES, 100, 96.5))  # target baru tercapai di hari kedua
    market = PagedMarket(candles)
    now_s = (2 * DAY_MINUTES + 5) * 60
    [out] = evaluate_open_trades([ENTRY], market, now_s, FEE)  # type: ignore[arg-type]
    assert out.status == "target" and out.closed_at == candles[-1].close_time / 1000
    assert market.requests == 3  # 2.880 menit = 3 halaman


def closed(status: str, pnl: float, at: float) -> JournalEntry:
    return replace(ENTRY, status=status, pnl_pct=pnl, pnl_usdt=pnl, closed_at=at)


def test_summary_needs_50_closed_trades_before_a_verdict() -> None:
    stats = summarize([closed("target", 2.9, i) for i in range(10)], SopParams(), now_s=0)
    assert stats.closed == 10
    assert stats.net_capital_pct == pytest.approx(29.0)
    assert "10/50" in stats.verdict


def test_summary_breakeven_follows_the_real_losses() -> None:
    # Rugi rata-rata +21,8% (seperti STRK) dengan target 3% -> titik impas sekitar 88%.
    params = SopParams()
    good = [closed("target", 2.9, i) for i in range(47)] + [
        closed("likuidasi", -21.9, 100 + i) for i in range(3)
    ]
    weak = [closed("target", 2.9, i) for i in range(45)] + [
        closed("likuidasi", -21.9, 100 + i) for i in range(5)
    ]
    assert summarize(good, params, 0).breakeven == pytest.approx(0.883, abs=0.001)
    assert summarize(good, params, 0).verdict.startswith("LULUS")  # 94%
    assert summarize(weak, params, 0).verdict.startswith("TIDAK LULUS")  # 90%: tipis
    assert summarize(weak, params, 0).liquidations == 5


def test_summary_flags_positions_held_more_than_a_day() -> None:
    assert summarize([ENTRY], SopParams(), now_s=3600).needs_review == 0
    stats = summarize([ENTRY], SopParams(), now_s=24 * 3600 + 1)
    assert (stats.open, stats.needs_review) == (1, 1)


def test_summary_counts_agreement_between_ai_and_data() -> None:
    ok, wait = {"below_count": 3, "below_now": True}, {"below_count": 1, "below_now": False}
    entries = [
        replace(ENTRY, status="skipped", pattern_ai=ok, pattern_data=ok),
        replace(ENTRY, status="skipped", pattern_ai=ok, pattern_data=wait),
    ]
    assert summarize(entries, SopParams(), 0).signal_agreement == (1, 2)


def test_a_real_position_is_never_closed_at_the_paper_liquidation_price() -> None:
    # Kertas 2x: likuidasi di +50% (150). Posisi sungguhan tidak boleh ditutup bot di sana: itu
    # stop-loss tersembunyi, dan likuidasi sungguhan diatur bursa.
    real = replace(ENTRY, real=True)
    held = evaluate_by_price(real, ask=160.0, now_s=60, fee_pct=FEE)
    assert held.status == "open" and held.max_price == 160.0
    assert evaluate_by_price(ENTRY, ask=160.0, now_s=60, fee_pct=FEE).status == "likuidasi"
    # Di target tetap dijual, termasuk setelah harga sempat naik jauh.
    assert evaluate_by_price(held, ask=96.0, now_s=120, fee_pct=FEE).status == "target"
