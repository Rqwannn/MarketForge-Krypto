import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from binance_bot.analysis import AnalysisRecord
from binance_bot.binance_desktop.screen_text import GainerRow, MarginSettings
from binance_bot.config import Settings
from binance_bot.exceptions import (
    BotError,
    MarketDataError,
    NoHistoryError,
    PositionNotFoundError,
    SafetyError,
    ScreenReadError,
)
from binance_bot.hub import AnalysisStore, HubClient, HubServer, LeaderPlan, SharedAnalysis
from binance_bot.market import Quote
from binance_bot.strategy import Journal, JournalEntry, SopParams
from binance_bot.workflows import (
    ExampleWorkflow,
    FollowerWorkflow,
    HistoryWorkflow,
    JournalWorkflow,
    LeaderWorkflow,
    PositionsWorkflow,
    SingleWorkflow,
    SopTrader,
)
from binance_bot.workflows.positions import ManualClose
from binance_bot.workflows.sop import coin_event
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
    reading,
)

NOW = datetime(2026, 10, 12, 16, 0, 0)


def make_trader(
    tmp_path: Path,
    nav: FakeNavigator,
    market: FakeMarket | None = None,
    role: str = "single",
    **params: Any,
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
        role=role,
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
    assert nav.filled == ["100"]  # Jumlah dalam USDT (Ukuran Order): 100 x margin 50% x 2x
    plan = gate.plans[0]
    assert (plan.side, plan.leverage, plan.margin_usdt) == ("SHORT", 2, pytest.approx(50.0))
    assert plan.target_price == pytest.approx(0.97)  # jual otomatis 3% di bawah (V3)
    assert entry.stop_price is None and entry.deadline is None  # tanpa stop-loss dan batas waktu
    assert entry.pattern_ai == {"below_count": 3, "below_now": True, "below_recent": True}
    assert entry.pattern_data == {"below_count": 2, "below_now": False, "below_recent": False}
    assert entry.max_price == pytest.approx(1.0) and entry.min_price == pytest.approx(1.0)
    assert [e.status for e in journal.load()] == ["open"]


@pytest.mark.parametrize(("pattern", "word"), [(NEVER, "JANGAN"), (WAIT, "TUNGGU")])
def test_pattern_not_ok_means_no_entry(tmp_path: Path, pattern: Any, word: str) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(pattern)))
    assert entry.status == "skipped" and word in entry.reason
    assert nav.filled == [] and gate.plans == []


def test_spread_filter_rejects_after_the_pattern_is_judged(tmp_path: Path) -> None:
    # Urutan SOP: pola, lalu biaya. Koin yang spread-nya lebar tetap dibaca AI dan tampil lengkap
    # (grafik, penilaian), tapi tidak pernah dibuka.
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, gate, _, _ = make_trader(tmp_path, nav, FakeMarket(quote=Quote(1.0, 1.01, 50.0)))
    analyzer = FakePatternAnalyzer(OK)
    entry = trader.trade(1, "STRKUSDT", source(analyzer))
    assert entry.status == "skipped" and "spread" in entry.reason
    assert len(analyzer.calls) == 1 and entry.verdict == "ok" and entry.screenshots
    assert nav.filled == [] and gate.plans == []


def test_default_cost_limits_are_loose_until_the_sop_gives_numbers(tmp_path: Path) -> None:
    # SOP V2 tidak menyebut angka. Koin ETF dengan spread 0,23% tetap boleh.
    etf = FakeMarket(quote=Quote(17.16, 17.20, 8.7))
    trader, _, _, _ = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}), etf)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"
    assert SopParams().max_spread_pct == 0.3


def test_funding_rate_never_filters_a_coin(tmp_path: Path) -> None:
    # Keputusan tim 20 Okt 2026: scalping singkat, funding rate tidak dipakai menyaring koin.
    assert not hasattr(SopParams(), "min_funding_pct")
    assert "funding_rate" not in Quote.__slots__
    trader, _, _, _ = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}))
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "open" and entry.funding_rate is None
    event = coin_event(entry, SopParams())["event"]
    assert not any("funding" in key for key in [*event, *event["limits"]])


def test_pattern_reason_wins_over_cost_reason_when_pattern_is_not_ok(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    wide = FakeMarket(quote=Quote(1.0, 1.01, 50.0))
    trader, _, _, _ = make_trader(tmp_path, nav, wide)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(NEVER)))
    assert entry.verdict == "jangan" and "spread" not in entry.reason


def test_min_gain_filter_is_off_by_default_and_optional(tmp_path: Path) -> None:
    calm = FakeMarket(quote=Quote(1.0, 1.0005, 5.0))
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


def test_the_bot_sets_leverage_to_2x_before_filling(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"}, margin=MarginSettings(False, 20))
    trader, _, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert (entry.status, entry.margin) == ("open", "Cross 2x")
    assert nav.calls.index("leverage:2") < nav.calls.index("fill:100")


def test_a_refused_leverage_change_is_warned_but_paper_trade_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Refusing(FakeNavigator):
        def ensure_leverage(self, leverage: int) -> MarginSettings:
            raise ScreenReadError("Bursa tidak mengubah leverage (masih 20x, bukan 2x)")

    nav = Refusing({1: "STRKUSDT"}, margin=MarginSettings(False, 20))
    trader, _, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert (entry.status, entry.margin) == ("open", "Cross 20x")
    assert "Leverage tidak bisa diubah ke 2x" in caplog.text


# --------------------------------------------------------------------------- slot (langkah 4)


def test_the_number_of_open_positions_is_not_limited(tmp_path: Path) -> None:
    trader, gate, journal, _ = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}))
    for symbol in ("CFXUSDT", "MBLUSDT", "WUSDT"):
        journal.append(open_trade(symbol, entry_price=1.01))  # tidak rugi (harga 1.0 < masuk)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "open" and len(gate.plans) == 1


def test_second_coin_only_when_first_is_not_losing(tmp_path: Path) -> None:
    trader, _, journal, market = make_trader(tmp_path, FakeNavigator({1: "STRKUSDT"}))
    journal.append(open_trade("CFXUSDT", entry_price=1.0))
    market.quotes["CFXUSDT"] = Quote(bid=1.009, ask=1.01, change_pct=40.0)
    losing = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert "CFXUSDT sedang rugi" in losing.reason

    market.quotes["CFXUSDT"] = Quote(bid=0.99, ask=0.991, change_pct=40.0)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"


def test_old_stop_losses_no_longer_halt_the_engine(tmp_path: Path) -> None:
    # V3 tanpa stop-loss: catatan stop lama (V2) tidak menghentikan bot.
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
    assert "prepare" in nav.calls and len(analyzer.calls) == 1


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


def test_single_still_judges_and_records_coins_when_slots_are_full(tmp_path: Path) -> None:
    # Slot penuh hanya menahan posisi baru: koin tetap dibuka, dinilai AI, dan tampil di riwayat.
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    journal.append(open_trade("CFXUSDT", entry_price=0.9))  # sedang rugi: harga 1.0 > masuk
    analyzer = FakePatternAnalyzer(OK)
    SingleWorkflow(nav, trader, analyzer, ranks=[1]).run()  # type: ignore[arg-type]
    assert len(analyzer.calls) == 1
    new = next(e for e in journal.load() if e.symbol == "STRKUSDT")
    assert (new.status, new.verdict) == ("skipped", "ok")  # dinilai Layak, tapi tidak dibuka
    assert "CFXUSDT sedang rugi" in new.reason
    assert len([e for e in journal.load() if e.status == "open"]) == 1


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
        if len(sleeps) == 6:  # 5 x 60 detik menunggu, lalu putaran kedua mulai menunggu lagi
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
    # Selama menunggu, jual otomatis memeriksa posisi tiap menit (Binance: data publik).
    assert nav.calls.count("prepare") == 2 and sleeps == [60] * 6


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
    """Hub tiruan: hasil leader per Top (muncul setelah beberapa kali ditanya) + rencana."""

    def __init__(
        self,
        shared: AnalysisRecord | dict[int, AnalysisRecord] | None,
        appears_after_polls: int = 0,
        *,
        plan_done: bool = False,
    ) -> None:
        self.results = shared if isinstance(shared, dict) else ({2: shared} if shared else {})
        self.appears_after_polls = appears_after_polls
        self.plan_done = plan_done
        self.polls = 0
        self.ranks: list[int] = []

    def by_rank(self, rank: int) -> SharedAnalysis | None:
        self.polls += 1
        self.ranks.append(rank)
        record = self.results.get(rank)
        if record is None or self.polls <= self.appears_after_polls:
            return None
        return SharedAnalysis(record, 60.0)

    def plan(self) -> LeaderPlan:
        return LeaderPlan(tuple(sorted(self.results)) or (2,), self.plan_done, 5.0)


def make_follower(
    tmp_path: Path,
    client: FakeClient,
    symbols: dict[int, str | Any],
    wait_s: float = 300.0,
    ranks: Sequence[int] | None = (2,),
    **params: Any,
) -> tuple[FollowerWorkflow, FakeNavigator, Journal]:
    clock = Clock()
    nav = FakeNavigator(symbols)
    trader, _, journal, _ = make_trader(tmp_path, nav, role="follower", **params)
    follower = FollowerWorkflow(
        Settings(screenshot_dir=tmp_path / "shots", follower_wait_s=wait_s),
        nav,
        trader,
        client,
        ranks=ranks,
        sleep=clock.sleep,
        clock=clock,  # type: ignore[arg-type]
    )
    return follower, nav, journal


def test_follower_enters_the_same_coin_as_the_leader_even_after_ranks_shift(tmp_path: Path) -> None:
    # Leader menilai CFXUSDT di Top 2 (OK); saat follower masuk, CFXUSDT sudah di Top 3.
    leader_result = AnalysisRecord("CFXUSDT", 2, 1000.0, reading(OK))
    client = FakeClient(leader_result, appears_after_polls=2)
    follower, nav, _ = make_follower(tmp_path, client, {2: "WUSDT", 3: "CFXUSDT"})
    follower.run()
    assert client.ranks[:3] == [2, 2, 2]  # menunggu hasil Top 2 putaran ini
    assert follower.result is not None
    assert (follower.result.symbol, follower.result.status) == ("CFXUSDT", "open")
    assert follower.result.pattern_ai == OK.as_dict()  # pola dari AI di leader
    assert nav.filled == ["100"]
    # Dicatat dengan Top versi leader (2), bukan posisinya di daftar laptop ini saat itu (3).
    assert follower.result.rank == 2


def test_follower_with_all_tops_follows_every_top_the_leader_plays(tmp_path: Path) -> None:
    # Leader memainkan Top 1-5 (hanya 1, 2, 3 yang diwakili di hub). Pengikut bukan hanya Top 1.
    results = {
        1: AnalysisRecord("WUSDT", 1, 1000.0, reading(WAIT)),
        2: AnalysisRecord("CFXUSDT", 2, 1000.0, reading(OK)),
        3: AnalysisRecord("SUSDT", 3, 1000.0, reading(NEVER)),
    }
    client = FakeClient(results, plan_done=True)
    symbols = {1: "WUSDT", 2: "CFXUSDT", 3: "SUSDT"}
    follower, nav, journal = make_follower(tmp_path, client, symbols, ranks=None, margin_pct=25)
    follower.run()
    assert client.ranks == [1, 2, 3]  # semua Top milik leader, berurutan
    rows = {e.symbol: e for e in journal.load()}
    assert rows["WUSDT"].status == "skipped" and rows["WUSDT"].verdict == "tunggu"
    assert rows["CFXUSDT"].status == "open" and rows["CFXUSDT"].role == "follower"
    assert rows["SUSDT"].status == "skipped" and rows["SUSDT"].verdict == "jangan"
    assert nav.filled == ["50"]  # hanya koin OK yang membuka form; margin 25% x 2x x 100


def test_follower_with_all_tops_opens_every_ok_coin(tmp_path: Path) -> None:
    results = {r: AnalysisRecord(f"C{r}USDT", r, 1000.0, reading(OK)) for r in (1, 2, 3)}
    client = FakeClient(results, plan_done=True)
    symbols = {r: f"C{r}USDT" for r in (1, 2, 3)}
    follower, _nav, journal = make_follower(tmp_path, client, symbols, ranks=None)
    follower.run()
    opened = [e.symbol for e in journal.load() if e.status == "open"]
    assert opened == ["C1USDT", "C2USDT", "C3USDT"]  # jumlah posisi tidak dibatasi
    assert client.ranks == [1, 2, 3]


def test_follower_skips_a_top_the_leader_does_not_play_without_waiting(tmp_path: Path) -> None:
    # Leader hanya memainkan Top 1; tugas pengikut Top 2: dilewati, tanpa bertanya apalagi menunggu.
    client = FakeClient({1: AnalysisRecord("WUSDT", 1, 1000.0, reading(OK))}, plan_done=True)
    follower, nav, _ = make_follower(tmp_path, client, {1: "WUSDT"}, ranks=[2])
    follower.run()
    assert follower.result is None and nav.calls == []
    assert client.ranks == []


def test_each_follower_plays_only_its_own_tops_of_the_leaders_selection(tmp_path: Path) -> None:
    """Pemimpin memainkan Top 2, 4, 5; pengikut berbeda mendapat Top berbeda."""
    results = {
        2: AnalysisRecord("C2USDT", 2, 1000.0, reading(OK)),
        4: AnalysisRecord("C4USDT", 4, 1000.0, reading(OK)),
        5: AnalysisRecord("C5USDT", 5, 1000.0, reading(OK)),
    }
    symbols = {2: "C2USDT", 4: "C4USDT", 5: "C5USDT"}

    def journal_of(ranks: Sequence[int] | None, name: str) -> tuple[list[int], list[str]]:
        client = FakeClient(results, plan_done=True)
        follower, _, journal = make_follower(tmp_path / name, client, symbols, ranks=ranks)
        follower.run()
        return client.ranks, [e.symbol for e in journal.load() if e.status == "open"]

    assert journal_of([2], "a") == ([2], ["C2USDT"])  # satu Top
    assert journal_of([4, 5], "b") == ([4, 5], ["C4USDT", "C5USDT"])  # dua Top
    assert journal_of([2, 4, 5], "c")[0] == [2, 4, 5]  # tiga Top
    assert journal_of(None, "d")[0] == [2, 4, 5]  # "semua Top pemimpin"
    assert journal_of([1, 3], "e") == ([], [])  # Top yang tidak dimainkan pemimpin


def test_follower_does_not_touch_binance_when_leader_says_wait(tmp_path: Path) -> None:
    client = FakeClient(AnalysisRecord("CFXUSDT", 2, 1000.0, reading(WAIT)))
    follower, nav, journal = make_follower(tmp_path, client, {2: "CFXUSDT"})
    follower.run()
    assert nav.calls == []  # Binance tidak dibuka
    assert follower.result is not None
    assert (follower.result.status, follower.result.verdict) == ("skipped", "tunggu")
    assert "dari leader" in follower.result.reason
    assert journal.load()[-1].symbol == "CFXUSDT"


def test_follower_skips_when_the_leaders_coin_left_the_top_list(tmp_path: Path) -> None:
    client = FakeClient(AnalysisRecord("CFXUSDT", 2, 1000.0, reading(OK)))
    follower, nav, _ = make_follower(tmp_path, client, {1: "WUSDT", 2: "SUSDT"})
    follower.run()
    assert follower.result is not None and follower.result.status == "skipped"
    assert "sudah tidak di top" in follower.result.reason
    assert nav.filled == []


def test_follower_gives_up_when_leader_never_judges_its_rank(tmp_path: Path) -> None:
    follower, nav, journal = make_follower(tmp_path, FakeClient(None), {2: "CFXUSDT"}, wait_s=30)
    follower.run()
    assert follower.result is None
    assert nav.calls == ["show_app:2"]  # MarketForge tampil selama menunggu; bursa tidak disentuh
    assert journal.load() == []


def noted(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str, str]]:
    """(rank, symbol, alasan) tiap Top yang ditampilkan sebagai tidak diproses."""
    return [
        (r.event["rank"], r.event["symbol"], r.event["reason"])
        for r in caplog.records
        if hasattr(r, "event") and r.getMessage().find("tidak diproses") >= 0
    ]


def test_an_assigned_top_the_leader_does_not_play_is_shown_instead_of_vanishing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    client = FakeClient({1: AnalysisRecord("WUSDT", 1, 1000.0, reading(OK))}, plan_done=True)
    follower, _nav, journal = make_follower(tmp_path, client, {1: "WUSDT"}, ranks=[2])
    follower.run()
    assert noted(caplog) == [(2, "-", "Leader tidak memainkan Top 2 di putaran ini")]
    assert journal.load() == []


def test_a_top_the_leader_never_judged_is_shown_with_the_hub_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    follower, _nav, journal = make_follower(tmp_path, FakeClient(None), {2: "CFXUSDT"}, wait_s=30)
    follower.run()
    assert [(r, sym) for r, sym, _ in noted(caplog)] == [(2, "-")]
    assert "belum menilai Top 2" in noted(caplog)[0][2]
    assert journal.load() == []


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


def test_journal_report_json_for_the_desktop_app(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("STRKUSDT"))
    journal.append(JournalEntry(id="s", created_at=0.0, symbol="WUSDT", rank=2, reason="TUNGGU"))
    out: list[str] = []
    JournalWorkflow(
        SopParams(), journal, FakeMarket(), as_json=True, output=out.append, wall_clock=lambda: 60.0
    ).run()  # type: ignore[arg-type]
    report = json.loads(out[0])
    assert report["warning"] is None
    assert report["stats"]["open"] == 1
    assert report["stats"]["skipped"] == 1
    assert report["stats"]["required_trades"] == 50
    assert report["stats"]["verdict"].startswith("Belum cukup data")
    assert [t["symbol"] for t in report["trades"]] == ["STRKUSDT"]  # yang dilewati tidak ikut


def test_journal_report_lists_ai_analyses_with_their_chart(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    shots = ["screenshots/a_rank2.png", "screenshots/a_rank2_15m.png"]
    journal.append(
        JournalEntry(
            id="t",
            created_at=0.0,
            symbol="WUSDT",
            rank=2,
            verdict="tunggu",
            reason="pola garis kuning TUNGGU",
            ai_summary="Baru sekali di bawah.",
            screenshots=shots,
        )
    )
    journal.append(JournalEntry(id="x", created_at=1.0, symbol="XUSDT", rank=3, reason="gagal"))
    out: list[str] = []
    JournalWorkflow(
        SopParams(), journal, FakeMarket(), as_json=True, output=out.append, wall_clock=lambda: 60.0
    ).run()  # type: ignore[arg-type]
    (analysis,) = json.loads(out[0])["analyses"]  # yang tidak dinilai AI tidak ikut
    assert analysis["symbol"] == "WUSDT"
    assert analysis["verdict"] == "tunggu"
    assert analysis["chart"] == "screenshots/a_rank2_15m.png"
    assert analysis["summary"] == "Baru sekali di bawah."
    assert analysis["old_rule"] is False  # tanpa pola AI: bukan catatan aturan lama
    assert coin_event(journal.load()[0])["event"]["chart"] == "screenshots/a_rank2_15m.png"


def test_journal_report_sends_old_analyses_too_with_the_total(tmp_path: Path) -> None:
    """Riwayat lama tetap terlihat: bukan hanya 30 terakhir (aplikasi menampilkannya bertahap)."""
    journal = Journal(tmp_path / "sop.jsonl")
    for i in range(45):
        journal.append(
            JournalEntry(
                id=f"a{i}", created_at=float(i), symbol=f"C{i}USDT", rank=1, verdict="tunggu"
            )
        )
        journal.append(JournalEntry(id=f"x{i}", created_at=i + 0.5, symbol="XUSDT", rank=2))
    out: list[str] = []
    JournalWorkflow(
        SopParams(), journal, FakeMarket(), as_json=True, output=out.append, wall_clock=lambda: 99.0
    ).run()  # type: ignore[arg-type]
    report = json.loads(out[0])
    assert report["analyses_total"] == 45  # yang tidak dinilai AI tidak dihitung
    assert [a["symbol"] for a in report["analyses"]][:2] == ["C0USDT", "C1USDT"]  # yang tertua ikut
    assert len(report["analyses"]) == 45


def test_journal_report_still_works_when_binance_api_is_blocked(tmp_path: Path) -> None:
    class BlockedMarket(FakeMarket):
        def klines(self, symbol: str, interval: str, **_: object) -> list[Any]:
            raise MarketDataError("Data pasar Binance tidak bisa diambil: diblokir")

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("STRKUSDT"))
    out: list[str] = []
    JournalWorkflow(
        SopParams(),
        journal,
        BlockedMarket(),
        as_json=True,
        output=out.append,
        wall_clock=lambda: NOW.timestamp() + 600,
    ).run()  # type: ignore[arg-type]
    report = json.loads(out[0])
    assert "diblokir" in report["warning"]
    assert report["stats"]["open"] == 1


# --------------------------------------------------------------------------- event aplikasi


def test_each_evaluated_coin_emits_one_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "WUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav)
    caplog.set_level("INFO")
    trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    trader.trade(2, "WUSDT", source(FakePatternAnalyzer(WAIT)))
    events = [r.event for r in caplog.records if hasattr(r, "event")]
    assert [(e["type"], e["symbol"], e["status"], e["verdict"]) for e in events] == [
        ("coin", "STRKUSDT", "open", "ok"),
        ("coin", "WUSDT", "skipped", "tunggu"),
    ]
    assert events[0]["count_ai"] == 3 and events[0]["target_price"] is not None
    assert "TUNGGU" in events[1]["reason"]


# --------------------------------------------------------------------------- posisi dan Sell


def run_positions(journal: Journal, market: FakeMarket, close: str | None = None) -> dict[str, Any]:
    out: list[str] = []
    PositionsWorkflow(
        SopParams(),
        journal,
        market,  # type: ignore[arg-type]
        close=close,
        output=out.append,
        wall_clock=lambda: NOW.timestamp() + 600,
    ).run()
    result: dict[str, Any] = json.loads(out[0])
    return result


def test_positions_lists_open_trades_with_unrealized_result(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT", entry_price=1.0))
    market = FakeMarket(quote=Quote(bid=0.97, ask=0.98, change_pct=50.0))
    market.minute_candles = [candle(1.0, 1.005, 0.99, 0.99, 1, 1)]  # belum kena target/stop
    result = run_positions(journal, market)
    [position] = result["positions"]
    assert position["symbol"] == "CKBUSDT" and position["role"] == "single"
    assert position["price"] == 0.98
    assert position["pnl_pct"] == pytest.approx(1.9)  # 2% turun - fee 0,1%
    assert result["closed"] == []


def test_sell_closes_one_pair_at_the_ask_without_touching_binance(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT", entry_price=1.0))
    journal.append(open_trade("WUSDT", entry_price=1.0))
    market = FakeMarket(quote=Quote(bid=0.98, ask=0.99, change_pct=50.0))
    result = run_positions(journal, market, close="CKBUSDT")
    assert [c["symbol"] for c in result["closed"]] == ["CKBUSDT"]
    assert result["closed"][0]["pnl_pct"] == pytest.approx(0.9)  # beli kembali di ask 0,99
    assert [p["symbol"] for p in result["positions"]] == ["WUSDT"]
    by_symbol = {e.symbol: e for e in journal.load()}
    assert (by_symbol["CKBUSDT"].status, by_symbol["CKBUSDT"].exit_price) == ("manual", 0.99)
    assert by_symbol["WUSDT"].status == "open"

    run_positions(journal, market, close="semua")
    assert all(e.status == "manual" for e in journal.load())


def test_sell_refuses_when_binance_prices_are_unavailable(tmp_path: Path) -> None:
    class BlockedMarket(FakeMarket):
        def klines(self, symbol: str, interval: str, **_: object) -> list[Any]:
            raise MarketDataError("diblokir")

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT"))
    result = run_positions(journal, BlockedMarket(), close="semua")
    assert "tidak bisa diambil" in result["error"]
    assert journal.load()[0].status == "open"


def test_trades_record_the_role_of_the_laptop(tmp_path: Path) -> None:
    single, _, _, _ = make_trader(tmp_path / "s", FakeNavigator({1: "STRKUSDT"}))
    follower, _, _, _ = make_trader(tmp_path / "f", FakeNavigator({1: "STRKUSDT"}), role="follower")
    assert single.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).role == "single"
    assert follower.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).role == "follower"
    assert follower.skip(2, "WUSDT", "pola TUNGGU (dari leader)").role == "follower"


def test_one_follower_covers_all_five_tops_the_leader_plays_over_a_real_hub(
    tmp_path: Path,
) -> None:
    """Bug sebelumnya: pemimpin memainkan Top 1-5 tapi pengikut hanya mengikuti Top 1."""
    symbols = {r: f"C{r}USDT" for r in (1, 2, 3, 4, 5)}
    patterns = {"C1USDT": WAIT, "C2USDT": NEVER, "C3USDT": OK, "C4USDT": WAIT, "C5USDT": OK}
    clock = Clock()
    store = AnalysisStore()
    leader = LeaderWorkflow(
        Settings(screenshot_dir=tmp_path / "shots"),
        SopParams(),
        FakeNavigator(symbols),  # type: ignore[arg-type]
        FakeMarket(),
        FakePatternAnalyzer(WAIT, patterns),
        store,
        None,
        [1, 2, 3, 4, 5],  # type: ignore[arg-type]
        wall_clock=clock,
        now=lambda: NOW,
    )
    server = HubServer(store, "token-uji", host="127.0.0.1", port=0, clock=clock)
    server.start()
    try:
        leader.run_cycle()
        follower_nav = FakeNavigator(symbols)
        trader, _, journal, _ = make_trader(tmp_path / "f", follower_nav, role="follower")
        follower = FollowerWorkflow(
            Settings(screenshot_dir=tmp_path / "f" / "shots", follower_wait_s=60),
            follower_nav,
            trader,
            HubClient(f"http://127.0.0.1:{server.port}", "token-uji"),
            ranks=None,  # "semua top"
            sleep=clock.sleep,
            clock=clock,  # type: ignore[arg-type]
        )
        follower.run()
    finally:
        server.stop()
    by_symbol = {e.symbol: e for e in journal.load()}
    assert sorted(by_symbol) == ["C1USDT", "C2USDT", "C3USDT", "C4USDT", "C5USDT"]  # semua Top
    assert {s: e.status for s, e in by_symbol.items()} == {
        "C1USDT": "skipped",  # AI: tunggu
        "C2USDT": "skipped",  # AI: jangan
        "C3USDT": "open",  # AI: layak short
        "C4USDT": "skipped",
        "C5USDT": "open",
    }
    assert follower_nav.filled == ["100", "100"]


def test_example_chart_is_judged_and_kept_in_history_without_counting_as_trade(
    tmp_path: Path,
) -> None:
    image = tmp_path / "magic.png"
    image.write_bytes(b"\x89PNG")
    journal = Journal(tmp_path / "sop.jsonl")
    shots = tmp_path / "screenshots"
    ExampleWorkflow(
        image,
        "magicusdt",
        "menarik (Pak Saputra)",
        FakePatternAnalyzer(OK),
        journal,
        shots,
        SopParams(),
        wall_clock=lambda: NOW.timestamp(),
    ).run()  # type: ignore[arg-type]
    (entry,) = journal.load()
    assert (entry.symbol, entry.status, entry.role, entry.verdict) == (
        "MAGICUSDT",
        "contoh",
        "contoh",
        "ok",
    )
    assert entry.reason == "Contoh: menarik (Pak Saputra)"
    assert entry.screenshots[0].endswith("_contoh_MAGICUSDT_15m.png")
    assert Path(entry.screenshots[0]).read_bytes() == b"\x89PNG"

    out: list[str] = []
    JournalWorkflow(
        SopParams(), journal, FakeMarket(), as_json=True, output=out.append, wall_clock=lambda: 60.0
    ).run()  # type: ignore[arg-type]
    report = json.loads(out[0])
    assert report["stats"]["skipped"] == 0 and report["trades"] == []
    assert [a["symbol"] for a in report["analyses"]] == ["MAGICUSDT"]

    for symbol, name in [("MAGIC", "magic.png"), ("MAGICUSDT", "tidak-ada.png")]:
        with pytest.raises(BotError):
            ExampleWorkflow(
                tmp_path / name, symbol, "", FakePatternAnalyzer(OK), journal, shots, SopParams()
            ).run()


def test_history_delete_one_entry_or_clear_everything_except_trades(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("STRKUSDT"))
    journal.append(JournalEntry(id="s", created_at=0.0, symbol="WUSDT", rank=2, verdict="tunggu"))
    journal.append(
        JournalEntry(id="c", created_at=1.0, symbol="XUSDT", rank=0, status="contoh", role="contoh")
    )
    out: list[str] = []
    HistoryWorkflow(journal, delete_id="s", output=out.append).run()
    assert [e.id for e in journal.load()] == ["o-STRKUSDT", "c"]
    assert json.loads(out[-1]) == {"removed": 1}
    with pytest.raises(BotError):
        HistoryWorkflow(journal, delete_id="tidak-ada", output=out.append).run()

    journal.append(JournalEntry(id="s2", created_at=2.0, symbol="WUSDT", rank=2))
    HistoryWorkflow(journal, clear=True, output=out.append).run()
    assert [e.id for e in journal.load()] == ["o-STRKUSDT"]  # trade tidak ikut dibersihkan
    HistoryWorkflow(journal, delete_id="o-STRKUSDT", output=out.append).run()  # kecuali dipilih
    assert journal.load() == []
    with pytest.raises(BotError):
        HistoryWorkflow(journal)


def test_sell_works_on_exchange_without_price_history(tmp_path: Path) -> None:
    class ScreenOnly(FakeMarket):  # seperti Tebbit: harga terkini ada, candle dan funding tidak
        def klines(self, symbol: str, interval: str, **_: object) -> list[Any]:
            raise NoHistoryError("tidak punya sumber candle")

        def funding_history(self, symbol: str, start_ms: int, end_ms: int) -> list[Any]:
            raise NoHistoryError("tidak punya sumber funding")

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT"))
    result = run_positions(journal, ScreenOnly(), close="CKBUSDT")
    assert "error" not in result
    assert [c["symbol"] for c in result["closed"]] == ["CKBUSDT"]
    assert journal.load()[0].status == "manual"


# --------------------------------------------------------------------------- tampilkan MarketForge


def test_single_shows_the_app_while_ai_reads_and_returns_to_the_exchange_after(
    tmp_path: Path,
) -> None:
    nav = FakeNavigator({1: "CFXUSDT"})
    trader, gate, _, _ = make_trader(tmp_path, nav)
    SingleWorkflow(nav, trader, FakePatternAnalyzer(OK), ranks=[1]).run()  # type: ignore[arg-type]
    calls = nav.calls
    # Urutan: grafik dibuka -> MarketForge tampil selama AI membaca -> kolom jumlah diisi
    # (navigator membawa bursa ke depan lagi sebelum mengetik) -> pintu order (uji kertas).
    assert calls.index("15m") < calls.index("show_app:CFXUSDT")
    assert calls.index("show_app:CFXUSDT") < calls.index("fill:100")
    assert len(gate.plans) == 1


def test_leader_shows_the_app_while_ai_reads(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT", 2: "CFXUSDT"})
    leader, analyzer, _ = make_leader(tmp_path, nav, Clock(1000.0))
    leader.run_cycle()
    assert nav.calls.index("15m") < nav.calls.index("show_app:STRKUSDT")
    assert "show_app:CFXUSDT" in nav.calls and len(analyzer.calls) == 2


# ------------------------------------------------------------------------- order sungguhan dikunci


def test_live_orders_are_locked_everywhere() -> None:
    from binance_bot.strategy import ScreenOrderGate, live_orders_enabled
    from binance_bot.strategy.execution import OrderPlan

    assert live_orders_enabled() is False  # bawaan: uji kertas, tanpa --uang-sungguhan
    plan = OrderPlan("CFXUSDT", "100", "100", 100.0, 50.0, 1.0, 0.98, 2)

    class Presser:
        pressed = False

        def press_short(self, plan: OrderPlan) -> None:
            Presser.pressed = True

    with pytest.raises(SafetyError, match="terkunci"):
        ScreenOrderGate(Presser()).submit(plan)
    assert Presser.pressed is False


def test_dry_run_gate_finds_the_short_button_without_pressing_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from binance_bot.strategy import DryRunOrderGate
    from binance_bot.strategy.execution import OrderPlan

    plan = OrderPlan("CFXUSDT", "100", "100", 100.0, 50.0, 1.0, 0.98, 1.02, 2)
    with caplog.at_level("INFO"):
        DryRunOrderGate(lambda: (0.9, 0.51)).submit(plan)
        DryRunOrderGate(lambda: (_ for _ in ()).throw(ScreenReadError("tidak ada"))).submit(plan)
    text = caplog.text
    assert "ditemukan di (0.900, 0.510); TIDAK ditekan" in text
    assert "tidak ditemukan (uji kertas tetap jalan)" in text
    assert "[DRY RUN] Tombol Jual/Short TIDAK ditekan" in text


def test_a_rank_that_fails_to_open_still_appears_as_a_row_in_the_app(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    nav = FakeNavigator(
        {1: ScreenReadError("Yang terbuka DUSKUSDT, bukan RATSUSDT (peringkat bergeser)")},
        rows=[GainerRow(1, "RATSUSDT", 9.5)],
    )
    trader, _, _, _ = make_trader(tmp_path, nav)
    with caplog.at_level("INFO"):
        SingleWorkflow(nav, trader, FakePatternAnalyzer(OK), ranks=[1]).run()  # type: ignore[arg-type]
    rows = [r.event for r in caplog.records if getattr(r, "event", {}).get("type") == "coin"]  # type: ignore[attr-defined]
    assert rows == [
        {
            "type": "coin",
            "rank": 1,
            "symbol": "RATSUSDT",
            "status": "skipped",
            "verdict": None,
            "reason": "Yang terbuka DUSKUSDT, bukan RATSUSDT (peringkat bergeser)",
        }
    ]


def test_follower_held_by_a_losing_position_still_records_the_leaders_decisions(
    tmp_path: Path,
) -> None:
    results = {
        1: AnalysisRecord("C1USDT", 1, 1000.0, reading(OK)),
        2: AnalysisRecord("C2USDT", 2, 1000.0, reading(WAIT)),
    }
    client = FakeClient(results, plan_done=True)
    follower, nav, journal = make_follower(tmp_path, client, {1: "C1USDT", 2: "C2USDT"}, ranks=None)
    journal.append(open_trade("CFXUSDT", entry_price=0.9))  # sedang rugi
    follower.run()
    rows = {e.symbol: e for e in journal.load()}
    assert rows["C1USDT"].status == "skipped" and "CFXUSDT sedang rugi" in rows["C1USDT"].reason
    assert rows["C2USDT"].verdict == "tunggu"
    assert nav.filled == []  # bursa tidak dibuka untuk koin yang tertahan


def cycle_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [r.event for r in caplog.records if hasattr(r, "event") and r.event["type"] == "cycle"]


def test_a_follower_round_reports_its_start_and_end_like_the_other_modes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    client = FakeClient(AnalysisRecord("CFXUSDT", 2, 1000.0, reading(OK)), plan_done=True)
    follower, _nav, _journal = make_follower(tmp_path, client, {2: "CFXUSDT"})
    follower.run()
    events = cycle_events(caplog)
    assert [e["phase"] for e in events] == ["start", "done"]
    assert events[1]["opened"] == 1


def test_the_follower_round_still_reports_its_end_when_it_stops_early(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    follower, _nav, _journal = make_follower(tmp_path, FakeClient(None), {2: "CFXUSDT"}, wait_s=30)
    follower.run()  # leader tidak pernah menilai Top 2
    events = cycle_events(caplog)
    assert [e["phase"] for e in events] == ["start", "done"] and events[1]["opened"] == 0


# --------------------------------------------------------------------------- jual otomatis (V3)


class ScreenOnlyMarket(FakeMarket):
    """Seperti Tebbit: tanpa candle, harga terkini hanya dari layar."""

    def klines(self, symbol: str, interval: str, **_: object) -> list[Any]:
        raise NoHistoryError("Tebbit tidak punya sumber candle")


def test_tebbit_auto_sells_from_the_screen_price_when_the_target_is_reached(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    market = ScreenOnlyMarket()
    trader, _, journal, _ = make_trader(tmp_path, FakeNavigator({}), market)
    held = open_trade("SKDDUSDT", entry_price=1.0)  # jual otomatis di 0,98 (open_trade)
    held.created_at = NOW.timestamp() - 600
    journal.append(held)
    market.quotes["SKDDUSDT"] = Quote(bid=0.99, ask=0.991, change_pct=20.0)
    assert trader.refresh_journal()[0].status == "open"  # belum sampai target: tahan
    market.quotes["SKDDUSDT"] = Quote(bid=0.975, ask=0.976, change_pct=20.0)
    [sold] = trader.refresh_journal()
    assert (sold.status, sold.exit_price) == ("target", 0.976)
    assert journal.load()[0].status == "target"
    assert any("Tombol tutup posisi TIDAK ditekan" in r.getMessage() for r in caplog.records)


def test_real_fund_auto_sell_closes_on_the_exchange_or_keeps_the_position_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from binance_bot.strategy import execution

    monkeypatch.setattr(execution, "_live_orders", True)  # seperti --uang-sungguhan
    market = ScreenOnlyMarket()
    nav = FakeNavigator({})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    held = open_trade("SKDDUSDT", entry_price=1.0)
    held.created_at = NOW.timestamp() - 600
    held.real = True  # posisi sungguhan (tombol Short ditekan)
    journal.append(held)
    market.quotes["SKDDUSDT"] = Quote(bid=0.975, ask=0.976, change_pct=20.0)

    class Refusing(FakeNavigator):
        def close_position(self, symbol: str) -> None:
            raise ScreenReadError("Tombol Market tidak ditemukan")

    failing, _, failing_journal, _ = make_trader(tmp_path / "gagal", Refusing({}), market)
    failing_journal.append(held)
    assert failing.refresh_journal()[0].status == "open"  # gagal di bursa: tetap terbuka

    assert trader.refresh_journal()[0].status == "target"
    assert nav.calls == ["close_position:SKDDUSDT"]


# --------------------------------------------------------------------------- filter waktu


def _dated(symbol: str, day: str, status: str = "target", pnl: float = 2.9) -> JournalEntry:
    when = datetime.strptime(f"{day} 12:00", "%Y-%m-%d %H:%M").timestamp()
    entry = open_trade(symbol, entry_price=1.0)
    entry.id, entry.created_at, entry.status = f"d-{symbol}", when, status
    entry.exit_price, entry.closed_at, entry.pnl_pct, entry.pnl_usdt = 0.97, when + 600, pnl, pnl
    entry.verdict = "ok"
    return entry


def _report_for(tmp_path: Path, dari: str | None, sampai: str | None) -> dict[str, Any]:
    from binance_bot.workflows import day_bounds

    journal = Journal(tmp_path / "sop.jsonl")
    for symbol, day in (("AUSDT", "2026-10-13"), ("BUSDT", "2026-10-14"), ("CUSDT", "2026-10-15")):
        journal.append(_dated(symbol, day))
    since, until = day_bounds(dari, sampai)
    out: list[str] = []
    JournalWorkflow(
        SopParams(),
        journal,
        FakeMarket(),
        as_json=True,
        since=since,
        until=until,
        output=out.append,
        wall_clock=lambda: datetime(2026, 10, 16).timestamp(),
    ).run()  # type: ignore[arg-type]
    return json.loads(out[0])


def test_the_date_filter_covers_the_whole_report_inclusively(tmp_path: Path) -> None:
    everything = _report_for(tmp_path / "a", None, None)
    assert everything["stats"]["closed"] == 3 and len(everything["trades"]) == 3

    one_day = _report_for(tmp_path / "b", "2026-10-14", "2026-10-14")  # kedua ujung termasuk
    assert [t["symbol"] for t in one_day["trades"]] == ["BUSDT"]
    assert one_day["stats"]["closed"] == 1 and one_day["stats"]["targets"] == 1
    assert [a["symbol"] for a in one_day["analyses"]] == ["BUSDT"]
    assert one_day["stats"]["net_capital_pct"] == pytest.approx(2.9)

    since_only = _report_for(tmp_path / "c", "2026-10-14", None)
    assert [t["symbol"] for t in since_only["trades"]] == ["BUSDT", "CUSDT"]
    until_only = _report_for(tmp_path / "d", None, "2026-10-13")
    assert [t["symbol"] for t in until_only["trades"]] == ["AUSDT"]
    empty = _report_for(tmp_path / "e", "2026-10-01", "2026-10-02")
    assert empty["stats"]["closed"] == 0 and empty["trades"] == [] and empty["analyses"] == []


def test_the_date_filter_rejects_bad_dates(tmp_path: Path) -> None:
    from binance_bot.workflows import day_bounds

    with pytest.raises(BotError, match="YYYY-MM-DD"):
        day_bounds("15-10-2026", None)
    with pytest.raises(BotError, match="tidak boleh setelah"):
        day_bounds("2026-10-16", "2026-10-15")


def test_once_mode_with_real_money_keeps_watching_until_the_position_is_sold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from binance_bot.strategy import execution

    monkeypatch.setattr(execution, "_live_orders", True)  # seperti --uang-sungguhan
    market = ScreenOnlyMarket()
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    held = open_trade("SKDDUSDT", entry_price=1.0)
    held.created_at, held.real = NOW.timestamp() - 600, True
    journal.append(held)
    market.quotes["SKDDUSDT"] = Quote(bid=0.99, ask=0.995, change_pct=20.0)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:  # harga akhirnya turun ke target di pengecekan ketiga
            market.quotes["SKDDUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=20.0)

    SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=0, sleep=sleep
    ).run()  # type: ignore[arg-type]
    assert len(sleeps) == 3  # mengawasi tiap menit sampai terjual, lalu berhenti sendiri
    assert [e.status for e in journal.load() if e.symbol == "SKDDUSDT"] == ["target"]
    assert nav.calls.count("close_position:SKDDUSDT") == 1


def test_once_mode_on_paper_still_ends_after_one_round(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    journal.append(open_trade("CFXUSDT", entry_price=1.01))  # posisi uji kertas terbuka
    slept: list[float] = []
    SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=0, sleep=slept.append
    ).run()  # type: ignore[arg-type]
    assert slept == []


# ----------------------------------------------------- saldo dan jual bergiliran (uang sungguhan)


@pytest.fixture
def live_money(monkeypatch: pytest.MonkeyPatch) -> None:
    from binance_bot.strategy import execution

    monkeypatch.setattr(execution, "_live_orders", True)  # seperti --uang-sungguhan


def test_real_entry_is_skipped_when_the_available_balance_cannot_cover_the_margin(
    tmp_path: Path, live_money: None
) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = 8.0  # margin posisi 50 USDT (modal 100 x 50%)
    trader, gate, journal, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert (
        entry.status == "skipped" and "saldo tersedia 8.00 USDT kurang dari margin" in entry.reason
    )
    assert (
        nav.filled == [] and gate.plans == []
    )  # tidak ada klik Jual/Short, tidak ada posisi hantu
    assert [e.status for e in journal.load()] == ["skipped"]


def test_real_entry_is_skipped_when_the_balance_cannot_be_read(
    tmp_path: Path, live_money: None
) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = None
    trader, gate, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "skipped" and "tidak terbaca" in entry.reason and gate.plans == []


def test_real_entry_goes_ahead_when_the_balance_covers_the_margin(
    tmp_path: Path, live_money: None
) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = 58.7  # seperti saldo setelah satu posisi: cukup untuk margin 50
    trader, gate, _, _ = make_trader(tmp_path, nav)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"
    assert len(gate.plans) == 1


def test_paper_trading_does_not_need_a_balance(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = 0.0
    trader, _, _, _ = make_trader(tmp_path, nav)
    assert trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK))).status == "open"


def test_max_capital_uses_the_whole_available_balance_with_the_sop_formula(
    tmp_path: Path,
) -> None:
    # Modal Max: modal = saldo tersedia; rumus SOP tetap (margin 50% modal, 2x -> nilai = modal).
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = 107.48
    trader, gate, journal, _ = make_trader(tmp_path, nav, capital_usdt=None, capital_share=1.0)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "open" and entry.capital_usdt == 107.48
    assert nav.filled == ["107,48"] and gate.plans[0].order_text == "107,48"
    # Separuh saldo (53,74); sedikit kurang karena jumlah koin dibulatkan ke langkah koin.
    assert 53.0 < gate.plans[0].margin_usdt <= 53.74
    assert journal.load()[0].capital_usdt == 107.48  # hasil % modal dihitung dari saldo itu


@pytest.mark.parametrize(("balance", "capital"), [(500.0, 250.0), (600.0, 300.0), (750.0, 375.0)])
def test_half_capital_uses_half_of_the_available_balance(
    tmp_path: Path, balance: float, capital: float
) -> None:
    """Modal Setengah: saldo 600 -> modal 300, saldo 750 -> modal 375; rumus SOP tetap."""
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = balance
    trader, gate, journal, _ = make_trader(tmp_path, nav, capital_usdt=None, capital_share=0.5)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "open" and entry.capital_usdt == capital
    assert gate.plans[0].margin_usdt == pytest.approx(capital / 2, abs=0.1)  # separuh modal, 2x
    assert journal.load()[0].capital_usdt == capital


def test_half_capital_names_itself_when_the_balance_cannot_be_read(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = None
    trader, _, _, _ = make_trader(tmp_path, nav, capital_usdt=None, capital_share=0.5)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "skipped" and "Modal 50% saldo" in entry.reason


def test_max_capital_skips_the_coin_when_the_balance_cannot_be_read(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = None  # mis. Tebbit: saldo belum bisa dibaca dari layar
    trader, gate, _, _ = make_trader(tmp_path, nav, capital_usdt=None, capital_share=1.0)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "skipped" and "Modal Max" in entry.reason
    assert nav.filled == [] and gate.plans == []


def test_max_capital_with_an_empty_balance_says_so(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "STRKUSDT"})
    nav.available = 0.0  # mis. saldo Tebbit 0.0000 USDT
    trader, gate, _, _ = make_trader(tmp_path, nav, capital_usdt=None, capital_share=1.0)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert entry.status == "skipped" and "saldo tersedia 0 USDT" in entry.reason
    assert gate.plans == []


def _real_position(symbol: str, entry: float = 1.0) -> JournalEntry:
    held = open_trade(symbol, entry_price=entry)
    held.created_at, held.real = NOW.timestamp() - 600, True
    return held


def test_two_positions_at_target_are_sold_one_after_the_other_with_a_fresh_price_check(
    tmp_path: Path, live_money: None
) -> None:
    market = ScreenOnlyMarket()
    trader, _, journal, _ = make_trader(tmp_path, FakeNavigator({}), market)
    journal.append(_real_position("AUSDT"))
    journal.append(_real_position("BUSDT"))
    for symbol in ("AUSDT", "BUSDT"):  # keduanya sudah di target (0,98)
        market.quotes[symbol] = Quote(bid=0.97, ask=0.975, change_pct=1.0)

    order: list[str] = []

    class Seller(FakeNavigator):
        def close_position(self, symbol: str) -> None:
            order.append(symbol)
            # Sesudah posisi pertama dijual, harga posisi kedua memantul di atas target.
            market.quotes["BUSDT"] = Quote(bid=0.995, ask=1.0, change_pct=1.0)

    trader._nav = Seller({})  # type: ignore[assignment]
    done = {e.symbol: e.status for e in trader.refresh_journal()}
    assert order == ["AUSDT"]  # BUSDT tidak dijual: dibaca ulang, profit sudah tidak 3%
    assert done == {"AUSDT": "target", "BUSDT": "open"}
    assert {e.symbol: e.status for e in journal.load()} == done


def test_a_second_position_still_at_target_is_sold_after_the_first_finishes(
    tmp_path: Path, live_money: None
) -> None:
    market = ScreenOnlyMarket()
    nav = FakeNavigator({})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    journal.append(_real_position("AUSDT"))
    journal.append(_real_position("BUSDT"))
    for symbol in ("AUSDT", "BUSDT"):
        market.quotes[symbol] = Quote(bid=0.97, ask=0.975, change_pct=1.0)
    done = {e.symbol: e.status for e in trader.refresh_journal()}
    assert done == {"AUSDT": "target", "BUSDT": "target"}
    assert nav.calls.count("close_position:AUSDT") == nav.calls.count("close_position:BUSDT") == 1
    assert nav.calls.index("close_position:AUSDT") < nav.calls.index("close_position:BUSDT")


def test_a_position_another_bot_already_sold_is_not_sold_again(
    tmp_path: Path, live_money: None
) -> None:
    market = ScreenOnlyMarket()
    nav = FakeNavigator({})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    sold = _real_position("AUSDT")
    sold.status, sold.exit_price, sold.closed_at, sold.pnl_pct = "target", 0.975, 1.0, 2.5
    journal.append(sold)  # bot lain sudah menjual dan mencatatnya
    market.quotes["AUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=1.0)
    trader.refresh_journal()
    assert nav.calls == []  # tidak ada klik Market kedua untuk posisi yang sudah tertutup


def test_a_bot_waits_for_another_bot_that_is_selling(tmp_path: Path) -> None:
    import threading
    import time

    from binance_bot.exceptions import BotError
    from binance_bot.filelock import exclusive

    lock = tmp_path / "sop.sell.lock"
    held, release = threading.Event(), threading.Event()

    def other_bot() -> None:
        with exclusive(lock):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=other_bot)
    thread.start()
    assert held.wait(5)
    started = time.monotonic()
    with (
        pytest.raises(BotError, match="masih menjual"),  # bot kedua menunggu, lalu menyerah
        exclusive(lock, timeout_s=0.6, poll_s=0.1),
    ):
        raise AssertionError("tidak boleh masuk selama bot lain memegang kunci")
    assert time.monotonic() - started >= 0.5
    release.set()
    thread.join()
    with exclusive(lock, timeout_s=1):  # setelah dilepas, bot kedua bisa masuk
        pass


# ---------------------------------------------------------- putaran gagal tidak mematikan bot


class _FlakyList(FakeNavigator):
    """Daftar Futures tidak bisa dibaca (seperti 21.08: urutan di layar tidak mau berganti)."""

    def open_top_gainers(self) -> list[Any]:
        raise ScreenReadError("Daftar Futures tidak terurut dari kenaikan tertinggi")


def test_a_failed_round_does_not_stop_the_repeat_loop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    nav = _FlakyList({})
    trader, _, _, _ = make_trader(tmp_path, nav)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 20:  # cukup untuk melewati dua putaran gagal (15 menit = 15 x 60 dtk)
            raise KeyboardInterrupt

    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=900, sleep=sleep
    )  # type: ignore[arg-type]
    with pytest.raises(KeyboardInterrupt):  # berhenti hanya karena tes menghentikannya
        workflow.run()
    assert nav.calls.count("prepare") >= 2  # putaran kedua tetap dicoba
    assert "Putaran gagal: Daftar Futures tidak terurut" in caplog.text


def test_after_too_many_failed_rounds_without_positions_the_bot_stops(tmp_path: Path) -> None:
    nav = _FlakyList({})
    trader, _, _, _ = make_trader(tmp_path, nav)
    workflow = SingleWorkflow(
        nav,
        trader,
        FakePatternAnalyzer(WAIT),
        ranks=[1],
        interval_s=900,
        sleep=lambda s: None,  # type: ignore[arg-type]
    )
    with pytest.raises(BotError, match="putaran berturut-turut gagal"):
        workflow.run()
    assert nav.calls.count("prepare") == 5


def test_real_positions_keep_being_watched_even_when_every_round_fails(
    tmp_path: Path, live_money: None
) -> None:
    market = ScreenOnlyMarket()
    nav = _FlakyList({})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    journal.append(_real_position("AUSDT"))
    market.quotes["AUSDT"] = Quote(bid=0.99, ask=0.995, change_pct=1.0)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 40:  # lebih dari 5 putaran gagal: bot tidak boleh berhenti sendiri
            market.quotes["AUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=1.0)
        if len(sleeps) == 60:
            raise KeyboardInterrupt

    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=900, sleep=sleep
    )  # type: ignore[arg-type]
    # Setelah terjual tidak ada posisi sungguhan lagi: 5 putaran gagal beruntun boleh menghentikan
    # bot (putaran setelah jual dimulai segera, jadi batas itu bisa tercapai sebelum sleep ke-40).
    with pytest.raises((KeyboardInterrupt, BotError)):
        workflow.run()
    assert [e.status for e in journal.load()] == [
        "target"
    ]  # tetap terjual walau putaran gagal terus
    assert nav.calls.count("close_position:AUSDT") == 1


def test_once_mode_failure_is_reported_after_real_positions_are_safe(
    tmp_path: Path, live_money: None
) -> None:
    market = ScreenOnlyMarket()
    nav = _FlakyList({})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    journal.append(_real_position("AUSDT"))
    market.quotes["AUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=1.0)
    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=0, sleep=lambda s: None
    )  # type: ignore[arg-type]
    with pytest.raises(ScreenReadError, match="tidak terurut"):
        workflow.run()
    assert [e.status for e in journal.load()] == [
        "target"
    ]  # posisi dijual dulu, baru gagal dilaporkan


def test_coin_events_and_the_history_carry_the_figures_behind_the_decision(tmp_path: Path) -> None:
    """Kartu "kenapa" di aplikasi memakai angka ini: kenaikan, spread, jarak MA, batas."""
    journal = Journal(tmp_path / "sop.jsonl")
    entry = JournalEntry(
        id="g",
        created_at=0.0,
        symbol="GTCUSDT",
        rank=2,
        verdict="ok",
        reason="spread 0.400% > 0.3%",
        change_pct=20.5,
        spread_pct=0.4,
        ma_gap_pct=-6.9,
        pattern_ai={"below_count": 3, "below_now": False, "below_recent": True},
        pattern_data={"below_count": 3},
        leverage=2,
    )
    journal.append(entry)
    params = SopParams(max_spread_pct=0.5)

    live = coin_event(entry, params)["event"]
    assert live["change_pct"] == 20.5 and "funding_rate" not in live
    assert live["spread_pct"] == 0.4 and live["ma_gap_pct"] == -6.9
    assert live["ai"] == {"below_count": 3, "below_now": False, "below_recent": True}
    assert live["limits"]["max_spread_pct"] == 0.5 and live["limits"]["min_crosses"] == 2
    assert "min_funding_pct" not in live["limits"]
    assert "limits" not in coin_event(entry)["event"]  # tanpa params: aplikasi pakai bawaan

    out: list[str] = []
    JournalWorkflow(
        params, journal, FakeMarket(), as_json=True, output=out.append, wall_clock=lambda: 60.0
    ).run()  # type: ignore[arg-type]
    (analysis,) = json.loads(out[0])["analyses"]
    assert "funding_rate" not in analysis and analysis["ma_gap_pct"] == -6.9
    assert analysis["limits"]["max_spread_pct"] == params.max_spread_pct
    assert analysis["data"] == {"below_count": 3}


def test_journal_rewrite_retries_while_windows_holds_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uji nyata: WinError 32 saat halaman Hasil uji menulis ulang jurnal yang sedang dibuka bot."""
    import binance_bot.strategy.journal as journal_module

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(JournalEntry(id="a", created_at=0.0, symbol="AUSDT", rank=1))
    real_replace = journal_module.os.replace
    attempts: list[int] = []

    def flaky(src: Path, dst: Path) -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(32, "being used by another process")
        real_replace(src, dst)

    monkeypatch.setattr(journal_module.os, "replace", flaky)
    monkeypatch.setattr(journal_module.time, "sleep", lambda _s: None)
    journal.save([JournalEntry(id="b", created_at=1.0, symbol="BUSDT", rank=2)])
    assert len(attempts) == 3
    assert [e.id for e in journal.load()] == ["b"]
    assert not list(tmp_path.glob("*.tmp"))


def test_journal_rewrite_gives_up_after_many_attempts_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import binance_bot.strategy.journal as journal_module

    journal = Journal(tmp_path / "sop.jsonl")

    def locked(src: Path, dst: Path) -> None:
        raise PermissionError(32, "locked")

    monkeypatch.setattr(journal_module.os, "replace", locked)
    monkeypatch.setattr(journal_module.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        journal.save([JournalEntry(id="b", created_at=1.0, symbol="BUSDT", rank=2)])
    assert not list(tmp_path.glob("*.tmp"))  # berkas sementara tidak tertinggal


def test_journal_load_and_append_retry_a_locked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import binance_bot.strategy.journal as journal_module

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(JournalEntry(id="a", created_at=0.0, symbol="AUSDT", rank=1))
    real_read = Path.read_text
    calls: list[int] = []

    def flaky_read(self: Path, *args: object, **kwargs: object) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(32, "locked")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky_read)
    monkeypatch.setattr(journal_module.time, "sleep", lambda _s: None)
    assert [e.id for e in journal.load()] == ["a"]
    assert len(calls) == 2


class ClosedScreenMarket(FakeMarket):
    """Seperti Tebbit saat layar tidak dibuka: tanpa candle, dan harga tidak bisa dibaca."""

    reachable = False

    def quote(self, symbol: str) -> Quote:
        if not self.reachable:
            raise MarketDataError(f"{symbol} tidak sedang terbuka di Tebbit, harga tidak terbaca")
        return super().quote(symbol)

    def klines(self, symbol: str, interval: str, **_: object) -> list[Any]:
        raise NoHistoryError("tidak punya sumber candle")


def test_positions_list_uses_the_last_read_price_when_the_screen_is_not_open(
    tmp_path: Path,
) -> None:
    """Uji nyata (Tebbit): daftar Posisi kosong untuk harga sekarang dan hasil sementara."""
    journal = Journal(tmp_path / "sop.jsonl")
    entry = open_trade("CKBUSDT", entry_price=1.0)
    entry.last_price, entry.last_price_at = 0.98, NOW.timestamp()
    journal.append(entry)
    journal.append(open_trade("WUSDT"))  # belum pernah dicek
    result = run_positions(journal, ClosedScreenMarket())
    known, unknown = result["positions"]
    assert known["price"] == 0.98 and known["price_stale"] is True
    assert known["price_at"] == NOW.timestamp()
    assert known["pnl_pct"] == pytest.approx(1.9)  # 2% turun - fee 0,1%
    assert unknown["price"] is None and unknown["pnl_pct"] is None
    assert unknown["price_stale"] is False


def test_positions_list_marks_a_fresh_price_as_not_stale(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT"))
    market = ClosedScreenMarket(quote=Quote(bid=0.97, ask=0.98, change_pct=1.0))
    market.reachable = True
    [position] = run_positions(journal, market)["positions"]
    assert position["price"] == 0.98 and position["price_stale"] is False
    assert position["price_at"] == NOW.timestamp() + 600


def test_price_check_remembers_the_price_for_the_positions_list(tmp_path: Path) -> None:
    """Tombol Cek harga Tebbit (atau bot yang berjalan) menyimpan harga yang dibaca dari layar."""
    from binance_bot.workflows.sop import refresh_by_price

    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("CKBUSDT", entry_price=1.0))
    market = ClosedScreenMarket(quote=Quote(bid=0.99, ask=0.995, change_pct=1.0))
    market.reachable = True
    refresh_by_price(journal, market, 0.1, NOW.timestamp())  # type: ignore[arg-type]
    saved = journal.load()[0]
    assert saved.status == "open" and saved.last_price == 0.995
    assert saved.last_price_at == NOW.timestamp()
    market.reachable = False  # layar ditutup lagi: daftar Posisi memakai harga tersimpan
    [position] = run_positions(journal, market)["positions"]
    assert position["price"] == 0.995 and position["price_stale"] is True


# ------------------------------------------------- kartu posisi, tutup manual, posisi yang hilang


def test_read_only_listing_never_writes_the_journal(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    held = _real_position("ARIAUSDT", entry=1.0)
    held.max_price = 1.32  # sempat naik 32% melawan short
    journal.append(held)
    before = journal.path.read_bytes()
    out: list[str] = []
    market = FakeMarket(quote=Quote(bid=1.04, ask=1.05, change_pct=1.0))
    PositionsWorkflow(
        SopParams(),
        journal,
        market,
        read_only=True,
        output=out.append,  # type: ignore[arg-type]
    ).run()
    [p] = json.loads(out[0])["positions"]
    assert journal.path.read_bytes() == before  # aman dijalankan tiap menit di samping bot
    assert p["pnl_pct"] == pytest.approx(-5.1)
    assert p["pnl_usdt"] == pytest.approx(-5.1)  # nilai posisi 100 USDT
    assert p["worst_pnl_pct"] == pytest.approx(-32.1)  # rugi terdalam sejak masuk
    assert p["to_target_pct"] == pytest.approx(100 * (1.05 - 0.98) / 1.05)


def _record_manual(journal: Journal, manual: ManualClose) -> dict[str, Any]:
    out: list[str] = []
    PositionsWorkflow(
        SopParams(),
        journal,
        FakeMarket(),  # type: ignore[arg-type]
        manual=manual,
        output=out.append,
        wall_clock=lambda: NOW.timestamp(),
    ).run()
    result: dict[str, Any] = json.loads(out[0])
    return result


def test_a_manual_close_is_recorded_with_the_exchange_result(tmp_path: Path) -> None:
    # Seperti ARIA: ditutup sendiri di Binance di 0,04747, PNL terealisasi +0,60 USDT.
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(_real_position("ARIAUSDT", entry=0.0478091))
    journal.append(_real_position("BTWUSDT"))
    result = _record_manual(journal, ManualClose("ARIAUSDT", 0.04747, 0.60))
    aria = next(e for e in journal.load() if e.symbol == "ARIAUSDT")
    assert (aria.status, aria.exit_price, aria.pnl_usdt) == ("manual", 0.04747, 0.60)
    assert aria.pnl_pct == pytest.approx(0.6)  # 0,60 dari nilai posisi 100 USDT
    assert "Ditutup manual" in aria.reason
    assert [p["symbol"] for p in result["positions"]] == ["BTWUSDT"]  # posisi lain tetap


def test_a_manual_close_without_the_exchange_result_uses_the_price(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(_real_position("ARIAUSDT", entry=1.0))
    _record_manual(journal, ManualClose("ARIAUSDT", 0.99))
    [aria] = journal.load()
    assert aria.pnl_pct == pytest.approx(0.9)  # turun 1% - fee 0,1%


def test_a_manual_close_for_a_pair_without_an_open_position_is_refused(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(_real_position("ARIAUSDT"))
    result = _record_manual(journal, ManualClose("BTWUSDT", 1.0))
    assert "Tidak ada posisi terbuka untuk BTWUSDT" in result["error"]
    assert [e.status for e in journal.load()] == ["open"]


def test_a_position_missing_on_the_exchange_is_reported_not_closed(
    tmp_path: Path, live_money: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Ditutup manual di Binance, jurnal masih terbuka: bot memberi tahu aplikasi, tidak mencatat.
    market = ScreenOnlyMarket()

    class Gone(FakeNavigator):
        def close_position(self, symbol: str) -> None:
            raise PositionNotFoundError(f"Posisi {symbol} tidak ada di tab Posisi Binance")

    trader, _, journal, _ = make_trader(tmp_path, Gone({}), market)
    journal.append(_real_position("ARIAUSDT"))
    market.quotes["ARIAUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=1.0)
    caplog.set_level("INFO")
    trader.refresh_journal()
    events = [r.event for r in caplog.records if hasattr(r, "event")]
    assert {"type": "position_missing", "symbol": "ARIAUSDT"} in events
    assert [e.status for e in journal.load()] == ["open"]


# --------------------------------------------------------------------------- beberapa bot, momentum


def test_journal_changes_are_written_over_entries_another_bot_added_meanwhile(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "sop.jsonl")
    journal.append(open_trade("AUSDT"))
    held = journal.load()[0]
    journal.append(open_trade("BUSDT"))  # bot lain masuk posisi sementara bot ini menjual
    held.status, held.exit_price = "target", 0.98

    journal.replace([held])

    assert [(e.symbol, e.status) for e in journal.load()] == [
        ("AUSDT", "target"),
        ("BUSDT", "open"),
    ]


def test_after_a_sale_at_target_the_next_round_starts_at_once_with_that_coin_first(
    tmp_path: Path,
) -> None:
    """Momentum: terjual di target -> putaran baru tanpa menunggu sisa jeda, dan koin itu dicek
    ulang lebih dulu walau bukan Top yang dipilih (selama masih di daftar). Uji kertas."""
    market = ScreenOnlyMarket()
    nav = FakeNavigator({1: "AUSDT", 2: "BUSDT", 3: "CUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav, market)
    held = open_trade("CUSDT")  # jual otomatis di 0,98
    held.created_at = NOW.timestamp() - 600
    journal.append(held)
    market.quotes["CUSDT"] = Quote(bid=0.995, ask=1.0, change_pct=9.0)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:  # harga CUSDT turun ke target selama menunggu
            market.quotes["CUSDT"] = Quote(bid=0.97, ask=0.975, change_pct=9.0)
        else:
            raise KeyboardInterrupt

    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], interval_s=900, sleep=sleep
    )  # type: ignore[arg-type]
    with pytest.raises(KeyboardInterrupt):
        workflow.run()

    assert sleeps == [60.0, 60.0]  # tidak menunggu 15 menit penuh setelah terjual
    second = nav.calls[nav.calls.index("open_symbol:AUSDT") + 1 :]
    assert [c for c in second if c.startswith("open_symbol")] == [
        "open_symbol:CUSDT",
        "open_symbol:AUSDT",
    ]
    assert journal.load()[0].status == "target"
    assert nav.outside_turns() == []  # setiap aksi layar di dalam giliran


def test_a_sold_coin_that_left_the_top_5_is_rechecked_through_search(tmp_path: Path) -> None:
    """Koin yang baru terjual sudah keluar Top 5: dibuka lewat pencarian, sebelum Top pilihan."""
    nav = FakeNavigator({1: "AUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav)
    workflow = SingleWorkflow(nav, trader, FakePatternAnalyzer(WAIT), ranks=[1])  # type: ignore[arg-type]
    workflow._remember(["ZUSDT"])

    workflow.run_cycle()

    opens = [c for c in nav.calls if c.split(":")[0] in ("open_symbol", "search_symbol")]
    assert opens == ["open_symbol:ZUSDT", "search_symbol:ZUSDT", "open_symbol:AUSDT"]
    assert nav.outside_turns() == []


def test_a_sold_coin_is_rechecked_once_per_new_15m_candle_for_two_hours(tmp_path: Path) -> None:
    """Keputusan 21 Okt: cek ulang tiap candle 15 menit baru, bukan candle yang sama, 2 jam."""
    from binance_bot.workflows.single import _candle
    from fakes import Clock

    clock = Clock(900_000.0 + 100)  # 100 detik setelah candle mulai
    nav = FakeNavigator({1: "AUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav)
    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], sleep=clock.sleep, clock=clock
    )  # type: ignore[arg-type]
    workflow._remember(["AUSDT"])
    workflow._checked["AUSDT"] = _candle(clock())  # sudah dicek langsung setelah terjual

    workflow._wait_and_watch(3 * 3600)

    # Candle berikutnya mulai 800 detik lagi; tiap candle baru dicek sekali sampai 2 jam habis.
    assert nav.calls.count("open_symbol:AUSDT") == 7
    assert "AUSDT" not in workflow._watch


def test_a_coin_that_used_up_its_reentries_is_not_rechecked(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "BUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    for hour in (9, 10, 11, 12):  # masuk pertama + 3 kali masuk ulang hari ini
        journal.append(_entered("AUSDT", NOW.replace(hour=hour)))
    workflow = SingleWorkflow(nav, trader, FakePatternAnalyzer(WAIT), ranks=[1])  # type: ignore[arg-type]
    workflow._remember(["AUSDT"])

    workflow.run_cycle()

    assert not any("AUSDT" in c for c in nav.calls)  # layar dan AI tidak dipakai untuknya
    assert "AUSDT" not in workflow._watch


def _entered(symbol: str, when: datetime, *, real: bool = False) -> JournalEntry:
    entry = open_trade(symbol)
    entry.id, entry.created_at = f"{when:%H%M%S}_{symbol}", when.timestamp()
    entry.status, entry.real = "target", real
    return entry


def test_the_same_coin_is_entered_at_most_four_times_a_day(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "AUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    for hour in (9, 10, 11, 12):  # masuk pertama + 3 kali masuk ulang hari ini
        journal.append(_entered("AUSDT", NOW.replace(hour=hour)))
    analyzer = FakePatternAnalyzer(OK)

    entry = trader.trade(1, "AUSDT", source(analyzer))

    assert entry.status == "skipped"
    assert "sudah masuk 4 kali hari ini" in entry.reason
    assert analyzer.calls == []  # grafik dan AI tidak dibaca untuk koin yang tidak dimasuki


def test_reentry_count_ignores_yesterday_and_the_other_money_mode(tmp_path: Path) -> None:
    nav = FakeNavigator({1: "AUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    for hour in (9, 10, 11):
        journal.append(_entered("AUSDT", NOW.replace(hour=hour)))
    journal.append(_entered("AUSDT", NOW.replace(hour=12), real=True))  # uang sungguhan
    journal.append(_entered("AUSDT", NOW.replace(day=NOW.day - 1)))  # kemarin

    entry = trader.trade(1, "AUSDT", source(FakePatternAnalyzer(OK)))

    assert entry.status == "open"  # baru 3 kali uji kertas hari ini


def test_real_money_is_never_sent_unless_leverage_is_proven_to_be_2x(
    tmp_path: Path, live_money: None
) -> None:
    """Uji nyata 21 Okt: leverage tidak terbaca, order tetap dikirim dan terbuka 20x."""

    class Refusing(FakeNavigator):
        def ensure_leverage(self, leverage: int) -> MarginSettings:
            raise ScreenReadError("Tombol leverage di atas form order tidak ditemukan")

    for margin in (MarginSettings(False, 20), MarginSettings(False, None)):  # 20x, atau tak terbaca
        nav = Refusing({1: "STRKUSDT"}, margin=margin)
        trader, gate, _, _ = make_trader(tmp_path, nav)
        entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
        assert entry.status == "skipped" and "leverage harus terbukti 2x" in entry.reason
        assert nav.filled == [] and gate.plans == [] and entry.real is False


def test_real_money_is_sent_once_leverage_is_confirmed_at_2x(
    tmp_path: Path, live_money: None
) -> None:
    nav = FakeNavigator({1: "STRKUSDT"}, margin=MarginSettings(False, 20))  # bot mengubah ke 2x
    trader, gate, _, _ = make_trader(tmp_path, nav)
    entry = trader.trade(1, "STRKUSDT", source(FakePatternAnalyzer(OK)))
    assert (entry.status, entry.real) == ("open", True) and len(gate.plans) == 1


def test_a_restarted_bot_keeps_rechecking_coins_sold_at_target_in_the_last_two_hours(
    tmp_path: Path,
) -> None:
    nav = FakeNavigator({1: "AUSDT"})
    trader, _, journal, _ = make_trader(tmp_path, nav)
    for symbol, minutes_ago in (("BUSDT", 30), ("CUSDT", 150)):  # 30 menit dan 2,5 jam lalu
        sold = _entered(symbol, NOW.replace(hour=12))
        sold.closed_at = NOW.timestamp() - minutes_ago * 60
        journal.append(sold)
    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], clock=lambda: NOW.timestamp()
    )  # type: ignore[arg-type]

    workflow._resume_watch()

    assert workflow._watch == {"BUSDT": NOW.timestamp() - 30 * 60 + 7200}


def test_a_failed_recheck_is_retried_next_candle_not_every_minute(tmp_path: Path) -> None:
    """Uji nyata 21 Okt: daftar Futures gagal dibaca (banner), cek ulang dicoba lagi tiap menit."""
    from binance_bot.workflows.single import _candle
    from fakes import Clock

    class Broken(FakeNavigator):
        def open_top_gainers(self) -> list[GainerRow]:
            self.calls.append("open_top_gainers")
            raise ScreenReadError("Daftar Futures tidak terurut")

    clock = Clock(900_000.0 + 100)
    nav = Broken({1: "AUSDT"})
    trader, _, _, _ = make_trader(tmp_path, nav)
    workflow = SingleWorkflow(
        nav, trader, FakePatternAnalyzer(WAIT), ranks=[1], sleep=clock.sleep, clock=clock
    )  # type: ignore[arg-type]
    workflow._remember(["AUSDT"])
    workflow._checked["AUSDT"] = _candle(clock())

    workflow._wait_and_watch(2400)  # 40 menit: dua candle baru (tanpa perbaikan: tiap menit)

    assert nav.calls.count("open_top_gainers") == 2
