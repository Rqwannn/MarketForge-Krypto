import json
from pathlib import Path
from typing import Any

import pytest

from binance_bot.analysis import VikeyPatternAnalyzer
from binance_bot.analysis.pattern import pattern_from_dict
from binance_bot.analysis.vision import extract_json
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError, ConfigError
from binance_bot.strategy import MaPattern

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
    assert reading.pattern.verdict(2) == "ok"


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

    analyzer = VikeyPatternAnalyzer(settings(**overrides), post=post)
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
        VikeyPatternAnalyzer(Settings())
    assert "sk-rahasia" not in repr(settings())
