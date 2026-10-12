"""Kontrak engine <-> aplikasi desktop: log JSON, `cek`, dan argumen CLI."""

import json
import logging

from binance_bot.binance_desktop.layout import window_size_problem
from binance_bot.cli import build_parser
from binance_bot.config import Settings
from binance_bot.exceptions import MarketDataError
from binance_bot.logging_setup import JsonLinesFormatter, event
from binance_bot.macos import Rect
from binance_bot.market import Quote
from binance_bot.workflows import ReadinessWorkflow
from fakes import FakeApps, FakeMarket, FakeScreen

SECRET = "sk-rahasia-jangan-tercetak"


def log_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("bot", logging.INFO, __file__, 1, "#%d %s", (1, "WUSDT"), None)
    record.__dict__.update(extra)
    return record


def test_json_lines_include_message_and_optional_event() -> None:
    plain = json.loads(JsonLinesFormatter().format(log_record()))
    assert plain["message"] == "#1 WUSDT"
    assert plain["level"] == "INFO"
    assert "event" not in plain

    with_event = json.loads(JsonLinesFormatter().format(log_record(**event("hub", url="http://x"))))
    assert with_event["event"] == {"type": "hub", "url": "http://x"}


def test_window_size_tolerance() -> None:
    assert window_size_problem(1470, 859) is None
    assert window_size_problem(1490, 850) is None  # dalam 2%
    problem = window_size_problem(1200, 859)
    assert problem is not None and "1200x859" in problem


class BlockedMarket(FakeMarket):
    def quote(self, symbol: str) -> Quote:
        raise MarketDataError("Data pasar Binance tidak bisa diambil: internetpositif")


def readiness(
    *,
    running: bool = True,
    screen: FakeScreen | None = None,
    market: FakeMarket | None = None,
    settings: Settings | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    out: list[str] = []
    ReadinessWorkflow(
        settings or Settings(vikey_api_base="https://x", vikey_api_key=SECRET, hub_token=SECRET),
        FakeApps(running=running),
        screen or FakeScreen(),
        market or FakeMarket(),  # type: ignore[arg-type]
        accessibility=lambda: True,
        screen_capture=lambda: True,
        output=out.append,
    ).run()
    assert SECRET not in out[0]
    result = json.loads(out[0])
    return result, {c["id"]: c for c in result["checks"]}


def test_readiness_all_ok() -> None:
    result, checks = readiness()
    assert result["ok"] is True
    assert all(c["ok"] for c in checks.values())


def test_readiness_reports_each_problem_without_clicking() -> None:
    screen = FakeScreen(rect=Rect(0, 0, 1200, 700))
    result, checks = readiness(screen=screen, market=BlockedMarket(), settings=Settings())
    assert result["ok"] is False
    assert checks["binance"]["ok"] is True
    assert checks["window"]["ok"] is False
    assert checks["api"]["ok"] is False and "internetpositif" in str(checks["api"]["pesan"])
    assert checks["ai_key"]["ok"] is False and checks["ai_key"]["wajib"] is False
    assert screen.events == []  # tidak ada klik atau ketikan


def test_readiness_when_binance_is_closed() -> None:
    _, checks = readiness(running=False)
    assert checks["binance"]["ok"] is False
    assert checks["window"]["ok"] is False


def test_cli_app_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["--events", "single", "--modal", "100", "--no-fill"])
    assert args.events and args.command == "single" and args.no_fill
    assert parser.parse_args(["jurnal", "--json"]).json
    assert parser.parse_args(["cek"]).command == "cek"
