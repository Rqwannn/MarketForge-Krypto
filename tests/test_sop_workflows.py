from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from binance_bot.analysis import PeakReading
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
    ONE_SIGN,
    Clock,
    FakeGate,
    FakeMarket,
    FakeNavigator,
    FakePeakAnalyzer,
    reading,
    record,
    rising_candles,
)

NOW = datetime(2026, 10, 11, 16, 0, 0)


def make_trader(
    tmp_path: Path,
    nav: FakeNavigator,
    market: FakeMarket | None = None,
    **params: object,
) -> tuple[SopTrader, FakeGate, Journal]:
    settings = Settings(screenshot_dir=tmp_path / "shots")
    journal, gate = Journal(tmp_path / "sop.jsonl"), FakeGate()
    trader = SopTrader(
        settings,
        SopParams(**{"capital_usdt": 1000.0, **params}),  # type: ignore[arg-type]
        nav,  # type: ignore[arg-type]
        market or FakeMarket(),  # type: ignore[arg-type]
        journal,
        gate,  # type: ignore[arg-type]
        wall_clock=lambda: NOW.timestamp(),
        now=lambda: NOW,
    )
    return trader, gate, journal


def ai(signs: object = None) -> tuple[FakePeakAnalyzer, object]:
    analyzer = FakePeakAnalyzer() if signs is None else FakePeakAnalyzer(signs)  # type: ignore[arg-type]
    return analyzer, lambda _symbol, chart: analyzer.analyze(chart)


# --------------------------------------------------------------------------- inti SOP


def test_coin_passing_all_filters_is_filled_and_paper_traded(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, journal = make_trader(tmp_path, nav)
    analyzer, source = ai()

    entry = trader.trade(1, "STRKUSDT", source)  # type: ignore[arg-type]

    assert entry.status == "open"
    assert nav.filled == ["200,0"]  # 1000 x 1% / 5% = 200 USDT pada harga bid 1,0
    plan = gate.plans[0]
    assert (plan.side, plan.leverage, plan.margin_mode) == ("SHORT", 1, "ISOLATED")
    assert plan.target_price == pytest.approx(0.96)
    assert plan.stop_price == pytest.approx(1.05)
    assert entry.deadline == pytest.approx(NOW.timestamp() + 4 * 3600)
    assert entry.signs_ai is not None and entry.signs_data is not None
    assert len(analyzer.calls) == 1
    assert [e.status for e in journal.load()] == ["open"]


@pytest.mark.parametrize(
    ("quote", "reason"),
    [
        (Quote(1.0, 1.0005, 0.0001, 12.0), "naik 12.0%"),
        (Quote(1.0, 1.0005, -0.001, 50.0), "funding"),
        (Quote(1.0, 1.01, 0.0001, 50.0), "spread"),
    ],
)
def test_free_filters_skip_before_any_ai_call(tmp_path: Path, quote: Quote, reason: str) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, _ = make_trader(tmp_path, nav, FakeMarket(quote=quote))
    analyzer, source = ai()

    entry = trader.trade(1, "STRKUSDT", source)  # type: ignore[arg-type]

    assert entry.status == "skipped"
    assert reason in entry.reason
    assert analyzer.calls == []
    assert nav.filled == [] and gate.plans == []


def test_too_few_peak_signs_from_ai_skips_without_filling(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, _ = make_trader(tmp_path, nav)
    _, source = ai(ONE_SIGN)

    entry = trader.trade(1, "STRKUSDT", source)  # type: ignore[arg-type]

    assert entry.status == "skipped"
    assert "tanda pucuk 1/4" in entry.reason
    assert entry.signs_data is not None  # data tetap dicatat sebagai pembanding
    assert nav.filled == [] and gate.plans == []


def test_data_signal_mode_decides_without_ai(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, _ = make_trader(
        tmp_path, nav, FakeMarket(candles=rising_candles()), signal_source="data"
    )
    entry = trader.trade(1, "STRKUSDT", None)
    assert entry.status == "skipped"
    assert "tanda pucuk 0/4" in entry.reason
    assert entry.signs_ai is None


def test_wrong_margin_is_warned_but_paper_trade_continues(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"}, margin=MarginSettings(False, 20))
    trader, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", ai()[1])  # type: ignore[arg-type]
    assert (entry.status, entry.margin) == ("open", "Cross 20x")


def test_same_pair_is_not_entered_twice_while_open(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, _ = make_trader(tmp_path, nav)
    assert trader.trade(1, "STRKUSDT", ai()[1]).status == "open"  # type: ignore[arg-type]
    second = trader.trade(1, "STRKUSDT", ai()[1])  # type: ignore[arg-type]
    assert "masih terbuka" in second.reason


def test_manual_quantity_is_typed_as_given(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, _ = make_trader(tmp_path, nav, capital_usdt=None, quantity=75.0)
    trader.trade(1, "STRKUSDT", ai()[1])  # type: ignore[arg-type]
    assert nav.filled == ["75,0"]


def test_three_stop_losses_today_halts_the_engine(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal = make_trader(tmp_path, nav)
    stop = JournalEntry(
        id="x",
        created_at=NOW.timestamp() - 600,
        symbol="CFXUSDT",
        rank=1,
        status="stop",
        closed_at=NOW.timestamp() - 60,
    )
    for _ in range(3):
        journal.append(stop)
    analyzer, _ = ai()

    SingleWorkflow(nav, trader, analyzer, ranks=[1]).run()  # type: ignore[arg-type]

    assert nav.calls == []
    assert analyzer.calls == []


# --------------------------------------------------------------------------- mode single


def test_single_stops_after_max_positions_and_skips_low_gain_ranks(tmp_path: Path) -> None:
    rows = [
        GainerRow(1, "STRKUSDT", 54.0),
        GainerRow(2, "CFXUSDT", 12.0),
        GainerRow(3, "MBLUSDT", 40.0),
        GainerRow(4, "ZKUSDT", 35.0),
    ]
    nav = FakeNavigator({1: "STRKUSDT", 2: "CFXUSDT", 3: "MBLUSDT", 4: "ZKUSDT"}, rows=rows)
    trader, _, journal = make_trader(tmp_path, nav, max_positions=1)
    analyzer, _ = ai()

    SingleWorkflow(nav, trader, analyzer, ranks=[2, 1, 3]).run()  # type: ignore[arg-type]

    assert "open_gainer:2" not in nav.calls  # naik 12% < 30%: tidak dibuka sama sekali
    assert "open_gainer:3" not in nav.calls  # batas 1 posisi sudah tercapai di rank 1
    assert [e.symbol for e in journal.load()] == ["STRKUSDT"]


def test_single_continues_after_a_rank_fails_to_open(tmp_path: Path) -> None:
    nav = FakeNavigator(
        {1: ScreenReadError("tidak terbaca"), 2: "CFXUSDT"},
        rows=[GainerRow(1, "STRKUSDT", 50), GainerRow(2, "CFXUSDT", 40)],
    )
    trader, _, journal = make_trader(tmp_path, nav)
    SingleWorkflow(nav, trader, ai()[0], ranks=[1, 2]).run()  # type: ignore[arg-type]
    assert [e.symbol for e in journal.load()] == ["CFXUSDT"]


# --------------------------------------------------------------------------- mode banyak


def make_leader(
    tmp_path: Path, nav: FakeNavigator, clock: Clock, market: FakeMarket | None = None
) -> tuple[LeaderWorkflow, FakePeakAnalyzer, AnalysisStore]:
    analyzer, store = FakePeakAnalyzer(), AnalysisStore()
    leader = LeaderWorkflow(
        Settings(screenshot_dir=tmp_path / "shots"),
        SopParams(),
        nav,  # type: ignore[arg-type]
        market or FakeMarket(),  # type: ignore[arg-type]
        analyzer,
        store,
        None,
        [1, 2],
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
    nav.symbols = {1: "CFXUSDT", 2: "STRKUSDT"}  # peringkat bertukar, pair sama
    leader.run_cycle()

    assert len(analyzer.calls) == 2
    cfx = store.get("CFXUSDT")
    assert cfx is not None and (cfx.rank, cfx.analyzed_at) == (1, 1000.0)
    assert list((tmp_path / "shots").glob("*_15m.json"))


def test_leader_skips_ai_for_pairs_below_min_gain(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "CFXUSDT"})
    market = FakeMarket(quote=Quote(1.0, 1.0005, 0.0001, 10.0))
    leader, analyzer, store = make_leader(tmp_path, nav, Clock(1000.0), market)
    assert leader.run_cycle() == []
    assert analyzer.calls == [] and store.all() == []


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
        return SharedAnalysis(replace(record(symbol, 2), reading=reading()), 60.0)


def make_follower(
    tmp_path: Path, client: FakeClient, wait_s: float = 180.0
) -> tuple[FollowerWorkflow, FakeNavigator, Journal]:
    clock = Clock()
    nav = FakeNavigator({2: "CFXUSDT"})
    trader, _, journal = make_trader(tmp_path, nav)
    follower = FollowerWorkflow(
        Settings(screenshot_dir=tmp_path / "shots", follower_wait_s=wait_s),
        nav,  # type: ignore[arg-type]
        trader,
        client,  # type: ignore[arg-type]
        rank=2,
        sleep=clock.sleep,
        clock=clock,
    )
    return follower, nav, journal


def test_follower_runs_sop_with_hub_reading_and_no_ai(tmp_path: Path) -> None:
    follower, nav, _ = make_follower(tmp_path, FakeClient(appears_after_polls=2))
    follower.run()

    assert follower.result is not None
    assert follower.result.status == "open"
    assert follower.result.ai_summary == reading().summary
    assert nav.filled == ["200,0"]
    assert "open_gainer:2" in nav.calls


def test_follower_records_skip_when_hub_never_has_the_pair(tmp_path: Path) -> None:
    follower, nav, journal = make_follower(tmp_path, FakeClient(10**6), wait_s=30)
    follower.run()
    assert follower.result is not None and follower.result.status == "skipped"
    assert "Hub belum punya analisis untuk CFXUSDT" in follower.result.reason
    assert nav.filled == []
    assert journal.load()[0].reason == follower.result.reason


# --------------------------------------------------------------------------- jurnal


def test_journal_report_closes_finished_trades(tmp_path: Path) -> None:
    from fakes import candle

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(
        JournalEntry(
            id="t",
            created_at=0.0,
            symbol="STRKUSDT",
            rank=1,
            status="open",
            entry_price=1.0,
            notional=200.0,
            target_price=0.96,
            stop_price=1.05,
            deadline=4 * 3600.0,
        )
    )
    market = FakeMarket()
    market.minute_candles = [candle(1.0, 1.0, 0.95, 0.96, 1, 5)]
    JournalWorkflow(SopParams(), journal, market, wall_clock=lambda: 3600.0).run()  # type: ignore[arg-type]
    assert journal.load()[0].status == "target"


def test_reading_type_is_shared_between_ai_and_hub() -> None:
    assert isinstance(record().reading, PeakReading)


def test_single_evaluates_a_pair_once_when_ranks_shift_onto_it(tmp_path: Path) -> None:
    # Uji nyata: rank #1 dan #2 sama-sama membuka STRKUSDT karena peringkat bergeser.
    nav = FakeNavigator({1: "STRKUSDT", 2: "STRKUSDT", 3: "CFXUSDT"})
    trader, _, journal = make_trader(tmp_path, nav, max_positions=3)
    analyzer, _ = ai(ONE_SIGN)

    SingleWorkflow(nav, trader, analyzer, ranks=[1, 2, 3]).run()  # type: ignore[arg-type]

    assert len(analyzer.calls) == 2  # STRKUSDT sekali, CFXUSDT sekali
    assert [e.symbol for e in journal.load()] == ["STRKUSDT", "CFXUSDT"]


def test_leader_evaluates_a_pair_once_per_cycle_when_ranks_shift(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "STRKUSDT"})
    leader, analyzer, store = make_leader(tmp_path, nav, Clock(1000.0))
    leader.run_cycle()
    assert len(analyzer.calls) == 1
    stored = store.get("STRKUSDT")
    assert stored is not None and stored.rank == 1
