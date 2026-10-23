import argparse
import sys
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


def test_single_defaults_follow_sop_v3() -> None:
    args = build_parser().parse_args(["single"])
    params = params_from(args)
    assert args.ranks == [1, 2, 3, 4, 5]  # pantau top 5
    assert (params.leverage, params.margin_pct) == (2, 50.0)
    assert (params.target_pct, params.fee_pct) == (3.0, 0.1)  # tanpa stop-loss dan batas waktu
    assert (params.min_crosses, params.min_gain_pct) == (2, 0.0)


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
    assert (params.capital_usdt, params.margin_pct, params.target_pct) == (1000, 25, 1)
    assert (params.min_crosses, params.order_usdt, params.signal_source) == (3, 75, "data")


def test_leader_and_follower_arguments() -> None:
    parser = build_parser()
    leader = parser.parse_args(["leader", "--interval", "15"])
    assert (leader.ranks, leader.interval, leader.min_naik) == ([1, 2, 3, 4, 5], 15.0, 0.0)
    follower = parser.parse_args(
        ["follower", "--hub", "http://10.0.0.2:8765", "--rank", "5", "--modal", "500"]
    )
    assert (follower.hub, follower.rank, follower.modal) == ("http://10.0.0.2:8765", 5, 500)


@pytest.mark.parametrize("command", ["single", "follower"])
def test_modal_max_means_the_whole_available_balance(command: str) -> None:
    params = params_from(build_parser().parse_args([command, "--modal", "Max"]))
    assert (params.capital_share, params.capital_usdt) == (1.0, None)
    params.validate()  # Max cukup sebagai modal
    assert (
        params_from(build_parser().parse_args([command, "--modal", "150,5"])).capital_usdt == 150.5
    )
    with pytest.raises(SystemExit):
        build_parser().parse_args([command, "--modal", "semua"])


@pytest.mark.parametrize("command", ["single", "follower"])
def test_modal_setengah_means_half_of_the_available_balance(command: str) -> None:
    params = params_from(build_parser().parse_args([command, "--modal", "Setengah"]))
    assert (params.capital_share, params.capital_usdt) == (0.5, None)
    params.validate()


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


def test_app_paths_in_dotenv_reach_the_os_layer_but_the_os_environment_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOT_APP_PATH", raising=False)
    monkeypatch.setenv("BOT_CHROME_PATH", r"C:\dari\os\chrome.exe")
    cli._export_path_settings(
        {"BOT_APP_PATH": r"D:\Binance\Binance.exe", "BOT_CHROME_PATH": r"C:\dari\env\chrome.exe"}
    )
    import os

    assert os.environ["BOT_APP_PATH"] == r"D:\Binance\Binance.exe"
    assert os.environ["BOT_CHROME_PATH"] == r"C:\dari\os\chrome.exe"  # variabel OS menang


def test_manual_close_arguments() -> None:
    from binance_bot.workflows.positions import ManualClose

    args = build_parser().parse_args(
        ["posisi", "--catat-manual", "ariausdt", "--harga", "0,04747", "--hasil", "+0,60"]
    )
    assert cli._manual_close(args) == ManualClose("ARIAUSDT", 0.04747, 0.60)
    with pytest.raises(BotError, match="--harga"):
        cli._manual_close(build_parser().parse_args(["posisi", "--catat-manual", "ARIAUSDT"]))
    with pytest.raises(SystemExit):
        build_parser().parse_args(["posisi", "--catat-manual", "ARIAUSDT", "--harga", "0"])
    assert cli._manual_close(build_parser().parse_args(["posisi", "--baca"])) is None


def test_tops_per_direction_cutloss_and_time_limit_options() -> None:
    default = params_from(build_parser().parse_args(["single", "--modal", "100"]))
    assert (default.short_tops, default.long_tops) == (None, ())  # short di semua Top
    assert (default.stop_pct, default.time_limit) == (None, False)
    args = build_parser().parse_args(
        [
            *("single", "--modal", "100", "--top-short", "2,3,4", "--top-long", "1,5"),
            *("--cutloss", "10", "--batas-waktu"),
        ]
    )
    params = params_from(args)
    assert (params.short_tops, params.long_tops, params.tops) == (
        (2, 3, 4),
        (1, 5),
        (1, 2, 3, 4, 5),
    )
    assert [params.sides_for(r) for r in (1, 2, 5)] == [("long",), ("short",), ("long",)]
    assert (params.stop_pct, params.time_limit, params.long_target_pct) == (10.0, True, 4.0)
    long_only = params_from(
        build_parser().parse_args(["single", "--modal", "1", "--top-long", "1"])
    )
    assert long_only.sides_for(1) == ("long",) and long_only.sides_for(2) == ()


def test_the_leader_and_follower_accept_tops_per_direction() -> None:
    # Pemimpin membaca tanda LONG hanya di Top long; pengikut memakai pembagian yang sama.
    leader = build_parser().parse_args(["leader", "--top-short", "2,4,5", "--top-long", "1,2,3"])
    assert (leader.top_short, leader.top_long) == ([2, 4, 5], [1, 2, 3])
    follower = build_parser().parse_args(["follower", "--modal", "100", "--top-long", "1"])
    assert params_from(follower).sides_for(1) == ("long",)


@pytest.mark.skipif(sys.platform != "darwin", reason="membangun sistem macOS")
@pytest.mark.parametrize(
    "argv",
    [
        ["leader", "--top-short", "2,4,5", "--top-long", "1,2,3"],
        ["single", "--modal", "100", "--top-short", "2,3,4", "--top-long", "1,5"],
        ["follower", "--modal", "100", "--semua", "--top-long", "1", "--cutloss", "10"],
        ["--bursa", "tebbit", "single", "--modal", "100", "--top-long", "1,2"],
    ],
)
def test_every_mode_builds_with_tops_per_direction(argv: list[str], tmp_path: Path) -> None:
    # Uji nyata 23 Okt: pemimpin dengan pembagian Top gagal dijalankan (mewajibkan modal).
    from binance_bot.cli import build_workflow
    from binance_bot.config import Settings

    settings = Settings(
        journal_path=tmp_path / "sop.jsonl",
        screenshot_dir=tmp_path,
        hub_token="token-uji",
        hub_url="http://127.0.0.1:1",
        vikey_api_base="https://gw.example/v1",
        vikey_api_key="sk-uji",
    )
    workflow = build_workflow(build_parser().parse_args(argv), settings)
    if argv[0] == "leader":
        assert workflow._long_analyzer is not None  # type: ignore[attr-defined]
        assert workflow._ranks == [1, 2, 3, 4, 5]  # type: ignore[attr-defined]
    if "single" in argv:
        expected = [1, 2, 3, 4, 5] if "--top-short" in argv else [1, 2]
        assert list(workflow._ranks) == expected  # type: ignore[attr-defined]
