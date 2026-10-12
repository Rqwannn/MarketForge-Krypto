"""Kontrak engine <-> aplikasi desktop: log JSON, `cek`, dan argumen CLI."""

import json
import logging

from binance_bot.binance_desktop.layout import window_ready, window_size_problem, window_target
from binance_bot.cli import build_parser
from binance_bot.config import Settings
from binance_bot.exceptions import MarketDataError, WindowError
from binance_bot.logging_setup import JsonLinesFormatter, event
from binance_bot.macos import Rect
from binance_bot.market import Quote
from binance_bot.workflows import ReadinessWorkflow
from fakes import AREA, FakeApps, FakeMarket, FakeScreen

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


def test_window_target_uses_the_top_left_of_a_screen_that_fits() -> None:
    small, big = Rect(0, 25, 1440, 790), Rect(1440, 0, 1920, 1055)
    assert window_target(Rect(10, 30, 900, 600), [small, big]) == Rect(1440, 0, 1470, 859)
    assert window_target(Rect(10, 30, 900, 600), [small]) is None
    assert window_ready(Rect(0, 33, 1470, 859), [AREA])
    assert not window_ready(Rect(300, 33, 1470, 859), [AREA])


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
    areas: list[Rect] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    out: list[str] = []
    ReadinessWorkflow(
        settings or Settings(vikey_api_base="https://x", vikey_api_key=SECRET, hub_token=SECRET),
        FakeApps(running=running),
        screen or FakeScreen(),
        market or FakeMarket(),  # type: ignore[arg-type]
        accessibility=lambda: True,
        screen_capture=lambda: True,
        screens=lambda: areas or [AREA],
        output=out.append,
    ).run()
    assert SECRET not in out[0]
    result = json.loads(out[0])
    return result, {c["id"]: c for c in result["checks"]}


def test_readiness_all_ok() -> None:
    result, checks = readiness()
    assert result["ok"] is True
    assert all(c["ok"] for c in checks.values())


def test_readiness_accepts_a_wrong_window_size_that_the_bot_will_fix() -> None:
    screen = FakeScreen(rect=Rect(200, 100, 1200, 700))
    _, checks = readiness(screen=screen)
    assert checks["window"]["ok"] is True
    assert "otomatis" in str(checks["window"]["pesan"])
    assert screen.events == []  # cek tidak mengubah apa pun


def test_readiness_does_not_flag_a_binance_window_on_another_desktop() -> None:
    class OtherSpaceScreen(FakeScreen):
        def bounds(self, app_name: str) -> Rect:
            raise WindowError("System Events: Indeks yang tidak sah (-1719)")

    _, checks = readiness(screen=OtherSpaceScreen())
    assert checks["window"]["ok"] is True
    _, checks = readiness(screen=OtherSpaceScreen(), areas=[Rect(0, 25, 1440, 790)])
    assert checks["window"]["ok"] is False


def test_readiness_reports_each_problem_without_clicking() -> None:
    screen = FakeScreen(rect=Rect(0, 25, 1440, 790))
    result, checks = readiness(
        screen=screen, market=BlockedMarket(), settings=Settings(), areas=[Rect(0, 25, 1440, 790)]
    )
    assert result["ok"] is False
    assert checks["binance"]["ok"] is True
    assert checks["window"]["ok"] is False
    assert checks["api"]["ok"] is False and "internetpositif" in str(checks["api"]["pesan"])
    assert checks["ai_key"]["ok"] is False and checks["ai_key"]["wajib"] is False
    assert screen.events == []  # tidak ada klik atau ketikan


def test_readiness_when_binance_is_closed() -> None:
    _, checks = readiness(running=False)
    assert checks["binance"]["ok"] is False
    assert checks["window"]["ok"] is True  # layar cukup; jendela diatur saat bot mulai
    _, checks = readiness(running=False, areas=[Rect(0, 25, 1440, 790)])
    assert checks["window"]["ok"] is False
    assert "terlalu kecil" in str(checks["window"]["pesan"])


def test_cli_app_arguments() -> None:
    parser = build_parser()
    args = parser.parse_args(["--events", "single", "--modal", "100", "--no-fill"])
    assert args.events and args.command == "single" and args.no_fill
    assert parser.parse_args(["jurnal", "--json"]).json
    assert parser.parse_args(["cek"]).command == "cek"
