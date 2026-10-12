from dataclasses import replace

import pytest

from binance_bot.market import Candle
from binance_bot.strategy import JournalEntry, SopParams, stop_streak, summarize
from binance_bot.strategy.evaluate import evaluate_short
from fakes import candle

# Short V2: modal 100, margin 50% x 2x -> nilai posisi 100; target -2%, stop-loss +2%.
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
    target_price=98.0,
    stop_price=102.0,
    deadline=4 * 3600.0,
)
FEE = 0.1


def minute(i: int, high: float, low: float, close: float = 100.0) -> Candle:
    return candle(close, high, low, close, 1, i)


def test_target_hit_first_is_a_win_after_fees() -> None:
    out = evaluate_short(ENTRY, [minute(1, 100.5, 99), minute(2, 100, 97.9)], [], 60, FEE)
    assert out.status == "target"
    assert out.pnl_pct == pytest.approx(1.9)  # 2% - 0,1% fee
    assert out.pnl_capital_pct == pytest.approx(1.9)  # nilai posisi = 100% modal
    assert out.max_price == pytest.approx(100.5)  # harga tertinggi setelah masuk


def test_stop_hit_first_is_a_loss_of_about_2pct_capital() -> None:
    out = evaluate_short(ENTRY, [minute(1, 102.1, 99), minute(2, 100, 90)], [], 60, FEE)
    assert out.status == "stop"
    assert out.pnl_pct == pytest.approx(-2.1)
    assert out.max_price == pytest.approx(102.1)


def test_target_and_stop_in_same_candle_counts_as_stop() -> None:
    assert evaluate_short(ENTRY, [minute(1, 103, 97)], [], 60, FEE).status == "stop"


def test_timeout_closes_at_last_candle_before_deadline() -> None:
    candles = [minute(1, 101, 99, 99.0), minute(239, 100, 98.5, 99.0)]
    out = evaluate_short(ENTRY, candles, [], now_s=5 * 3600, fee_pct=FEE)
    assert (out.status, out.exit_price) == ("timeout", 99.0)
    assert out.pnl_pct == pytest.approx(0.9)


def test_open_trade_keeps_tracking_the_highest_price() -> None:
    out = evaluate_short(ENTRY, [minute(1, 101.3, 99.5)], [], 120, FEE)
    assert (out.status, out.max_price) == ("open", 101.3)


def test_short_receives_positive_funding_and_pays_negative() -> None:
    funding = [(30 * 60_000, 0.001), (90 * 60_000, -0.0005)]
    out = evaluate_short(ENTRY, [minute(120, 100, 97.9)], funding, 7200, FEE)
    assert out.funding_pct == pytest.approx(0.05)
    assert out.pnl_pct == pytest.approx(1.95)


def closed(status: str, pnl: float, at: float) -> JournalEntry:
    return replace(ENTRY, status=status, pnl_pct=pnl, pnl_usdt=pnl, closed_at=at)


def test_stop_streak_counts_latest_consecutive_stops() -> None:
    entries = [
        closed("stop", -2.1, 1),
        closed("target", 1.9, 2),
        closed("stop", -2.1, 3),
        closed("stop", -2.1, 4),
    ]
    assert stop_streak(entries) == 2
    assert stop_streak(entries, since_s=4) == 1


def test_summary_needs_50_closed_trades_before_a_verdict() -> None:
    stats = summarize([closed("target", 1.9, i) for i in range(10)], SopParams(), now_s=0)
    assert stats.closed == 10
    assert stats.net_capital_pct == pytest.approx(19.0)
    assert "10/50" in stats.verdict


def test_summary_passes_only_clearly_above_breakeven() -> None:
    params = SopParams()  # titik impas 52,5%
    good = [closed("target", 1.9, i) for i in range(30)] + [
        closed("stop", -2.1, 100 + i) for i in range(20)
    ]
    weak = [closed("target", 1.9, i) for i in range(27)] + [
        closed("stop", -2.1, 100 + i) for i in range(23)
    ]
    assert summarize(good, params, 0).verdict.startswith("LULUS")  # 60% win rate
    assert summarize(weak, params, 0).verdict.startswith("TIDAK LULUS")  # 54%: tipis


def test_summary_flags_positions_open_past_review_time() -> None:
    stats = summarize([ENTRY], SopParams(), now_s=3601)
    assert (stats.open, stats.needs_review) == (1, 1)


def test_summary_counts_agreement_between_ai_and_data() -> None:
    ok, wait = {"below_count": 3, "below_now": True}, {"below_count": 1, "below_now": False}
    entries = [
        replace(ENTRY, status="skipped", pattern_ai=ok, pattern_data=ok),
        replace(ENTRY, status="skipped", pattern_ai=ok, pattern_data=wait),
    ]
    assert summarize(entries, SopParams(), 0).signal_agreement == (1, 2)
