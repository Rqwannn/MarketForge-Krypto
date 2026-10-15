import argparse
from pathlib import Path

import pytest

from binance_bot import cli
from binance_bot.cli import build_parser, params_from, parse_ranks
from binance_bot.exceptions import BotError


def test_parse_ranks_keeps_order_and_drops_duplicates() -> None:
    assert parse_ranks("1, 3,2,3") == [1, 3, 2]


@pytest.mark.parametrize("text", ["", "0", "6", "a", "1,,x"])
def test_parse_ranks_rejects_invalid(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_ranks(text)


def test_single_defaults_follow_sop_v2() -> None:
    args = build_parser().parse_args(["single"])
    params = params_from(args)
    assert args.ranks == [1, 2, 3, 4, 5]  # pantau top 5
    assert (params.leverage, params.margin_pct, params.max_open_positions) == (2, 50.0, 2)
    assert (params.target_pct, params.stop_pct, params.fee_pct) == (2.0, 2.0, 0.1)
    assert (params.min_crosses, params.min_gain_pct, params.max_hold_h) == (2, 0.0, 4.0)


def test_single_maps_sop_parameters() -> None:
    args = build_parser().parse_args(
        [
            "single",
            "--ranks",
            "1,2",
            "--modal",
            "1000",
            "--margin",
            "25",
            "--leverage",
            "2",
            "--sl",
            "1.5",
            "--target",
            "1",
            "--min-turun",
            "3",
            "--jumlah",
            "75",
            "--sinyal",
            "data",
            "--no-fill",
            "--interval",
            "5",
        ]
    )
    params = params_from(args)
    assert args.ranks == [1, 2] and args.no_fill and args.interval == 5
    assert (params.capital_usdt, params.margin_pct, params.stop_pct, params.target_pct) == (
        1000,
        25,
        1.5,
        1,
    )
    assert (params.min_crosses, params.order_usdt, params.signal_source) == (3, 75, "data")


def test_leader_and_follower_arguments() -> None:
    parser = build_parser()
    leader = parser.parse_args(["leader", "--interval", "15"])
    assert (leader.ranks, leader.interval, leader.min_naik) == ([1, 2, 3, 4, 5], 15.0, 0.0)
    follower = parser.parse_args(
        ["follower", "--hub", "http://10.0.0.2:8765", "--rank", "5", "--modal", "500"]
    )
    assert (follower.hub, follower.rank, follower.modal) == ("http://10.0.0.2:8765", 5, 500)


def test_unexpected_error_is_logged_with_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    class Boom:
        name = "boom"

        def run(self) -> None:
            raise RuntimeError("OCR rusak")

    monkeypatch.chdir(tmp_path)  # .env dan log_dir ("logs") ada di folder sementara
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_workflow", lambda args, settings: Boom())
    with caplog.at_level("ERROR"):
        code = cli.main(["cek"])
    assert code == 1
    record = next(r for r in caplog.records if "Galat tak terduga" in r.getMessage())
    assert "RuntimeError: OCR rusak" in record.getMessage()
    assert record.exc_info is not None  # traceback ikut tercatat


def test_cleanups_run_when_the_workflow_ends_or_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: list[str] = []

    class Workflow:
        name = "x"

        def __init__(self, fail: bool) -> None:
            self.fail = fail

        def run(self) -> None:
            cli._cleanups.append(lambda: called.append("tutup"))
            if self.fail:
                raise BotError("gagal")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **k: None)
    for fail, code in ((False, 0), (True, 1)):
        called.clear()
        monkeypatch.setattr(cli, "build_workflow", lambda args, settings, f=fail: Workflow(f))
        assert cli.main(["cek"]) == code
        assert called == ["tutup"] and cli._cleanups == []
