import json
from pathlib import Path
from typing import Any

import pytest

from binance_bot.analysis import VikeyPeakAnalyzer
from binance_bot.analysis.peak import peak_from_dict
from binance_bot.analysis.vision import extract_json
from binance_bot.config import Settings
from binance_bot.exceptions import AnalysisError, ConfigError

VALID = {
    "upper_wick": True,
    "failed_new_high": True,
    "volume_declining": False,
    "big_red_after_greens": False,
    "summary": "Sumbu atas panjang setelah lonjakan.",
}


def settings(**overrides: Any) -> Settings:
    values = {"vikey_api_base": "https://gw.example/v1", "vikey_api_key": "sk-rahasia"}
    return Settings(**{**values, **overrides})


def test_valid_reading_counts_signs() -> None:
    reading = peak_from_dict(extract_json("```json\n" + json.dumps(VALID) + "\n```"))
    assert reading.signs.count == 2


@pytest.mark.parametrize(
    "data",
    [
        {**VALID, "upper_wick": "ya"},
        {**VALID, "summary": ""},
        {k: v for k, v in VALID.items() if k != "volume_declining"},
        "bukan objek",
    ],
)
def test_reading_that_breaks_the_schema_is_rejected(data: Any) -> None:
    with pytest.raises(AnalysisError):
        peak_from_dict(data)


def capture(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    image = tmp_path / "chart.png"
    image.write_bytes(b"png")
    sent: dict[str, Any] = {}

    def post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        sent.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": json.dumps(VALID)}}]}

    assert VikeyPeakAnalyzer(settings(**overrides), post=post).analyze(image).signs.upper_wick
    return sent


def test_request_carries_image_auth_and_15m_prompt_with_thinking_on(tmp_path: Path) -> None:
    sent = capture(tmp_path)
    content = sent["body"]["messages"][0]["content"]
    assert sent["headers"]["Authorization"] == "Bearer sk-rahasia"
    assert "15 MENIT" in content[0]["text"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "thinking" not in sent["body"]
    assert sent["body"]["max_tokens"] >= 4000


def test_fast_mode_disables_thinking(tmp_path: Path) -> None:
    sent = capture(tmp_path, analyzer_thinking=False)
    assert sent["body"]["thinking"] == {"type": "disabled"}


def test_credentials_are_required_and_key_is_not_in_repr() -> None:
    with pytest.raises(ConfigError):
        VikeyPeakAnalyzer(Settings())
    assert "sk-rahasia" not in repr(settings())
