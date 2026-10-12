from pathlib import Path

from binance_bot.config import DEFAULT_APP_ID, Settings, read_dotenv


def test_read_dotenv_parses_values_and_ignores_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('# komentar\n\nVIKEY_API_BASE=https://x/v1\nVIKEY_API_KEY="abc=def"\nrusak\n')
    assert read_dotenv(env) == {"VIKEY_API_BASE": "https://x/v1", "VIKEY_API_KEY": "abc=def"}


def test_analyzer_thinking_is_on_unless_explicitly_turned_off() -> None:
    assert Settings.from_env({}).analyzer_thinking is True
    assert Settings.from_env({"BOT_ANALYZER_THINKING": "false"}).analyzer_thinking is False
    assert Settings.from_env({"BOT_ANALYZER_THINKING": "OFF"}).analyzer_thinking is False


def test_read_dotenv_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_dotenv(tmp_path / "tidak-ada") == {}


def test_gateway_credentials_come_from_unprefixed_env() -> None:
    settings = Settings.from_env({"VIKEY_API_BASE": "https://x/v1", "VIKEY_API_KEY": "k"})
    assert (settings.vikey_api_base, settings.vikey_api_key) == ("https://x/v1", "k")
    assert settings.analyzer_model == "anthropic/haiku-5.5"


def test_defaults_when_env_empty() -> None:
    settings = Settings.from_env({})
    assert settings.app_bundle_id == DEFAULT_APP_ID
    assert settings.launch_timeout_s == 20.0
    assert settings.log_dir == Path("logs")


def test_env_overrides() -> None:
    settings = Settings.from_env(
        {"BOT_LAUNCH_TIMEOUT_S": "5", "BOT_LOG_LEVEL": "debug", "BOT_LOG_DIR": "/tmp/x"}
    )
    assert settings.launch_timeout_s == 5.0
    assert settings.log_level == "DEBUG"
    assert settings.log_dir == Path("/tmp/x")
