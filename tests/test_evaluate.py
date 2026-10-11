from dataclasses import replace

import pytest

from binance_bot.strategy import JournalEntry, SopParams, stop_streak, summarize
from binance_bot.strategy.evaluate import evaluate_short
from fakes import candle

ENTRY = JournalEntry(
    id="t1",
    created_at=0.0,
    symbol="STRKUSDT",
    rank=1,
    status="open",
    entry_price=100.0,
    notional=200.0,
    target_price=96.0,
    stop_price=105.0,
    deadline=4 * 3600.0,
)


def minute(i: int, high: float, low: float, close: float = 100.0) -> object:
    return candle(close, high, low, close, 1, i)


def test_target_hit_first_is_a_win_after_fees() -> None:
    out = evaluate_short(ENTRY, [minute(1, 101, 99), minute(2, 100, 95.9)], [], 60, 0.5)
    assert out.status == "target"
    assert out.pnl_pct == pytest.approx(3.5)  # 4% - 0,5% biaya
    assert out.pnl_usdt == pytest.approx(7.0)


def test_stop_hit_first_is_a_loss() -> None:
    out = evaluate_short(ENTRY, [minute(1, 105.1, 99), minute(2, 100, 90)], [], 60, 0.5)
    assert out.status == "stop"
    assert out.pnl_pct == pytest.approx(-5.5)


def test_target_and_stop_in_same_candle_counts_as_stop() -> None:
    out = evaluate_short(ENTRY, [minute(1, 106, 95)], [], 60, 0.5)
    assert out.status == "stop"


def test_timeout_closes_at_last_candle_before_deadline() -> None:
    candles = [minute(1, 101, 99, 99.0), minute(239, 100, 98, 98.0)]
    out = evaluate_short(ENTRY, candles, [], now_s=5 * 3600, fee_pct=0.5)
    assert (out.status, out.exit_price) == ("timeout", 98.0)
    assert out.pnl_pct == pytest.approx(1.5)


def test_still_open_before_deadline_without_hits() -> None:
    assert evaluate_short(ENTRY, [minute(1, 101, 99)], [], 120, 0.5).status == "open"


def test_short_receives_positive_funding_and_pays_negative() -> None:
    funding = [(30 * 60_000, 0.001), (90 * 60_000, -0.0005)]
    out = evaluate_short(ENTRY, [minute(120, 100, 95.9)], funding, 7200, 0.5)
    assert out.funding_pct == pytest.approx(0.05)
    assert out.pnl_pct == pytest.approx(3.55)


def closed(status: str, pnl: float, at: float) -> JournalEntry:
    return replace(ENTRY, status=status, pnl_pct=pnl, pnl_usdt=pnl * 2, closed_at=at)


def test_stop_streak_counts_latest_consecutive_stops() -> None:
    entries = [
        closed("stop", -5.5, 1),
        closed("target", 3.5, 2),
        closed("stop", -5.5, 3),
        closed("stop", -5.5, 4),
    ]
    assert stop_streak(entries) == 2
    assert stop_streak(entries, since_s=4) == 1


def test_summary_needs_50_closed_trades_before_a_verdict() -> None:
    params = SopParams(capital_usdt=1000)
    stats = summarize([closed("target", 3.5, i) for i in range(10)], params)
    assert stats.closed == 10
    assert "10/50" in stats.verdict


def test_summary_passes_only_clearly_above_breakeven() -> None:
    params = SopParams(capital_usdt=1000)  # titik impas 61,1%
    good = [closed("target", 3.5, i) for i in range(35)] + [
        closed("stop", -5.5, 100 + i) for i in range(15)
    ]
    weak = [closed("target", 3.5, i) for i in range(31)] + [
        closed("stop", -5.5, 100 + i) for i in range(19)
    ]
    assert summarize(good, params).verdict.startswith("LULUS")  # 70% win rate
    assert summarize(weak, params).verdict.startswith("TIDAK LULUS")  # 62%: tipis di atas impas


def test_summary_counts_agreement_between_ai_and_data_signs() -> None:
    yes = {
        "upper_wick": True,
        "failed_new_high": True,
        "volume_declining": False,
        "big_red_after_greens": False,
    }
    no = dict.fromkeys(yes, False)
    entries = [
        replace(ENTRY, status="skipped", signs_ai=yes, signs_data=yes),
        replace(ENTRY, status="skipped", signs_ai=yes, signs_data=no),
    ]
    assert summarize(entries, SopParams(capital_usdt=1)).signal_agreement == (1, 2)
