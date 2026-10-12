from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.config import Settings
from binance_bot.exceptions import ScreenReadError
from binance_bot.hub import AnalysisStore, SharedAnalysis
from binance_bot.market import Quote
from binance_bot.strategy import Journal, JournalEntry, SopParams
from binance_bot.workflows import (
    FollowerWorkflow,
    JournalWorkflow,
    LeaderWorkflow,
    SingleWorkflow,
    SopTrader,
)
from fakes import (
    NEVER,
    OK,
    WAIT,
    Clock,
    FakeGate,
    FakeMarket,
    FakeNavigator,
    FakePatternAnalyzer,
    candle,
    ma_candles,
    record,
)

NOW = datetime(2026, 10, 12, 16, 0, 0)


def make_trader(
    tmp_path: Path, nav: FakeNavigator, market: FakeMarket | None = None, **params: Any
) -> tuple[SopTrader, FakeGate, Journal, FakeMarket]:
    market = market or FakeMarket()
    journal, gate = Journal(tmp_path / "sop.jsonl"), FakeGate()
    trader = SopTrader(
        Settings(screenshot_dir=tmp_path / "shots"),
        SopParams(**{"capital_usdt": 100.0, **params}),
        nav,  # type: ignore[arg-type]
        market,  # type: ignore[arg-type]
        journal,
        gate,  # type: ignore[arg-type]
        wall_clock=lambda: NOW.timestamp(),
        now=lambda: NOW,
    )
    return trader, gate, journal, market


def source(analyzer: FakePatternAnalyzer) -> Any:
    return lambda _symbol, chart: analyzer.analyze(chart)


def open_trade(symbol: str, entry_price: float = 1.0) -> JournalEntry:
    return JournalEntry(
        id=f"o-{symbol}",
        created_at=NOW.timestamp() - 60,
        symbol=symbol,
        rank=1,
        status="open",
        entry_price=entry_price,
        notional=100.0,
        target_price=entry_price * 0.98,
        stop_price=entry_price * 1.02,
        deadline=NOW.timestamp() + 3 * 3600,
        capital_usdt=100.0,
    )


# --------------------------------------------------------------------------- inti SOP V2


def test_ok_pattern_is_sized_2x_filled_and_paper_traded(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, journal, _ = make_trader(tmp_path, nav)
    analyzer = FakePatternAnalyzer(OK)

    entry = trader.trade(1, "STRKUSDT", source(analyzer))

    assert (entry.status, entry.verdict) == ("open", "ok")
    assert nav.filled == ["100,0"]  # 100 USDT x margin 50% x 2x = nilai 100 USDT, bid 1,0
    plan = gate.plans[0]
    assert (plan.side, plan.leverage, plan.margin_usdt) == ("SHORT", 2, pytest.approx(50.0))
    assert plan.target_price == pytest.approx(0.98)  # target 2% di bawah
    assert plan.stop_price == pytest.approx(1.02)  # stop-loss 2% di atas
    assert entry.pattern_ai == {"below_count": 3, "below_now": True}
    assert entry.pattern_data == {"below_count": 2, "below_now": False}
    assert entry.max_price == pytest.approx(1.0)
    assert [e.status for e in journal.load()] == ["open"]


@pytest.mark.parametrize(("pattern", "word"), [(NEVER, "JANGAN"), (WAIT, "TUNGGU")])
def test_pattern_not_ok_means_no_entry(tmp_path: Path, pattern: Any, word: str) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(pattern)))
    assert entry.status == "skipped" and word in entry.reason
    assert nav.filled == [] and gate.plans == []


@pytest.mark.parametrize(
    ("quote", "reason"),
    [(Quote(1.0, 1.0005, -0.001, 50.0), "funding"), (Quote(1.0, 1.01, 0.0001, 50.0), "spread")],
)
def test_cost_filters_skip_before_any_ai_call(tmp_path: Path, quote: Quote, reason: str) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav, FakeMarket(quote=quote))
    analyzer = FakePatternAnalyzer(OK)
    entry = trader.trade(1, "STRKUSDT", source(analyzer))
    assert reason in entry.reason and analyzer.calls == []


def test_min_gain_filter_is_off_by_default_and_optional(tmp_path: Path) -> None:
    calm = FakeMarket(quote=Quote(1.0, 1.0005, 0.0001, 5.0))
    trader, _, _, _ = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}), calm)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"
    strict, _, _, _ = make_trader(
        tmp_path / "b", FakeNavigator({1: "STRKUSDT"}), calm, min_gain_pct=30
    )
    assert "naik 5.0%" in strict.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).reason


def test_data_signal_mode_decides_without_ai(tmp_path: Path) -> None:
    trader, _, _, _ = make_trader(
        tmp_path,
        FakeNavigator({1: "STRKUSDT"}),
        FakeMarket(candles=ma_candles(1)),
        signal_source="data",
    )
    entry = trader.trade(1, "STRKUSDT", None)
    assert entry.verdict == "tunggu" and entry.pattern_ai is None


def test_margin_differences_are_warned_but_paper_trade_continues(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"}, margin=MarginSettings(False, 20))
    trader, _, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert (entry.status, entry.margin) == ("open", "Cross 20x")


# --------------------------------------------------------------------------- slot (langkah 4)


def test_no_third_position_while_two_are_open(tmp_path: Path) -> None:
    trader, gate, journal, _ = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}))
    journal.append(open_trade("CFXUSDT"))
    journal.append(open_trade("MBLUSDT"))
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert "sudah 2 posisi terbuka" in entry.reason and gate.plans == []


def test_second_coin_only_when_first_is_not_losing(tmp_path: Path) -> None:
    trader, _, journal, market = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}))
    journal.append(open_trade("CFXUSDT", entry_price=1.0))
    market.quotes["CFXUSDT"] = Quote(bid=1.009, ask=1.01, funding_rate=0.0, change_pct=40.0)
    losing = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert "CFXUSDT sedang rugi" in losing.reason

    market.quotes["CFXUSDT"] = Quote(bid=0.99, ask=0.991, funding_rate=0.0, change_pct=40.0)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"


def test_three_stop_losses_today_halts_the_engine(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    for i in range(3):
        journal.append(
            JournalEntry(
                id=f"s{i}",
                created_at=NOW.timestamp() - 600,
                symbol="CFXUSDT",
                rank=1,
                status="stop",
                closed_at=NOW.timestamp() - 60 + i,
            )
        )
    analyzer = FakePatternAnalyzer(OK)
    SingleWorkflow(nav, trader, analyzer, ranks=[1]).run()  # type: ignore[arg-type]
    assert nav.calls == [] and analyzer.calls == []


# --------------------------------------------------------------------------- mode single


def test_single_watches_top5_and_fills_up_to_two_slots(tmp_path: Path) -> None:
    symbols = {1: "STRKUSDT", 2: "LUMIAUSDT", 3: "CFXUSDT", 4: "GRASSUSDT", 5: "SUSDT"}
    nav = FakeNavigator(symbols)  # type: ignore[arg-type]
    trader, _, journal, _ = make_trader(tmp_path, nav)
    analyzer = FakePatternAnalyzer(NEVER, {"CFXUSDT": OK, "SUSDT": OK, "LUMIAUSDT": WAIT})

    SingleWorkflow(nav, trader, analyzer, ranks=[1, 2, 3, 4, 5]).run()  # type: ignore[arg-type]

    opened = [e.symbol for e in journal.load() if e.status == "open"]
    assert opened == ["CFXUSDT", "SUSDT"]
    assert len(analyzer.calls) == 5


def test_single_does_not_enter_when_none_of_the_five_is_ok(tmp_path: Path) -> None:
    nav = FakeNavigator({r: f"C{r}USDT" for r in range(1, 6)})  # type: ignore[arg-type]
    trader, gate, journal, _ = make_trader(tmp_path, nav)
    workflow = SingleWorkflow(nav, trader, FakePatternAnalyzer(WAIT), ranks=[1, 2, 3, 4, 5])  # type: ignore[arg-type]
    workflow.run()
    assert gate.plans == [] and nav.filled == []
    assert {e.status for e in journal.load()} == {"skipped"}


def test_single_skips_scanning_entirely_when_slots_are_full(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    journal.append(open_trade("CFXUSDT"))
    journal.append(open_trade("MBLUSDT"))
    analyzer = FakePatternAnalyzer(OK)
    SingleWorkflow(nav, trader, analyzer, ranks=[1]).run()  # type: ignore[arg-type]
    assert nav.calls == [] and analyzer.calls == []


def test_single_evaluates_a_pair_once_when_ranks_shift_onto_it(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "STRKUSDT", 3: "CFXUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    analyzer = FakePatternAnalyzer(WAIT)
    SingleWorkflow(nav, trader, analyzer, ranks=[1, 2, 3]).run()  # type: ignore[arg-type]
    assert len(analyzer.calls) == 2
    assert [e.symbol for e in journal.load()] == ["STRKUSDT", "CFXUSDT"]


def test_single_continues_after_a_rank_fails_to_open(tmp_path: Path) -> None:
    nav = FakeNavigator(
        {1: ScreenReadError("tidak terbaca"), 2: "CFXUSDT"},
        rows=[GainerRow(1, "STRKUSDT", 50), GainerRow(2, "CFXUSDT", 40)],
    )
    trader, _, journal, _ = make_trader(tmp_path, nav)
    SingleWorkflow(nav, trader, FakePatternAnalyzer(OK), ranks=[1, 2]).run()  # type: ignore[arg-type]
    assert [e.symbol for e in journal.load()] == ["CFXUSDT"]


def test_single_interval_repeats_monitoring(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    workflow = SingleWorkflow(
        nav,
        trader,
        FakePatternAnalyzer(WAIT),
        ranks=[1],  # type: ignore[arg-type]
        interval_s=300,
        sleep=sleep,
    )
    with pytest.raises(KeyboardInterrupt):
        workflow.run()
    assert nav.calls.count("prepare") == 2 and sleeps == [300, 300]


# --------------------------------------------------------------------------- mode banyak


def make_leader(
    tmp_path: Path, nav: FakeNavigator, clock: Clock
) -> tuple[LeaderWorkflow, FakePatternAnalyzer, AnalysisStore]:
    analyzer, store = FakePatternAnalyzer(OK), AnalysisStore()
    leader = LeaderWorkflow(
        Settings(screenshot_dir=tmp_path / "shots"),
        SopParams(),
        nav,  # type: ignore[arg-type]
        FakeMarket(),
        analyzer,
        store,
        None,
        [1, 2],  # type: ignore[arg-type]
        wall_clock=clock,
        now=lambda: NOW,
    )
    return leader, analyzer, store


def test_leader_analyzes_each_pair_once_and_reuses_within_ttl(tmp_path: Path) -> None:
    clock = Clock(1000.0)
    nav = FakeNavigator({1: "STRKUSDT", 2: "CFXUSDT"})
    leader, analyzer, store = make_leader(tmp_path, nav, clock)

    leader.run_cycle()
    clock.now += 600
    nav.symbols = {1: "CFXUSDT", 2: "STRKUSDT"}
    leader.run_cycle()

    assert len(analyzer.calls) == 2
    cfx = store.get("CFXUSDT")
    assert cfx is not None and (cfx.rank, cfx.analyzed_at) == (1, 1000.0)
    assert cfx.reading.pattern == OK


def test_leader_evaluates_a_pair_once_per_cycle_when_ranks_shift(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "STRKUSDT"})
    leader, analyzer, _ = make_leader(tmp_path, nav, Clock(1000.0))
    leader.run_cycle()
    assert len(analyzer.calls) == 1


class FakeClient:
    def __init__(self, appears_after_polls: int = 0) -> None:
        self.appears_after_polls = appears_after_polls
        self.polls = 0

    def list(self) -> list[SharedAnalysis]:
        return [SharedAnalysis(record("STRKUSDT", 1), 60.0)]

    def get(self, symbol: str) -> SharedAnalysis | None:
        self.polls += 1
        if self.polls <= self.appears_after_polls:
            return None
        return SharedAnalysis(record(symbol, 2), 60.0)


def make_follower(
    tmp_path: Path, client: FakeClient, wait_s: float = 180.0
) -> tuple[FollowerWorkflow, FakeNavigator, Journal]:
    clock = Clock()
    nav = FakeNavigator({2: "CFXUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    follower = FollowerWorkflow(
        Settings(screenshot_dir=tmp_path / "shots", follower_wait_s=wait_s),
        nav,
        trader,
        client,
        rank=2,
        sleep=clock.sleep,
        clock=clock,  # type: ignore[arg-type]
    )
    return follower, nav, journal


def test_follower_runs_sop_with_hub_reading_and_no_ai(tmp_path: Path) -> None:
    follower, nav, _ = make_follower(tmp_path, FakeClient(appears_after_polls=2))
    follower.run()
    assert follower.result is not None
    assert (follower.result.status, follower.result.verdict) == ("open", "ok")
    assert nav.filled == ["100,0"]


def test_follower_records_skip_when_hub_never_has_the_pair(tmp_path: Path) -> None:
    follower, nav, _ = make_follower(tmp_path, FakeClient(10**6), wait_s=30)
    follower.run()
    assert follower.result is not None and follower.result.status == "skipped"
    assert "Hub belum punya analisis untuk CFXUSDT" in follower.result.reason
    assert nav.filled == []


# --------------------------------------------------------------------------- jurnal


def test_journal_report_closes_finished_trades_with_capital_pct(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(
        JournalEntry(
            id="t",
            created_at=0.0,
            symbol="STRKUSDT",
            rank=1,
            status="open",
            capital_usdt=100.0,
            entry_price=1.0,
            notional=100.0,
            target_price=0.98,
            stop_price=1.02,
            deadline=4 * 3600.0,
        )
    )
    market = FakeMarket()
    market.minute_candles = [candle(1.0, 1.005, 0.979, 0.98, 1, 5)]
    JournalWorkflow(SopParams(), journal, market, wall_clock=lambda: 3600.0).run()  # type: ignore[arg-type]
    done = journal.load()[0]
    assert done.status == "target"
    assert done.pnl_capital_pct == pytest.approx(1.9)
    assert done.max_price == pytest.approx(1.005)
