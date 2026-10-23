import json
from pathlib import Path
from typing import Any

import pytest

from binance_bot.analysis import ConsensusAnalyzer, VikeyPatternAnalyzer
from binance_bot.analysis.pattern import PatternReading, pattern_from_dict
from binance_bot.analysis.vision import extract_json
from binance_bot.binance_desktop.pattern_rules import BINANCE
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError, ConfigError
from binance_bot.strategy import MaPattern
from binance_bot.tebbit_web.pattern_rules import TEBBIT

VALID = {
    "ma7_below_ma25_count": 3,
    "ma7_below_ma25_now": True,
    "ma7_below_ma25_recent": True,
    "summary": "Garis kuning sudah tiga kali di bawah magenta.",
}


def settings(**overrides: Any) -> Settings:
    values = {"vikey_api_base": "https://gw.example/v1", "vikey_api_key": "sk-rahasia"}
    return Settings(**{**values, **overrides})


def test_valid_answer_becomes_a_pattern() -> None:
    reading = pattern_from_dict(extract_json("```json\n" + json.dumps(VALID) + "\n```"))
    assert reading.pattern == MaPattern(3, True, True)
    assert BINANCE.verdict(reading.pattern, 2) == "ok"


@pytest.mark.parametrize(
    "data",
    [
        {**VALID, "ma7_below_ma25_count": "tiga"},
        {**VALID, "ma7_below_ma25_count": 2.5},
        {**VALID, "ma7_below_ma25_count": True},
        {**VALID, "ma7_below_ma25_count": -1},
        {**VALID, "ma7_below_ma25_count": 999},
        {**VALID, "ma7_below_ma25_now": "ya"},
        {**VALID, "ma7_below_ma25_recent": None},
        {k: v for k, v in VALID.items() if k != "ma7_below_ma25_recent"},
        {**VALID, "summary": ""},
        {k: v for k, v in VALID.items() if k != "ma7_below_ma25_now"},
        "bukan objek",
    ],
)
def test_answer_that_breaks_the_schema_is_rejected(data: Any) -> None:
    with pytest.raises(AnalysisError):
        pattern_from_dict(data)


def capture(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    sent: dict[str, Any] = {}

    def post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        sent.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": json.dumps(VALID)}}]}

    analyzer = VikeyPatternAnalyzer(settings(**overrides), BINANCE.prompt, post=post)
    assert analyzer.analyze(image).pattern.below_count == 3
    return sent


def test_prompt_asks_haiku_to_follow_the_yellow_line_on_the_15m_chart(tmp_path: Path) -> None:
    sent = capture(tmp_path)
    prompt = sent["body"]["messages"][0]["content"][0]["text"]
    assert "15 MENIT" in prompt and "KUNING = MA7" in prompt and "MAGENTA" in prompt
    assert sent["body"]["model"] == "anthropic/haiku-5.5"
    assert "thinking" not in sent["body"]  # menghitung butuh thinking
    assert sent["headers"]["Authorization"] == "Bearer sk-rahasia"


def test_fast_mode_disables_thinking(tmp_path: Path) -> None:
    sent = capture(tmp_path, analyzer_thinking=False)
    assert sent["body"]["thinking"] == {"type": "disabled"}


def test_credentials_are_required_and_key_is_not_in_repr() -> None:
    with pytest.raises(ConfigError):
        VikeyPatternAnalyzer(Settings(), BINANCE.prompt)
    assert "sk-rahasia" not in repr(settings())


def test_each_platform_has_its_own_baseline_and_prompt() -> None:
    # Binance membaca MA 7/25/99; Tebbit memakai bawaan grafiknya MA 5/10/30. Dipisah supaya
    # SOP V3 bisa mengubah satu platform tanpa mengganggu yang lain.
    assert (BINANCE.fast, BINANCE.mid, BINANCE.slow) == (7, 25, 99)
    assert (TEBBIT.fast, TEBBIT.mid, TEBBIT.slow) == (5, 10, 30)
    assert "MA7" in BINANCE.prompt and "Binance" in BINANCE.prompt and "MA 5" not in BINANCE.prompt
    for text in ("MA 5", "MA 10", "MA 30", "Tebbit"):
        assert text in TEBBIT.prompt
    assert "MA7" not in TEBBIT.prompt and "MA 7" not in TEBBIT.prompt
    assert "MA25" not in TEBBIT.prompt and "MA 25" not in TEBBIT.prompt
    assert BINANCE.prompt != TEBBIT.prompt


def test_tebbit_legend_needs_its_own_baseline_not_binance_lines() -> None:
    assert TEBBIT.legend_ready({5, 10, 30})
    assert not TEBBIT.legend_ready({7, 25, 99})  # koin yang indikatornya bukan bawaan Tebbit
    assert BINANCE.legend_ready({7, 25, 99}) and not BINANCE.legend_ready({5, 10, 30})


class _Scripted:
    """AI tiruan: tiap bacaan mengembalikan (hitungan, sekarang, baru-baru ini) berikutnya."""

    def __init__(self, answers: list[tuple[int, bool, bool] | Exception]) -> None:
        self._answers = list(answers)

    def analyze(self, image: Path) -> PatternReading:
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        count, now, recent = answer
        return PatternReading(MaPattern(count, now, recent), f"hitungan {count}")


def test_consensus_takes_the_median_count_and_majority_flags() -> None:
    reads = [
        (1, False, False),
        (3, True, True),
        (4, True, True),
        (3, False, True),
        (1, False, False),
    ]
    reading = ConsensusAnalyzer(_Scripted(list(reads)), reads=5).analyze(Path("x.png"))
    assert reading.pattern == MaPattern(
        3, below_now=False, below_recent=True
    )  # median 3; 3 dari 5 recent
    assert "5 bacaan AI" in reading.summary


def test_consensus_survives_a_minority_of_failed_reads_but_not_a_majority() -> None:
    ok = [(2, False, True), (2, False, True)]
    failed = AnalysisError("jawaban rusak")
    reading = ConsensusAnalyzer(_Scripted([*ok, failed]), reads=3).analyze(Path("x.png"))
    assert reading.pattern.below_count == 2 and "2 bacaan AI" in reading.summary
    with pytest.raises(AnalysisError, match="Mayoritas bacaan AI gagal"):
        ConsensusAnalyzer(_Scripted([ok[0], failed, failed]), reads=3).analyze(Path("x.png"))


def test_consensus_is_stable_when_all_reads_agree() -> None:
    same = [(0, False, False)] * 5
    reading = ConsensusAnalyzer(_Scripted(list(same)), reads=5).analyze(Path("x.png"))
    assert BINANCE.verdict(reading.pattern, 2) == "jangan"


def test_binance_v3_lines_close_means_wait_but_tebbit_still_may_enter() -> None:
    close = pattern_from_dict({**VALID, "ma7_ma25_close": True})
    apart = pattern_from_dict({**VALID, "ma7_ma25_close": False})
    assert close.pattern == MaPattern(3, True, True, lines_close=True)
    assert BINANCE.verdict(close.pattern, 2) == "tunggu"  # garis berdekatan: jangan masuk dulu
    assert BINANCE.verdict(apart.pattern, 2) == "ok"
    assert TEBBIT.verdict(close.pattern, 2) == "ok"  # Tebbit: garis berdekatan boleh masuk
    assert "ma7_ma25_close" in BINANCE.prompt and "ma7_ma25_close" not in TEBBIT.prompt
    with pytest.raises(AnalysisError):
        pattern_from_dict({**VALID, "ma7_ma25_close": "dekat"})


class _CloseVotes:
    def __init__(self, votes: list[bool]) -> None:
        self._votes = votes

    def analyze(self, image: Path) -> PatternReading:
        return PatternReading(MaPattern(3, True, True, self._votes.pop(0)), "baca")


def test_consensus_takes_the_majority_on_lines_close() -> None:
    reading = ConsensusAnalyzer(_CloseVotes([True, False, True, True, False]), reads=5)
    assert reading.analyze(Path("x.png")).pattern.lines_close is True
    unjudged = ConsensusAnalyzer(_Scripted([(3, True, True)] * 5), reads=5)
    assert unjudged.analyze(Path("x.png")).pattern.lines_close is None


# ---------------------------------------------------------------- tanda LONG (SOP 23 Okt)

LONG_VALID = {
    "long_reversal": False,
    "long_flat": True,
    "long_far_above": False,
    "summary": "Harga mendatar lama, tiga garis menyatu.",
}


def test_long_answer_becomes_signs() -> None:
    from binance_bot.analysis.pattern import long_pattern_from_dict

    reading = long_pattern_from_dict(LONG_VALID)
    assert reading.pattern.signs == [2]


@pytest.mark.parametrize(
    "data",
    [{**LONG_VALID, "long_flat": "ya"}, {**LONG_VALID, "summary": ""}, {"long_flat": True}, []],
)
def test_long_answer_outside_the_schema_is_rejected(data: Any) -> None:
    from binance_bot.analysis.pattern import long_pattern_from_dict

    with pytest.raises(AnalysisError):
        long_pattern_from_dict(data)


def test_long_signs_take_the_majority_of_five_reads() -> None:
    from binance_bot.analysis import LongConsensusAnalyzer, LongReading
    from binance_bot.strategy import LongPattern

    answers = iter([LongPattern(True, False, False)] * 3 + [LongPattern(False, False, True)] * 2)

    class Reader:
        def analyze(self, image: Path) -> LongReading:
            return LongReading(next(answers), "bacaan")

    got = LongConsensusAnalyzer(Reader(), reads=5).analyze(Path("x.png"))
    assert got.pattern == LongPattern(True, False, False)


def test_a_failed_long_read_keeps_the_short_reading() -> None:
    from binance_bot.analysis import LongReading, read_chart

    class Short:
        def analyze(self, image: Path) -> PatternReading:
            return PatternReading(MaPattern(3, True, True), "short")

    class Broken:
        def analyze(self, image: Path) -> LongReading:
            raise AnalysisError("rusak")

    got = read_chart(Short(), Broken(), Path("x.png"), with_long=True)
    assert got.pattern == MaPattern(3, True, True) and got.long is None


def test_long_signs_are_read_only_for_tops_that_may_go_long() -> None:
    from binance_bot.analysis import LongReading, read_chart
    from binance_bot.strategy import LongPattern

    calls: list[Path] = []

    class Short:
        def analyze(self, image: Path) -> PatternReading:
            return PatternReading(MaPattern(1, False, False), "short")

    class Long:
        def analyze(self, image: Path) -> LongReading:
            calls.append(image)
            return LongReading(LongPattern(True, False, False), "berbalik")

    assert read_chart(Short(), Long(), Path("a.png"), with_long=False).long is None
    assert calls == []  # Top short saja: tanpa panggilan AI tambahan
    assert read_chart(Short(), Long(), Path("b.png"), with_long=True).long is not None


def test_the_short_prompt_is_separate_from_the_long_prompt() -> None:
    assert BINANCE.long_prompt is not None and "long_reversal" in BINANCE.long_prompt
    assert "long_" not in BINANCE.prompt  # prompt short tidak berubah
    assert "MA 5" in TEBBIT.long_prompt and "long_reversal" in TEBBIT.long_prompt
    assert "long_" not in TEBBIT.prompt
