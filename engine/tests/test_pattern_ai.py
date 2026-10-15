import json
from pathlib import Path
from typing import Any

import pytest

from binance_bot.analysis import VikeyPatternAnalyzer
from binance_bot.analysis.pattern import pattern_from_dict
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
